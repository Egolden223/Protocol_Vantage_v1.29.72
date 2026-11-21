"""batch.py -- Lot de courses walk-forward (v1.29.53) : analyse + audit automatique, une course après l'autre.

Besoin : valider / calibrer sur ~50 courses historiques sans relancer chacune à la main (~5 min chacune).
  * file d'attente PERSISTANTE (SQLite) : reprise automatique après un redémarrage de Render ;
  * exécution séquentielle avec pause entre courses (ménage les quotas des sources et des IA gratuites) ;
  * audit post-course automatique (A + B + résultats complets + analyse IA) ;
  * suivi (statuts, durée, erreur) et EXPORT CSV (une ligne par course) pour les calibrations ;
  * chaque course est aussi sauvegardée sur Hugging Face par l'export automatique.
Saisie : une course par ligne -> « 2026-10-11 R1C3 Auteuil » · « 11/10/2026 R1 C3 » · « 2026-10-11;1;3 ».
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app import db

logger = logging.getLogger("vantage.batch")

_cv = threading.Condition()
_worker: Optional[threading.Thread] = None
_cancel: set = set()
PAUSE_S = 10.0                 # pause entre deux courses (modifiable en test)

_DATE = r"(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})"
_RC = re.compile(_DATE + r"\s*[;,\s]\s*(?:R\s*)?(\d{1,2})\s*[;,\sC]\s*C?\s*(\d{1,2})\s*(?:[;,\s]\s*(.*))?$", re.I)


def ensure_table() -> None:
    with db._lock, db._connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS batch_items (
            id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, position INTEGER NOT NULL, spec TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING', race_id TEXT, error TEXT, started_at TEXT, ended_at TEXT,
            options TEXT)""")
        c.commit()


def parse_lines(texte: str) -> List[Dict[str, Any]]:
    """Une course par ligne. Retourne [{date, reunion_num, course_num, hippodrome?}] ; lève ValueError listant les lignes illisibles."""
    out, mauvaises = [], []
    for brut in (texte or "").splitlines():
        ligne = brut.strip()
        if not ligne or ligne.startswith("#"):
            continue
        m = _RC.match(ligne)
        if not m:
            mauvaises.append(ligne)
            continue
        d = m.group(1)
        if "/" in d:
            j, mo, a = d.split("/")
            d = f"{a}-{mo}-{j}"
        spec = {"date": d, "reunion_num": int(m.group(2)), "course_num": int(m.group(3))}
        reste = (m.group(4) or "").strip(" ;,")
        if reste:
            spec["hippodrome"] = reste
        out.append(spec)
    if mauvaises:
        raise ValueError("Lignes illisibles (attendu « AAAA-MM-JJ R1C3 [hippodrome] ») : " + " | ".join(mauvaises[:5]))
    if not out:
        raise ValueError("Aucune course dans la saisie.")
    return out


def enqueue(specs: List[Dict[str, Any]], auto_audit: bool = True, pause_s: Optional[float] = None) -> str:
    ensure_table()
    batch_id = uuid.uuid4().hex[:10]
    opts = json.dumps({"auto_audit": bool(auto_audit), "pause_s": PAUSE_S if pause_s is None else float(pause_s)})
    with db._lock, db._connect() as c:
        for i, sp in enumerate(specs):
            c.execute("INSERT INTO batch_items (id, batch_id, position, spec, status, options) VALUES (?,?,?,?, 'PENDING', ?)",
                      (uuid.uuid4().hex[:12], batch_id, i, json.dumps(sp, ensure_ascii=False), opts))
        c.commit()
    _backup(batch_id)
    start_worker()
    return batch_id


def _items(batch_id: Optional[str] = None) -> List[Dict[str, Any]]:
    ensure_table()
    with db._lock, db._connect() as c:
        if batch_id:
            rows = c.execute("SELECT * FROM batch_items WHERE batch_id=? ORDER BY position", (batch_id,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM batch_items ORDER BY batch_id, position").fetchall()
    return [dict(r) for r in rows]


def _backup(batch_id: str) -> None:
    """Copie l'état du lot sur Hugging Face (jamais bloquant)."""
    try:
        from app.integrations import hf_export
        if not hf_export.hf_export_enabled():
            return
        items = _items(batch_id)
        hf_export.push_batch(batch_id, {"batch_id": batch_id, "items": [
            {"id": it["id"], "position": it["position"], "spec": json.loads(it["spec"]), "status": it["status"],
             "race_id": it["race_id"], "error": it["error"], "options": json.loads(it["options"] or "{}")} for it in items]})
    except Exception as e:  # noqa: BLE001
        logger.warning("Sauvegarde du lot %s impossible : %s", batch_id, e)


def import_batch(payload: Dict[str, Any]) -> bool:
    """Réinsère un lot sauvegardé s'il n'existe pas localement (RUNNING -> PENDING). Retourne True si importé."""
    ensure_table()
    bid = payload.get("batch_id")
    if not bid or _items(bid):
        return False
    with db._lock, db._connect() as c:
        for it in payload.get("items", []):
            st = "PENDING" if it.get("status") == "RUNNING" else it.get("status", "PENDING")
            c.execute("INSERT OR IGNORE INTO batch_items (id, batch_id, position, spec, status, race_id, error, options) VALUES (?,?,?,?,?,?,?,?)",
                      (it["id"], bid, it["position"], json.dumps(it["spec"], ensure_ascii=False), st, it.get("race_id"),
                       it.get("error"), json.dumps(it.get("options") or {})))
        c.commit()
    return True


def status(batch_id: str) -> Dict[str, Any]:
    items = _items(batch_id)
    if not items:
        return {"batch_id": batch_id, "existe": False}
    compte: Dict[str, int] = {}
    for it in items:
        compte[it["status"]] = compte.get(it["status"], 0) + 1
    det = []
    for it in items:
        sp = json.loads(it["spec"])
        det.append({"position": it["position"] + 1, **sp, "status": it["status"], "race_id": it["race_id"],
                    "erreur": (it["error"] or "")[:200] or None})
    return {"batch_id": batch_id, "existe": True, "total": len(items), "compte": compte,
            "termine": all(it["status"] in ("DONE", "FAILED", "CANCELLED") for it in items), "items": det}


def list_batches() -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, int]] = {}
    for it in _items():
        seen.setdefault(it["batch_id"], {})
        seen[it["batch_id"]][it["status"]] = seen[it["batch_id"]].get(it["status"], 0) + 1
    return [{"batch_id": b, "compte": c, "total": sum(c.values())} for b, c in seen.items()]


