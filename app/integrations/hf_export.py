"""hf_export.py -- Sauvegarde AUTOMATIQUE de chaque course (+ audit) sur Hugging Face, et RESTAURATION
au démarrage (v1.29.46, refonte de l'export v1.29.15).

Pourquoi : sur Render (plan sans disque persistant, ou mise en veille / redéploiement) la base SQLite est
perdue -> tout l'historique disparaît. Ici, chaque course est copiée dans un dataset Hugging Face PRIVÉ, et
l'historique manquant est rechargé tout seul à chaque démarrage.

Améliorations par rapport à la v1.29.15 :
  * le dataset est CRÉÉ automatiquement s'il n'existe pas (avant : échec silencieux) ;
  * UN seul commit par envoi (avant : 1 commit par fichier, 8 par course) ;
  * envois en arrière-plan, regroupés (3 s), avec 4 reprises ; jamais bloquant pour l'analyse ;
  * aucune dépendance (HTTP direct) : plus besoin de `huggingface_hub` ;
  * RESTAURATION de l'historique (démarrage + bouton) et rattrapage des courses locales jamais envoyées ;
  * `meta.json` dans chaque dossier (id, urls, dates...) pour pouvoir tout reconstruire.

Un dossier par course, nom lisible (demandé le 21/09/2026) : {JJ-MM-AA}-{discipline}-{hippodrome}-{distance}m
  meta.json · donnees_pre_course.json · rapport_execution.json · resultat_ticket.json · audit_postcourse.json
Le même dossier est mis à jour (upsert) : après l'analyse, puis après l'audit post-course (ticket A et B).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app import config

logger = logging.getLogger("vantage.hf_export")

HF_API = "https://huggingface.co"
_FICHIERS = {"donnees_pre_course.json": "stage_collecte", "rapport_execution.json": "execution_report",
             "resultat_ticket.json": "result", "audit_postcourse.json": "audit"}
_DISCIPLINE_LABELS = {"TROT_ATTELE": "attele", "TROT_MONTE": "monte", "PLAT": "plat", "HAIES": "haies", "STEEPLE": "steeple"}

_state: Dict[str, Any] = {"derniere_sauvegarde": None, "derniere_erreur": None, "envoyees": 0, "restaurees": 0,
                          "en_attente": 0, "restauration": None}
_pending: Dict[str, float] = {}
_cv = threading.Condition()
_worker: Optional[threading.Thread] = None
_repo_ok = False
_DEBOUNCE = 3.0            # secondes (modifiable en test)


# ----------------------------------------------------------------------------------------- configuration
def _token() -> str:
    return (config.HF_TOKEN or "").strip()


_canon: Optional[str] = None      # nom canonique renvoyé par HF (ex. « Golden223/... » même si on a saisi « golden223/... »)


def _repo() -> str:
    cfg = (config.HF_DATASET_REPO or "").strip()
    return _canon if (_canon and _canon.lower() == cfg.lower()) else cfg


def hf_export_enabled() -> bool:
    return config.HF_AUTOSAVE != "0" and bool(_token()) and bool(_repo())


def _call(method: str, url: str, body: Optional[bytes] = None, content_type: Optional[str] = None, timeout: int = 60):
    """Appel HTTP vers HF. v1.29.50 : suit lui-même les redirections 301/302/307/308 en conservant méthode et corps
    (urllib ne le fait pas pour un POST : « commit HF refusé (HTTP 307) » quand la casse du nom de dépôt diffère,
    HF redirigeant « golden223/x » vers « Golden223/x »)."""
    from urllib.parse import urljoin
    headers = {"Authorization": f"Bearer {_token()}", "User-Agent": "protocol-vantage"}
    if content_type:
        headers["Content-Type"] = content_type
    for _ in range(5):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            hdrs = dict(e.headers or {})
            loc = hdrs.get("Location") or hdrs.get("location")
            if e.code in (301, 302, 307, 308) and loc:
                url = urljoin(url, loc)
                continue
            return e.code, e.read(), hdrs
    return 310, b"trop de redirections", {}


def _ensure_repo() -> None:
    """Vérifie que le dataset existe ; sinon tente de le créer. v1.29.50 : on teste d'abord l'EXISTENCE (un jeton
    « fine-grained » peut écrire dans un dépôt existant sans avoir le droit d'en créer : avant, HTTP 403 bloquait tout)."""
    global _repo_ok
    if _repo_ok:
        return
    global _canon
    _canon = None
    code, body, _ = _call("GET", f"{HF_API}/api/datasets/{_repo()}")
    if code == 200:
        try:
            ident = str(json.loads(body).get("id") or "")
            if ident and ident.lower() == (config.HF_DATASET_REPO or "").strip().lower():
                _canon = ident                          # mémorise la casse exacte du dépôt
        except Exception:  # noqa: BLE001
            pass
        _repo_ok = True
        return
    org, _, name = _repo().partition("/")
    payload: Dict[str, Any] = {"type": "dataset", "name": name or org, "private": True}
    if name:
        payload["organization"] = org
    code, body, _ = _call("POST", f"{HF_API}/api/repos/create", json.dumps(payload).encode(), "application/json")
    if code in (200, 201, 409):                          # 409 = existe déjà
        _repo_ok = True
        return
    if code in (401, 403):
        raise RuntimeError(
            f"Jeton sans droit de CRÉER le dataset « {_repo()} » (HTTP {code}). Solution : crée-le toi-même sur "
            f"huggingface.co/new-dataset (nom « {name or org} », visibilité Private), puis clique « tester ». "
            f"Le jeton doit avoir le droit d'ÉCRITURE sur ce dépôt (jeton « Write », ou fine-grained avec "
            f"« Write access to contents/settings of all repos under your personal namespace »).")
    raise RuntimeError(f"accès / création du dataset HF refusé (HTTP {code}) : {body[:160]!r}")


def _commit(files: Dict[str, bytes], message: str) -> None:
    """Un seul commit pour tous les fichiers (API officielle /commit, corps NDJSON, contenus base64)."""
    import base64
    _ensure_repo()
    lines = [json.dumps({"key": "header", "value": {"summary": message[:200]}})]
    for path, data in files.items():
        lines.append(json.dumps({"key": "file", "value": {"content": base64.b64encode(data).decode(),
                                                          "path": path, "encoding": "base64"}}))
    code, body, _ = _call("POST", f"{HF_API}/api/datasets/{_repo()}/commit/main",
                          ("\n".join(lines) + "\n").encode(), "application/x-ndjson", timeout=120)
    if code in (401, 403):
        raise RuntimeError(f"écriture refusée sur « {_repo()} » (HTTP {code}) : le jeton n'a pas le droit d'ÉCRITURE sur ce dataset "
                           f"(utiliser un jeton « Write » ou donner l'écriture à ce dépôt).")
    if code not in (200, 201):
        raise RuntimeError(f"commit HF refusé (HTTP {code}) : {body[:200]!r}")


# ----------------------------------------------------------------------------------------- nommage
def _slugify(text: Optional[str]) -> str:
    if not text:
        return "inconnu"
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(c for c in text if not unicodedata.combining(c)).strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "inconnu"


def race_folder_name(context: Dict[str, Any]) -> str:
    """Dossier HF (inchangé) : {JJ-MM-AA}-{discipline}-{hippodrome}-{distance}m."""
    try:
        date_part = datetime.fromisoformat(str(context.get("date_course"))[:10]).strftime("%d-%m-%y")
    except (ValueError, TypeError):
        date_part = datetime.now(timezone.utc).strftime("%d-%m-%y")
    disc = str(context.get("discipline") or "")
    try:
        dist = f"{int(context.get('distance_m'))}m"
    except (TypeError, ValueError):
        dist = "distance-inconnue"
    return f"{date_part}-{_DISCIPLINE_LABELS.get(disc, _slugify(disc))}-{_slugify(context.get('hippodrome'))}-{dist}"


def race_archive_basename(context: Dict[str, Any], row: Optional[Dict[str, Any]] = None) -> str:
    """Nom lisible pour les téléchargements locaux (ZIP, audit, rapport).

    Format : {AAAA-MM-JJ}_R{n}C{m}_{discipline}_{hippodrome}_{distance}m
    HF conserve race_folder_name() (JJ-MM-AA, sans R+C).
    """
    try:
        date_part = datetime.fromisoformat(str(context.get("date_course"))[:10]).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        date_part = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    label = ""
    if row:
        label = str(row.get("reunion_course_label") or "")
    if not label:
        label = str(context.get("reunion_course_label") or "")
    m = re.search(r"R\s*(\d{1,2})\s*C\s*(\d{1,2})", label, re.I)
    if m:
        rc = f"R{int(m.group(1))}C{int(m.group(2))}"
    else:
        rn, cn = context.get("reunion_num"), context.get("course_num")
        try:
            rc = f"R{int(rn)}C{int(cn)}" if rn is not None and cn is not None else "RxCx"
        except (TypeError, ValueError):
            rc = "RxCx"

    disc = str(context.get("discipline") or "")
    disc_slug = _DISCIPLINE_LABELS.get(disc, _slugify(disc))
    hippo = _slugify(context.get("hippodrome") or (row or {}).get("hippodrome"))
    try:
        dist = f"{int(context.get('distance_m'))}m"
    except (TypeError, ValueError):
        dist = "distance-inconnue"
    return f"{date_part}_{rc}_{disc_slug}_{hippo}_{dist}"


def archive_basename_for_race(race_id: str, row: Optional[Dict[str, Any]] = None) -> str:
    """Résout le basename d'archive à partir d'une course en base (repli sur race_id)."""
    from app import db
    if row is None:
        row = db.get_race(race_id) or {}
    ctx = _context(row)
    if not ctx and not row:
        return f"course_{race_id}"
    base = race_archive_basename(ctx or {}, row)
    # Si presque tout est « inconnu », garder un suffixe court d'id pour l'unicité
    if base.count("inconnu") >= 2 or base.endswith("_RxCx_inconnu_distance-inconnue"):
        return f"{base}_{race_id[:6]}"
    return base


def _folder_sort_key(folder: str):
    m = re.match(r"(\d{2})-(\d{2})-(\d{2})-", folder)
    return (m.group(3), m.group(2), m.group(1)) if m else ("00", "00", "00")


def _context(row: Dict[str, Any]) -> Dict[str, Any]:
    return (row.get("stage_collecte") or {}).get("race") or (row.get("result") or {}).get("context") or {}


# ----------------------------------------------------------------------------------------- envoi
def push_race(race_id: str) -> Dict[str, Any]:
    from app import db
    row = db.get_race(race_id)
    if not row:
        return {"status": "INTROUVABLE"}
    ctx = _context(row)
    if not ctx:
        return {"status": "SKIPPED_NO_CONTEXT"}
    folder = race_folder_name(ctx)
    from app.version import VERSION_BUILD
    meta = {"race_id": row["id"], "urls": row.get("urls"), "status": row.get("status"), "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"), "hippodrome": row.get("hippodrome") or ctx.get("hippodrome"),
            "reunion_course_label": row.get("reunion_course_label"), "error": row.get("error"),
            "date_course": ctx.get("date_course"), "version_moteur": VERSION_BUILD, "a_un_audit": bool(row.get("audit"))}
    files = {f"{folder}/meta.json": json.dumps(meta, ensure_ascii=False, indent=2, default=str).encode("utf-8")}
    for fname, key in _FICHIERS.items():
        if row.get(key):
            files[f"{folder}/{fname}"] = json.dumps(row[key], ensure_ascii=False, indent=2, default=str).encode("utf-8")
    _commit(files, f"vantage: {race_id} ({folder}){' + audit' if row.get('audit') else ''}")
    return {"status": "OK", "folder": folder, "files": [p.split("/")[-1] for p in files]}