def cancel(batch_id: str) -> int:
    ensure_table()
    _cancel.add(batch_id)
    with db._lock, db._connect() as c:
        n = c.execute("UPDATE batch_items SET status='CANCELLED' WHERE batch_id=? AND status='PENDING'", (batch_id,)).rowcount
        c.commit()
    return n


def retry_failed(batch_id: str) -> int:
    ensure_table()
    _cancel.discard(batch_id)
    with db._lock, db._connect() as c:
        n = c.execute("UPDATE batch_items SET status='PENDING', error=NULL WHERE batch_id=? AND status IN ('FAILED','CANCELLED')",
                      (batch_id,)).rowcount
        c.commit()
    if n:
        start_worker()
    return n


# ------------------------------------------------------------------------------------------- exécution
def launch_one(spec: Dict[str, Any], auto_audit: bool = True) -> str:
    """Identifie la course (découverte multi-sources), exécute le pipeline et l'audit. Retourne le race_id."""
    from app.orchestrator import run_pipeline
    from app.scraping.discovery_multi import discover_all_sources
    from app.scraping.hippodrome_normalize import resolve_hippodrome
    hippo = spec.get("hippodrome")
    if hippo:
        res, score = resolve_hippodrome(hippo)
        if res and score >= 0.72:
            hippo = res
    report = discover_all_sources(spec["date"], hippo, spec.get("course_num"), None, spec.get("reunion_num"))
    if report.sources_reussies < 2 or not report.urls:
        raise RuntimeError(f"identification insuffisante : {report.sources_reussies}/{report.sources_applicables} source(s) "
                           f"({json.dumps(report.par_source, ensure_ascii=False, default=str)[:300]})")
    race_id = uuid.uuid4().hex[:12]
    db.create_race(race_id, report.urls)
    run_pipeline(race_id, report.urls, auto_audit, {
        "urls": report.urls, "taux_collecte": report.taux_collecte, "par_source": report.par_source,
        "hippodrome_attendu": hippo, "date": spec["date"], "reunion_num": spec.get("reunion_num"),
        "course_num": spec.get("course_num")})
    return race_id


def _claim_next() -> Optional[Dict[str, Any]]:
    ensure_table()
    with db._lock, db._connect() as c:
        row = c.execute("SELECT * FROM batch_items WHERE status='PENDING' ORDER BY batch_id, position LIMIT 1").fetchone()
        if not row:
            return None
        c.execute("UPDATE batch_items SET status='RUNNING', started_at=? WHERE id=?",
                  (datetime.now(timezone.utc).isoformat(), row["id"]))
        c.commit()
        return dict(row)


def _finish(item_id: str, status_: str, race_id: Optional[str] = None, error: Optional[str] = None) -> None:
    with db._lock, db._connect() as c:
        c.execute("UPDATE batch_items SET status=?, race_id=COALESCE(?, race_id), error=?, ended_at=? WHERE id=?",
                  (status_, race_id, error, datetime.now(timezone.utc).isoformat(), item_id))
        c.commit()


def _loop() -> None:
    global _worker
    while True:
        with _cv:                          # même verrou que start_worker : pas de course entre « file vide » et « worker vivant »
            item = _claim_next()
            if item is None:
                _worker = None
                return
        opts = json.loads(item.get("options") or "{}")
        try:
            spec = json.loads(item["spec"])
            race_id = launch_one(spec, opts.get("auto_audit", True))
            r = db.get_race(race_id) or {}
            ok = r.get("status") in ("TERMINE",)
            _finish(item["id"], "DONE" if ok else "FAILED", race_id, None if ok else (r.get("error") or r.get("status") or "")[:400])
        except Exception as e:  # noqa: BLE001  (une course en échec n'arrête jamais le lot)
            logger.warning("Lot %s : course %s en échec : %s", item["batch_id"], item["spec"], e)
            _finish(item["id"], "FAILED", None, f"{type(e).__name__}: {str(e)[:300]}")
        _backup(item["batch_id"])
        time.sleep(float(opts.get("pause_s", PAUSE_S)))


def start_worker() -> None:
    global _worker
    with _cv:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, name="batch-worker", daemon=True)
            _worker.start()


def resume_on_startup() -> None:
    """Après un redémarrage : une course « RUNNING » interrompue repart en « PENDING », puis la file reprend."""
    try:
        ensure_table()
        with db._lock, db._connect() as c:
            c.execute("UPDATE batch_items SET status='PENDING' WHERE status='RUNNING'")
            n = c.execute("SELECT COUNT(*) FROM batch_items WHERE status='PENDING'").fetchone()[0]
            c.commit()
        if n:
            logger.info("Lot : %d course(s) en attente reprises après démarrage.", n)
            start_worker()
    except Exception as e:  # noqa: BLE001
        logger.warning("Reprise du lot impossible : %s", e)


# ------------------------------------------------------------------------------------------- export CSV
COLONNES = ["lot", "position", "date", "hippodrome", "reunion_course", "discipline", "partants", "mode", "statut_course",
            "statut_lot", "race_id", "captures_A", "captures_B", "captures_C", "marche_top8", "ordre_top8", "A_moins_marche", "B_moins_marche",
            "C_moins_marche", "top5_reel", "incidents_ticket_A",
            "captures_shadow_A", "captures_shadow_B", "captures_shadow_C",
            "shadow_b3_top5_A", "shadow_b3_top5_B", "shadow_b3_top5_C", "shadow_desordre_k2_A", "shadow_desordre_k2_B", "shadow_desordre_k2_C",
            "shadow_desordre_k3_A", "shadow_desordre_k3_B", "shadow_desordre_k3_C", "captures_shadow_garde_A", "favori_cote", "filtre_course", "erreur"]


def export_csv(batch_id: str) -> str:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=COLONNES, delimiter=";", extrasaction="ignore")
    w.writeheader()
    for it in _items(batch_id):
        sp = json.loads(it["spec"])
        row: Dict[str, Any] = {"lot": batch_id, "position": it["position"] + 1, "date": sp.get("date"),
                               "hippodrome": sp.get("hippodrome"), "reunion_course": f"R{sp.get('reunion_num')}C{sp.get('course_num')}",
                               "statut_lot": it["status"], "race_id": it["race_id"], "erreur": it["error"]}
        r = db.get_race(it["race_id"]) if it["race_id"] else None
        if r:
            ctx = (r.get("result") or {}).get("context") or {}
            aud = r.get("audit") or {}
            bl = aud.get("baselines_contrefactuelles") or {}
            row.update({"hippodrome": ctx.get("hippodrome") or row["hippodrome"], "discipline": ctx.get("discipline"),
                        "partants": (aud.get("contexte_dataset") or {}).get("partants"),
                        "mode": ((r.get("result") or {}).get("json_output") or {}).get("mode_execution"),
                        "statut_course": r.get("status"), "captures_A": aud.get("nb_captures"),
                        "captures_B": (aud.get("audit_ticket_B") or {}).get("nb_captures"),
                        "captures_C": (aud.get("audit_ticket_C") or {}).get("nb_captures"),
                        "C_moins_marche": (None if bl.get("ticket_C_ancre") is None or bl.get("marche_top8") is None
                                           else bl["ticket_C_ancre"] - bl["marche_top8"]),
                        "marche_top8": bl.get("marche_top8"), "ordre_top8": bl.get("ordre_final_top8"),
                        "A_moins_marche": bl.get("ticket_moins_marche"),
                        "B_moins_marche": (None if bl.get("ticket_B_quotas") is None or bl.get("marche_top8") is None
                                           else bl["ticket_B_quotas"] - bl["marche_top8"]),
                        "top5_reel": " ".join(str(x.get("numero")) for x in (aud.get("arrivee_officielle_top5") or [])),
                        "incidents_ticket_A": (aud.get("bilan_ticket") or {}).get("nb_incidents_course"),
                        **{f"captures_shadow_{t_}": (bl.get("shadow_captures") or {}).get(t_) for t_ in "ABC"},
                        **{f"shadow_b3_top5_{t_}": (((bl.get("shadow_v69") or {}).get("tickets") or {}).get(t_) or {}).get("k3", {}).get("bases_dans_top5") for t_ in "ABC"},
                        **{f"shadow_desordre_k2_{t_}": (((bl.get("shadow_v69") or {}).get("tickets") or {}).get(t_) or {}).get("k2", {}).get("desordre") for t_ in "ABC"},
                        **{f"shadow_desordre_k3_{t_}": (((bl.get("shadow_v69") or {}).get("tickets") or {}).get(t_) or {}).get("k3", {}).get("desordre") for t_ in "ABC"},
                        "captures_shadow_garde_A": ((((bl.get("shadow_v69") or {}).get("tickets") or {}).get("A") or {}).get("captures_garde_t1")),
                        "favori_cote": ((bl.get("shadow_v69") or {}).get("signal_course") or {}).get("favori_cote"),
                        "filtre_course": ((bl.get("shadow_v69") or {}).get("signal_course") or {}).get("niveau"),})
        w.writerow(row)
    return out.getvalue()