def _loop() -> None:
    while True:
        with _cv:
            while not _pending:
                _cv.wait()
            _cv.wait(timeout=_DEBOUNCE)                  # regroupe les déclenchements rapprochés
            batch = list(_pending)
            _pending.clear()
            _state["en_attente"] = 0
        for rid in batch:
            for essai in range(4):
                try:
                    res = push_race(rid)
                    if res.get("status") == "OK":
                        _state["envoyees"] += 1
                        _state["derniere_sauvegarde"] = {"id": rid, "dossier": res["folder"], "le": datetime.now(timezone.utc).isoformat()}
                        _state["derniere_erreur"] = None
                    break
                except Exception as e:  # noqa: BLE001
                    _state["derniere_erreur"] = f"{rid}: {str(e)[:200]}"
                    logger.warning("Sauvegarde HF échouée (%s, essai %d/4) : %s", rid, essai + 1, str(e)[:160])
                    time.sleep(2 ** (essai + 1))


def schedule(race_id: str) -> None:
    """Met la course en file d'envoi (non bloquant, ne lève jamais)."""
    global _worker
    try:
        if not hf_export_enabled():
            return
        with _cv:
            _pending[race_id] = time.time()
            _state["en_attente"] = len(_pending)
            if _worker is None or not _worker.is_alive():
                _worker = threading.Thread(target=_loop, name="hf-sync", daemon=True)
                _worker.start()
            _cv.notify_all()
    except Exception as e:  # noqa: BLE001
        logger.warning("hf schedule: %s", e)