# ------------------------------------------------------------------------------------------- export global pour analyse
_COURSES_COLS = ["race_id", "date_course", "hippodrome", "reunion_course", "discipline", "distance_m", "partants", "mode",
                 "statut", "version_moteur", "captures_A", "captures_B", "captures_C", "marche_top8", "ordre_top8", "hasard_attendu",
                 "A_moins_marche", "B_moins_marche", "C_moins_marche", "top5_reel", "rang_moyen_reel_A", "incidents_A", "proches_A", "hors_place_A",
                 "captures_shadow_A", "captures_shadow_B", "captures_shadow_C",
                 "shadow_b3_top5_A", "shadow_b3_top5_B", "shadow_b3_top5_C", "shadow_desordre_k2_A", "shadow_desordre_k2_B", "shadow_desordre_k2_C",
                 "shadow_desordre_k3_A", "shadow_desordre_k3_B", "shadow_desordre_k3_C", "captures_shadow_garde_A", "favori_cote", "filtre_course", 
                 "ia_post_course_chevaux_expliques", "ia_post_course_chevaux_analyses", "anomalies_donnees", "avec_audit",
                 "signature", "iic_v2", "iic_marche", "grille_B_cible", "grille_B_appliquee", "ecart_grille_B",
                 "captures_attendues_B", "captures_attendues_B_sans_grille",
                 "desordre_A", "bonus_A", "ordre_A", "desordre_B", "bonus_B", "ordre_B", "desordre_C", "bonus_C", "ordre_C",
                 "ordre_prevu_A", "ordre_prevu_B", "ordre_prevu_C", "p_desordre_A", "p_desordre_B", "p_desordre_C",
                 # v1.29.62 : contexte de course (terrain, météo, rythme) + COUVERTURE des données par course (part de partants renseignés)
                 "type_course", "depart", "allocation_eur", "penetrometre", "terrain_qualificatif", "conditions_particulieres",
                 "meteo_temp_c", "meteo_vent_kmh_max", "meteo_risque_pluie", "rythme_projete", "nb_meneurs_champ",
                 "couv_driver", "couv_driver_precedent", "couv_entraineur", "couv_proprietaire", "couv_oeilleres", "couv_ferrure_type",
                 "couv_deferre", "couv_driver_stats", "couv_trainer_stats", "couv_tandem", "couv_cotes_bookmakers", "couv_timeline_cotes",
                 "couv_rk", "couv_chrono_200m", "couv_record_chrono", "couv_feu_equidia", "couv_p_avant_valeurs_distinctes",
                 # v1.29.63 : DIAGNOSTIC des données qui conditionnent B11 / B12 / classements, corde empirique, pépite / piège, p_avant, Equidia
                 "diag_classements_drivers", "diag_classements_entraineurs", "diag_corpus_hippodrome", "diag_corpus_similaires",
                 "diag_biais_corde_possible", "diag_chevaux_avec_place_corde", "diag_p_avant_valeurs", "diag_p_avant_proxy_musique",
                 "diag_chevaux_avec_driver", "diag_chevaux_avec_changement_driver", "equidia_status", "equidia_reason", "turf_bzh_status",
                 "n_signal_B11", "n_signal_B12", "n_flag_biais_corde", "n_flag_piege_numero", "n_flag_piege_as", "n_flag_pepite_actif",
                 "n_flag_pepite_faible", "n_flag_pepite_sous_seuil",
                 "B_famille", "B_portees", "B_alpha_marche", "B_recouvrement_C", "B_identique_C", "B_gru_chevaux_modifies", "B_gru_delta_max_abs", "B_lab_chevaux_changes", "B_pepite_entrees", "B_rerank_modifie", "B_lab_gru", "B_lab_classements", "B_lab_pepite", "B_lab_piege", "B_lab_g30", "B_lab_corde",
                 # v1.29.64 : déclenchements des renforcements GRU à poids maîtrisé
                 "n_signal_G10", "n_signal_G30", "n_signal_G56", "n_signal_G58", "n_signal_G59", "n_signal_G60", "n_signal_G61", "n_signal_G62",
                 "n_signal_G63", "n_signal_G64", "n_flag_piege_mult", "n_flag_pool_pepite", "n_flag_piege_skip_mf"]
_PARTANTS_COLS = ["race_id", "date_course", "hippodrome", "discipline", "mode", "partants", "numero", "cote_matin",
                  "cote_avant_course", "tranche", "ordre_final", "composite", "pch_final", "tocard_score", "musique", "age", "sexe",
                  "dans_ticket_A", "dans_ticket_B", "dans_ticket_C", "top5", "rang_reel", "rang_complet", "incident"]


def _num_cols(prefix: str, d: Dict[str, Any]) -> Dict[str, Any]:
    """Aplatit les champs NUMÉRIQUES d'un dict (bool et chaînes exclus) en colonnes préfixées."""
    out: Dict[str, Any] = {}
    for k, v in (d or {}).items():
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (int, float)):
            out[f"{prefix}{k}"] = v
    return out


_TXT_CHAMPS = ("driver_jockey", "driver_precedent", "entraineur", "proprietaire", "oeilleres", "ferrure_type", "deferre",
               "feu_equidia", "pattern_incidents", "style_mpa")
_BOOL_CHAMPS = ("driver_est_entraineur", "favori_unanime", "sov_repli_utilise", "niveau_max_hors_pattern_europeen")
_NESTED = (("driver_stats", "ds_"), ("trainer_stats", "ts_"), ("tandem_driver_cheval", "tdc_"), ("tandem_driver_ecurie", "tde_"))


def _flat_num(prefix: str, obj: Any, depth: int = 3) -> Dict[str, Any]:
    """Aplatit récursivement les valeurs numériques (et booléennes -> 0/1) d'un dict ; une liste de fenêtres {jours, victoires, courses}
    devient `<prefix>w<jours>_victoires` / `_courses` / `_taux`."""
    out: Dict[str, Any] = {}
    if depth < 0 or obj is None:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, bool):
                out[f"{prefix}{k}"] = int(v)
            elif isinstance(v, (int, float)):
                out[f"{prefix}{k}"] = v
            elif isinstance(v, list) and v and all(isinstance(w, dict) and "jours" in w for w in v):
                out.update(_flat_num(prefix, v, depth - 1))                # fenêtres : <prefix>w<jours>_*
            elif isinstance(v, (dict, list)):
                out.update(_flat_num(f"{prefix}{k}_", v, depth - 1))
    elif isinstance(obj, list):
        for i, w in enumerate(obj):
            if isinstance(w, dict) and isinstance(w.get("jours"), (int, float)):
                lab = f"{prefix}w{int(w['jours'])}_"
                for k in ("victoires", "courses"):
                    if isinstance(w.get(k), (int, float)):
                        out[f"{lab}{k}"] = w[k]
                if w.get("courses"):
                    out[f"{lab}taux"] = round((w.get("victoires") or 0) / w["courses"], 4)
            elif isinstance(w, dict):
                out.update(_flat_num(f"{prefix}{i}_", w, depth - 1))
    return out


def _champs_bruts(ch: Dict[str, Any]) -> Dict[str, Any]:
    """v1.29.62 : champs du cheval que `_num_cols` écartait (textes, booléens, sous-objets) — driver, entraîneur, œillères,
    ferrure / déferrage, stats driver / entraîneur / tandem, cotes par bookmaker, timeline de cotes, RK."""
    out: Dict[str, Any] = {}
    for k in _TXT_CHAMPS:
        v = ch.get(k)
        if v is not None and str(v).strip() != "":
            out[f"tx_{k}"] = str(v).strip()[:60]
    for k in _BOOL_CHAMPS:
        if isinstance(ch.get(k), bool):
            out[f"bo_{k}"] = int(ch[k])
    dj, dp = (ch.get("driver_jockey") or "").strip().lower(), (ch.get("driver_precedent") or "").strip().lower()
    if dj and dp:
        out["chg_driver"] = int(dj != dp)
    oe = (ch.get("oeilleres") or "")
    if oe:
        out["oeilleres_presentes"] = int("SANS" not in oe.upper())
        out["oeilleres_premiere_fois"] = int("PREMIERE" in oe.upper())
    if "deferre" in ch:
        out["deferre_present"] = int(bool(str(ch.get("deferre") or "").strip()))
    if ch.get("ferrure_type") is not None:
        out["ferrure_type_present"] = int(bool(str(ch.get("ferrure_type")).strip()))
    for key, pre in _NESTED:
        out.update(_flat_num(pre, ch.get(key)))
    cb = ch.get("cotes_bookmakers")
    if isinstance(cb, dict) and cb:
        vals = [float(v) for v in cb.values() if isinstance(v, (int, float)) and v > 0]
        for b, v in cb.items():
            if isinstance(v, (int, float)):
                out[f"cbk_{str(b).lower()}"] = v
        out["cbk_n"] = len(vals)
        if len(vals) >= 2:
            out["cbk_ecart_rel"] = round((max(vals) - min(vals)) / (sum(vals) / len(vals)), 4)
    tl = ch.get("cotes_timeline")
    if isinstance(tl, list) and tl:
        c = [float(x["cote"]) for x in tl if isinstance(x, dict) and isinstance(x.get("cote"), (int, float)) and x["cote"] > 0]
        out["ctl_n"] = len(c)
        if len(c) >= 2:
            out["ctl_var_rel"] = round((c[-1] - c[0]) / c[0], 4)
    rk = ch.get("rk_array_3_derniers_sec")
    if isinstance(rk, list) and rk:
        v = [float(x) for x in rk if isinstance(x, (int, float))]
        if v:
            out["rk3_moy"] = round(sum(v) / len(v), 3)
    return out