def sync_race_to_hf(race_id: str, race_record: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Compatibilité v1.29.15 (appelée par l'orchestrateur et l'audit) : met en file, ne bloque jamais."""
    if not hf_export_enabled():
        return {"status": "DISABLED"}
    schedule(race_id)
    return {"status": "QUEUED"}


# ----------------------------------------------------------------------------------------- restauration
def _list_folders() -> List[str]:
    url = f"{HF_API}/api/datasets/{_repo()}/tree/main?limit=1000"
    out: List[str] = []
    while url:
        code, body, headers = _call("GET", url)
        if code == 404:
            return []
        if code != 200:
            raise RuntimeError(f"liste HF refusée (HTTP {code})")
        out += [x["path"] for x in json.loads(body) if x.get("type") == "directory" and not x["path"].startswith("_")]
        url = ""
        for part in (headers.get("Link") or headers.get("link") or "").split(","):
            if 'rel="next"' in part and "<" in part:
                url = part[part.index("<") + 1: part.index(">")]
    return sorted(out, key=_folder_sort_key, reverse=True)


def _get_json(folder: str, fname: str):
    code, body, _ = _call("GET", f"{HF_API}/datasets/{_repo()}/resolve/main/{folder}/{fname}")
    return json.loads(body.decode("utf-8")) if code == 200 else None


def restore(limit: Optional[int] = None, overwrite: bool = False) -> Dict[str, Any]:
    """Recharge dans SQLite les courses absentes (toutes si overwrite). Dossiers anciens sans meta.json : id reconstruit."""
    from app import db
    if not (_token() and _repo()):
        return {"ok": False, "raison": "HF_TOKEN / HF_DATASET_REPO non configurés"}
    limit = limit or config.HF_RESTORE_LIMIT
    bilan = {"ok": True, "dossiers_sur_hf": 0, "restaurees": 0, "deja_presentes": 0, "echecs": 0}
    folders = _list_folders()[:limit]
    bilan["dossiers_sur_hf"] = len(folders)
    for folder in folders:
        try:
            meta = _get_json(folder, "meta.json") or {}
            rid = meta.get("race_id") or ("hf" + hashlib.sha1(folder.encode()).hexdigest()[:10])
            if not overwrite and db.get_race(rid):
                bilan["deja_presentes"] += 1
                continue
            row: Dict[str, Any] = {"id": rid, "urls": meta.get("urls") or [], "status": meta.get("status") or "TERMINE",
                                   "created_at": meta.get("created_at"), "updated_at": meta.get("updated_at"),
                                   "hippodrome": meta.get("hippodrome"), "reunion_course_label": meta.get("reunion_course_label"),
                                   "error": meta.get("error")}
            for fname, key in _FICHIERS.items():
                row[key] = _get_json(folder, fname)
            if not row.get("created_at"):
                ctx = _context(row)
                row["created_at"] = f"{str(ctx.get('date_course') or '')[:10] or '1970-01-01'}T00:00:00+00:00"
                row["updated_at"] = row["created_at"]
            if not (row.get("result") or row.get("stage_collecte")):
                raise ValueError("dossier sans données exploitables")
            db.insert_row(row)
            bilan["restaurees"] += 1
        except Exception as e:  # noqa: BLE001
            bilan["echecs"] += 1
            logger.warning("Restauration HF de %s échouée : %s", folder, e)
    _state["restaurees"] += bilan["restaurees"]
    _state["restauration"] = {**bilan, "le": datetime.now(timezone.utc).isoformat()}
    return bilan


def push_batch(batch_id: str, payload: Dict[str, Any]) -> bool:
    """Sauvegarde l'état d'un lot (courses demandées + statuts) : la file survit à un redémarrage de Render."""
    if not hf_export_enabled():
        return False
    _commit({f"_lots/{batch_id}.json": json.dumps(payload, ensure_ascii=False, indent=1, default=str).encode("utf-8")},
            f"lot {batch_id}")
    return True


def restore_batches() -> int:
    """Recharge les lots absents de la base locale (courses en attente = reprises ensuite par batch.resume_on_startup)."""
    from app import batch
    if not (_token() and _repo()):
        return 0
    code, body, _ = _call("GET", f"{HF_API}/api/datasets/{_repo()}/tree/main/_lots")
    if code != 200:
        return 0
    n = 0
    for f in json.loads(body):
        if f.get("type") != "file" or not f["path"].endswith(".json"):
            continue
        code2, raw, _ = _call("GET", f"{HF_API}/datasets/{_repo()}/resolve/main/{f['path']}")
        if code2 == 200:
            try:
                n += 1 if batch.import_batch(json.loads(raw.decode("utf-8"))) else 0
            except Exception as e:  # noqa: BLE001
                logger.warning("Lot %s non restauré : %s", f["path"], e)
    return n


def sync_all(only_missing: bool = True) -> Dict[str, Any]:
    """Rattrapage : envoie les courses locales absentes du dataset (reconnues via meta.json, sinon via le nom du dossier)."""
    from app import db
    if not hf_export_enabled():
        return {"ok": False, "raison": "HF non configuré ou désactivé"}
    deja = set()
    if only_missing:
        try:
            for folder in _list_folders():
                meta = _get_json(folder, "meta.json") or {}
                if meta.get("race_id"):
                    deja.add(meta["race_id"])
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "raison": str(e)[:200]}
    a_envoyer = [r["id"] for r in db.list_races(100000) if r["id"] not in deja]
    for rid in a_envoyer:
        schedule(rid)
    return {"ok": True, "mises_en_file": len(a_envoyer), "deja_sur_hf": len(deja)}


def test_connection() -> Dict[str, Any]:
    """Vérifie jeton + dépôt : crée le dataset si besoin, écrit puis relit un fichier."""
    if not (_token() and _repo()):
        return {"ok": False, "raison": "Renseigner HF_TOKEN et HF_DATASET_REPO dans Render."}
    try:
        stamp = datetime.now(timezone.utc).isoformat()
        _commit({"_connexion_ok.json": json.dumps({"ok": True, "le": stamp}).encode()}, "test de connexion")
        code, body, _ = _call("GET", f"{HF_API}/datasets/{_repo()}/resolve/main/_connexion_ok.json")
        return {"ok": code == 200 and stamp.encode() in body, "ecriture": True, "relecture_http": code}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "raison": str(e)[:300]}


def status() -> Dict[str, Any]:
    from app import db
    return {"actif": hf_export_enabled(), "depot": _repo() or None, "jeton_present": bool(_token()),
            "autosave": config.HF_AUTOSAVE != "0", "restauration_au_demarrage": config.HF_RESTORE_ON_START != "0",
            "courses_locales": len(db.list_races(100000)), **_state}


def startup_restore() -> None:
    """Au démarrage : recharge l'historique manquant puis envoie ce qui n'existe que localement (arrière-plan)."""
    if not hf_export_enabled() or config.HF_RESTORE_ON_START == "0":
        return

    def _run():
        try:
            restore()
            restore_batches()
            sync_all(only_missing=True)
        except Exception as e:  # noqa: BLE001
            _state["derniere_erreur"] = f"restauration: {str(e)[:200]}"
            logger.warning("Restauration HF au démarrage échouée : %s", e)
        finally:
            try:                                           # la file de lots ne reprend qu'APRÈS la restauration
                from app import batch
                batch.resume_on_startup()
            except Exception as e:  # noqa: BLE001
                logger.warning("Reprise du lot : %s", e)
    threading.Thread(target=_run, name="hf-restore", daemon=True).start()