def _couverture(feats: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    """Part de partants avec la donnée renseignée, par course -> colonnes `couv_*` de courses.csv (contrôle de la collecte)."""
    n = len(feats) or 1
    def part(pred) -> float:
        return round(sum(1 for f in feats.values() if pred(f)) / n, 3)
    has = lambda k: (lambda f: k in f)
    pav = {f.get("ch_p_avant") for f in feats.values() if f.get("ch_p_avant") is not None}
    return {"couv_driver": part(has("tx_driver_jockey")), "couv_driver_precedent": part(has("tx_driver_precedent")),
            "couv_entraineur": part(has("tx_entraineur")), "couv_proprietaire": part(has("tx_proprietaire")),
            "couv_oeilleres": part(has("tx_oeilleres")), "couv_ferrure_type": part(has("tx_ferrure_type")),
            "couv_deferre": part(has("tx_deferre")), "couv_driver_stats": part(lambda f: any(k.startswith("ds_") for k in f)),
            "couv_trainer_stats": part(lambda f: any(k.startswith("ts_") for k in f)),
            "couv_tandem": part(lambda f: any(k.startswith(("tdc_", "tde_")) for k in f)),
            "couv_cotes_bookmakers": part(lambda f: f.get("cbk_n", 0) >= 1), "couv_timeline_cotes": part(lambda f: f.get("ctl_n", 0) >= 2),
            "couv_rk": part(has("ch_rk_derniere_sec")), "couv_chrono_200m": part(has("ch_chrono_200m")),
            "couv_record_chrono": part(has("ch_record_chrono_sec")), "couv_feu_equidia": part(has("tx_feu_equidia")),
            "couv_p_avant_valeurs_distinctes": len(pav)}


def _diagnostic_cols(jo: Dict[str, Any], aud: Dict[str, Any], feats: Dict[int, Dict[str, Any]], res: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """v1.29.63 : état des données (classements, corpus, corde, p_avant, Equidia) et nombre de déclenchements de chaque signal."""
    dg = (jo or {}).get("diagnostic_donnees") or {}
    en = ((aud or {}).get("sources_collecte_et_enrichissement") or {}).get("enrichissement") or {}
    eq, tb = en.get("equidia") or {}, en.get("turf_bzh") or {}
    sig = lambda f: set((f.get("tx_signaux") or "").split("|"))
    flg = lambda f: (f.get("tx_flags") or "").split("|")
    cnt = lambda pred: sum(1 for f in feats.values() if pred(f))
    qb = ((res or {}).get("quotas_info") or {})
    gr = qb.get("gru_renforce") or {}
    rgb = qb.get("reglages_b") or {}
    return {"B_famille": rgb.get("famille"), "B_portees": "|".join(rgb.get("portees") or []), "B_alpha_marche": qb.get("alpha_marche"), "B_recouvrement_C": qb.get("recouvrement_avec_ticket_C"),
            "B_identique_C": (None if qb.get("identique_ticket_C") is None else int(bool(qb.get("identique_ticket_C")))),
            "B_gru_chevaux_modifies": gr.get("chevaux_modifies"), "B_gru_delta_max_abs": gr.get("delta_max_abs"), "B_lab_chevaux_changes": qb.get("lab_chevaux_changes"), "B_pepite_entrees": qb.get("pepite_entrees"),
            "B_rerank_modifie": (None if not qb.get("rerank_tranche") else int(any(((qb["rerank_tranche"].get(t) or {}).get("modifie")) for t in ("T3", "T4")))),
            **{f"B_lab_{k_}": (gr.get("composantes_chevaux_touches") or {}).get({"classements": "classements"}.get(k_, k_)) for k_ in ("gru", "classements", "pepite", "piege", "g30", "corde")},
            "diag_classements_drivers": dg.get("classements_drivers"), "diag_classements_entraineurs": dg.get("classements_entraineurs"),
            "diag_corpus_hippodrome": dg.get("corpus_courses_hippodrome"), "diag_corpus_similaires": dg.get("corpus_courses_similaires"),
            "diag_biais_corde_possible": dg.get("biais_corde_possible"), "diag_chevaux_avec_place_corde": dg.get("chevaux_avec_place_corde"),
            "diag_p_avant_valeurs": dg.get("p_avant_valeurs_distinctes"), "diag_p_avant_proxy_musique": dg.get("p_avant_proxy_musique"),
            "diag_chevaux_avec_driver": dg.get("chevaux_avec_driver"), "diag_chevaux_avec_changement_driver": dg.get("chevaux_avec_changement_driver"),
            "equidia_status": eq.get("status"), "equidia_reason": eq.get("reason"), "turf_bzh_status": tb.get("status"),
            "n_signal_B11": cnt(lambda f: "B11" in sig(f)), "n_signal_B12": cnt(lambda f: "B12" in sig(f)),
            "n_flag_biais_corde": cnt(lambda f: any(x.startswith("BIAIS_CORDE") for x in flg(f))),
            "n_flag_piege_numero": cnt(lambda f: any(x.startswith("GRU_PIEGE_NUMERO") for x in flg(f))),
            "n_flag_piege_as": cnt(lambda f: "GRU_PIEGE_AS_CRITIQUE" in flg(f)),
            "n_flag_pepite_actif": cnt(lambda f: "GRU_PEPITE_ACTIF" in flg(f)), "n_flag_pepite_faible": cnt(lambda f: "GRU_PEPITE_FAIBLE" in flg(f)),
            "n_flag_pepite_sous_seuil": cnt(lambda f: "GRU_PEPITE_SOUS_SEUIL" in flg(f)),
            **{f"n_signal_{g}": cnt(lambda f, g=g: g in sig(f)) for g in ("G10", "G30", "G56", "G58", "G59", "G60", "G61", "G62", "G63", "G64")},
            "n_flag_piege_mult": cnt(lambda f: "GRU_PIEGE_MULT" in flg(f)), "n_flag_pool_pepite": cnt(lambda f: "GRU_POOL_PEPITE" in flg(f)),
            "n_flag_piege_skip_mf": cnt(lambda f: "GRU_PIEGE_SKIP_MARKET_FORCE" in flg(f))}


def _champ_reduit_cols(aud: Dict[str, Any], res: Dict[str, Any]) -> Dict[str, Any]:
    """v1.29.58 : colonnes désordre / bonus / ordre par ticket (champ réduit 3 bases + 5 compléments)."""
    out: Dict[str, Any] = {}
    structs = res.get("structures_tickets") or {}
    for l, src in (("A", aud), ("B", aud.get("audit_ticket_B") or {}), ("C", aud.get("audit_ticket_C") or {})):
        iss = ((src.get("structure_bases_complements") or {}).get("issue")) or {}
        for k in ("desordre", "bonus", "ordre"):
            out[f"{k}_{l}"] = (None if k not in iss else int(bool(iss[k])))
        st = structs.get(l) or {}
        out[f"ordre_prevu_{l}"] = " ".join(str(x) for x in (st.get("ordre_prevu") or []))
        out[f"p_desordre_{l}"] = (st.get("probabilites_modele") or {}).get("desordre")
    return out


def export_analyse_zip(limit: int = 300, mode: str = "ALL", complet: bool = False) -> bytes:
    """UN SEUL fichier pour l'analyse / la calibration : courses.csv (1 ligne par course), partants.csv (1 ligne par
    partant : features, TOUTES les composantes du score `bd_*`, synthèse `sy_*`, données cheval `ch_*`, présence dans les
    tickets, résultat réel), audits/*.json (allégés ; `complet=True` : avec le rapport d'exécution détaillé) et un LISEZ-MOI."""
    import zipfile
    from app.version import VERSION_BUILD
    courses = io.StringIO()
    wc = csv.DictWriter(courses, fieldnames=_COURSES_COLS, delimiter=";", extrasaction="ignore")
    wc.writeheader()
    partants_rows: List[Dict[str, Any]] = []
    audits: Dict[str, str] = {}
    repartition: Dict[str, int] = {}
    n = 0
    for meta in db.list_races(limit):
        r = db.get_race(meta["id"])
        if not r or not r.get("result"):
            continue
        res = r["result"]; ctx = res.get("context") or {}; jo = res.get("json_output") or {}
        aud = r.get("audit") or {}
        md = jo.get("mode_execution") or (aud.get("contexte_dataset") or {}).get("mode_execution") or "INCONNU"
        if mode != "ALL" and md != mode:
            continue
        repartition[md] = repartition.get(md, 0) + 1
        bl = aud.get("baselines_contrefactuelles") or {}
        bil = aud.get("bilan_ticket") or {}
        syn = ((aud.get("analyse_presse_post_course") or {}).get("synthese")) or {}
        # composantes du score de CHAQUE partant (bd_*, sy_*, ch_*) fusionnées avec le résultat réel de l'audit
        feats: Dict[int, Dict[str, Any]] = {}
        for h in res.get("horses") or []:
            ch = h.get("cheval") or {}
            if ch.get("numero") is None:
                continue
            f = {}
            f.update(_num_cols("bd_", h.get("breakdown") or {}))
            f.update(_num_cols("sy_", h.get("synthesis") or {}))
            f.update(_num_cols("ch_", ch))
            f.update(_champs_bruts(ch))                      # v1.29.62 : driver, entraîneur, œillères, ferrure / déferrage, stats, bookmakers
            f["nb_flags"] = len((h.get("breakdown") or {}).get("flags") or [])
            _bd = h.get("breakdown") or {}
            _ids = {x.get("id") for x in (_bd.get("signaux_actifs") or []) if isinstance(x, dict) and x.get("id")}
            _ids |= {x.get("id") for x in (ch.get("signaux_precalcules") or []) if isinstance(x, dict) and x.get("id")}
            f["tx_signaux"] = "|".join(sorted(_ids))                                             # v1.29.63 : B11, B12, GRU_PEPITE, GRU_PIEGE…
            f["tx_flags"] = "|".join(str(x) for x in (_bd.get("flags") or []))[:400]
            feats[int(ch["numero"])] = f
        wc.writerow({
            "race_id": r["id"], "date_course": ctx.get("date_course"), "hippodrome": ctx.get("hippodrome"),
            "reunion_course": ctx.get("reunion_course_label"), "discipline": ctx.get("discipline"), "distance_m": ctx.get("distance_m"),
            "partants": (aud.get("contexte_dataset") or {}).get("partants") or len(res.get("horses") or []), "mode": md,
            "statut": r.get("status"), "version_moteur": jo.get("version_build") or jo.get("version_ruleset"),
            "captures_A": aud.get("nb_captures"), "captures_B": (aud.get("audit_ticket_B") or {}).get("nb_captures"),
            "captures_C": (aud.get("audit_ticket_C") or {}).get("nb_captures"),
            "C_moins_marche": (None if bl.get("ticket_C_ancre") is None or bl.get("marche_top8") is None else bl["ticket_C_ancre"] - bl["marche_top8"]),
            "marche_top8": bl.get("marche_top8"), "ordre_top8": bl.get("ordre_final_top8"), "hasard_attendu": bl.get("hasard_attendu"),
            "A_moins_marche": bl.get("ticket_moins_marche"),
            **{f"captures_shadow_{t_}": (bl.get("shadow_captures") or {}).get(t_) for t_ in "ABC"},
            **{f"shadow_b3_top5_{t_}": (((bl.get("shadow_v69") or {}).get("tickets") or {}).get(t_) or {}).get("k3", {}).get("bases_dans_top5") for t_ in "ABC"},
            **{f"shadow_desordre_k2_{t_}": (((bl.get("shadow_v69") or {}).get("tickets") or {}).get(t_) or {}).get("k2", {}).get("desordre") for t_ in "ABC"},
            **{f"shadow_desordre_k3_{t_}": (((bl.get("shadow_v69") or {}).get("tickets") or {}).get(t_) or {}).get("k3", {}).get("desordre") for t_ in "ABC"},
            "captures_shadow_garde_A": ((((bl.get("shadow_v69") or {}).get("tickets") or {}).get("A") or {}).get("captures_garde_t1")),
            "favori_cote": ((bl.get("shadow_v69") or {}).get("signal_course") or {}).get("favori_cote"),
            "filtre_course": ((bl.get("shadow_v69") or {}).get("signal_course") or {}).get("niveau"),
            "B_moins_marche": (None if bl.get("ticket_B_quotas") is None or bl.get("marche_top8") is None else bl["ticket_B_quotas"] - bl["marche_top8"]),
            "top5_reel": " ".join(str(x.get("numero")) for x in (aud.get("arrivee_officielle_top5") or [])),
            "rang_moyen_reel_A": bil.get("rang_moyen_reel"), "incidents_A": bil.get("nb_incidents_course"),
            "proches_A": bil.get("nb_proches_6e_8e"), "hors_place_A": bil.get("nb_hors_place"),
            "ia_post_course_chevaux_expliques": syn.get("chevaux_expliques"), "ia_post_course_chevaux_analyses": syn.get("chevaux_analyses"),
            "anomalies_donnees": len(jo.get("anomalies_donnees") or []), "avec_audit": bool(aud),
            # v1.29.57 : de quoi calibrer λ (a priori de grille) et la signature IIC-v2 sur le lot
            "signature": ctx.get("signature"), "iic_v2": ctx.get("iic_v2"), "iic_marche": ctx.get("iic_market"),
            "grille_B_cible": "-".join(str(x) for x in ((res.get("quotas_info") or {}).get("target_grid") or [])),
            "grille_B_appliquee": "-".join(str(x) for x in ((res.get("quotas_info") or {}).get("applied_grid") or [])),
            "ecart_grille_B": (res.get("quotas_info") or {}).get("ecart_grille"),
            "captures_attendues_B": (res.get("quotas_info") or {}).get("captures_attendues_modele"),
            "captures_attendues_B_sans_grille": (res.get("quotas_info") or {}).get("captures_attendues_sans_grille"),
            **_champ_reduit_cols(aud, res), **_couverture(feats), **_diagnostic_cols(jo, aud, feats, res),
            **{k: ctx.get(k) for k in ("type_course", "depart", "allocation_eur", "penetrometre", "terrain_qualificatif", "conditions_particulieres",
                                       "meteo_temp_c", "meteo_vent_kmh_max", "meteo_risque_pluie", "rythme_projete", "nb_meneurs_champ")}})
        n_part = len(aud.get("dataset_calibration") or [])
        for row in aud.get("dataset_calibration") or []:
            partants_rows.append({**feats.get(int(row.get("numero") or -1), {}), **row, "race_id": r["id"],
                                  "date_course": ctx.get("date_course"), "hippodrome": ctx.get("hippodrome"),
                                  "discipline": ctx.get("discipline"), "mode": md, "partants": n_part})
        if aud:
            a = dict(aud)
            if not complet:
                a.pop("rapport_execution", None)
            audits[f"audits/{r['id']}.json"] = json.dumps(a, ensure_ascii=False, default=str)
        n += 1
    cols = list(_PARTANTS_COLS)
    extra = sorted({k for row in partants_rows for k in row} - set(cols))
    partants = io.StringIO()
    wp = csv.DictWriter(partants, fieldnames=cols + extra, delimiter=";", extrasaction="ignore")
    wp.writeheader()
    for row in partants_rows:
        wp.writerow(row)
    lisez = (f"Export d'analyse Protocol Vantage -- {VERSION_BUILD}\n"
             f"Généré le {datetime.now(timezone.utc).isoformat()} -- {n} course(s) -- répartition par mode : {repartition}\n\n"
             "courses.csv  : 1 ligne par course (captures ticket A / B, 8 plus petites cotes, ordre_final top 8, écarts, top 5 réel...)\n"
             "partants.csv : 1 ligne par partant : cotes, tranche, ordre_final, composite, PCH, musique, dans_ticket_A/B, top5, rang réel complet,\n"
             "               incident + TOUTES les composantes du score (bd_*), la synthèse (sy_*) et les données du cheval (ch_*)\n"
             "               v1.29.62 : tx_* (driver, driver précédent, entraîneur, propriétaire, œillères, ferrure, DÉFERRAGE, feu Equidia), chg_driver,\n"
             "               oeilleres_presentes/_premiere_fois, deferre_present, ds_*/ts_* (stats driver / entraîneur + fenêtres w<jours>_*), tdc_*/tde_*\n"
             "               (tandems), cbk_* (cotes par bookmaker), ctl_* (timeline de cotes), rk3_moy ; courses.csv : contexte (terrain, météo, rythme)\n"
             "               + couv_* = part de partants renseignés par donnée (contrôle de la collecte)\n"
             "audits/      : audit complet de chaque course (allégé du rapport d'exécution ; ?complet=1 pour l'inclure)\n"
             "MODE : REJEU = course déjà courue (cotes finales, cumuls d'après-course) ; PRE_COURSE = analysée avant le départ.\n"
             "Outils : scripts/simuler_regles_ticket.py (règles de ticket, validation croisée) et scripts/discriminer_composantes.py\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("LISEZ-MOI.txt", lisez)
        z.writestr("courses.csv", courses.getvalue())
        z.writestr("partants.csv", partants.getvalue())
        for name, content in audits.items():
            z.writestr(name, content)
    return buf.getvalue()
