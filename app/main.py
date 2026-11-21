"""main.py -- Application FastAPI PROTOCOL VANTAGE."""
from __future__ import annotations
import uuid
import json
import logging
import ipaddress
import socket
from urllib.parse import urlparse
from datetime import date as date_cls, datetime
from typing import List, Dict, Any

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from app import db
from app.orchestrator import run_pipeline
from app.scraping.discovery import find_race_url
from app.scraping.discovery_multi import discover_all_sources, SEUIL_TAUX_COLLECTE_MIN
from app.scraping.hippodrome_normalize import resolve_hippodrome
from app.engine.post_race_audit import build_post_race_audit, confirm_arrival
from app.engine.execution_report_render import render_execution_report_md
from app.scraping.base import HAS_CFFI  # installe via requirements.txt
from app.models import RaceResult, ExecutionReport
from app.version import VERSION_BUILD

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("vantage.main")

app = FastAPI(title="PROTOCOL VANTAGE -- Moteur unique", version=VERSION_BUILD)

_MAX_RACE_URLS = 8
_ALLOWED_RACE_DOMAINS = {
    "turfoo.fr", "www.turfoo.fr", "canalturf.com", "www.canalturf.com",
    "zone-turf.fr", "www.zone-turf.fr", "geny.com", "www.geny.com",
}


def _validate_race_url(raw_url: str) -> str:
    """Valide une URL de source avant tout fetch serveur (anti-SSRF)."""
    value = (raw_url or "").strip()
    if not value or any(ch in value for ch in "\r\n\x00"):
        raise ValueError("URL vide ou contenant des caractères de contrôle")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("seules les URLs HTTPS sans identifiants sont acceptées")
    host = parsed.hostname.lower().rstrip(".")
    if host not in _ALLOWED_RACE_DOMAINS:
        raise ValueError(f"domaine de source non autorisé: {host}")
    try:
        addresses = {ai[4][0] for ai in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise ValueError(f"hôte de source non résolu: {host}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise ValueError(f"adresse réseau interdite pour la source: {address}")
    return value


@app.on_event("startup")
def _startup():
    db.init_db()
    from app.integrations.hf_export import startup_restore, hf_export_enabled
    startup_restore()
    from app import batch as _batch
    if not hf_export_enabled():   # avec HF, la reprise a lieu APRÈS la restauration de l'historique et des lots
        _batch.resume_on_startup()   # v1.29.53 : reprend un lot interrompu par un redémarrage              # v1.29.46 : recharge l'historique depuis Hugging Face (Render perd son disque)



@app.get("/api/hippodromes")
def api_hippodromes():
    """Liste déroulante : hippodromes FR Quinté+, tri volume décroissant."""
    from app.scraping.hippodrome_normalize import list_hippodromes_quinte, list_hippodromes_quinte_with_weight
    return {
        "hippodromes": list_hippodromes_quinte(),
        "detail": list_hippodromes_quinte_with_weight(),
        "ordre": "volume_quinte_decroissant",
        "source": "turf.bzh_archives + calendriers_PMU_2024_2026",
    }

@app.get("/health")
def health():
    """Health + flags fusion + scraping runtime."""
    from app.version import VERSION_BUILD, VERSION_RULESET, VERSION_PACKAGE, FUSION_FLAGS
    from app.scraping.frequence_turf import frequence_turf_enabled
    from app.ml.ranker_shadow import shadow_enabled, _has_lightgbm
    from app.scraping.discovery_multi import SEUIL_TAUX_COLLECTE_MIN
    try:
        from curl_cffi import requests as _cffi  # noqa: F401
        has_cffi = True
    except ImportError:
        has_cffi = False
    return {
        "status": "ok",
        "version_build": VERSION_BUILD,
        "version_ruleset": VERSION_RULESET,
        "version_package": VERSION_PACKAGE,
        "fusion_flags": FUSION_FLAGS,
        "runtime": {
            "frequence_turf": frequence_turf_enabled(),
            "ml_shadow": shadow_enabled(),
            "lightgbm": _has_lightgbm(),
            "curl_cffi": has_cffi,
            "seuil_collecte": SEUIL_TAUX_COLLECTE_MIN,
            "turfoo_ok_probable": has_cffi,
        },
    }


class NewRaceRequest(BaseModel):
    urls: List[str]


@app.post("/api/races")
def create_race(req: NewRaceRequest, background_tasks: BackgroundTasks):
    urls = [u.strip() for u in req.urls if u and u.strip()]
    if not urls or len(urls) > _MAX_RACE_URLS:
        raise HTTPException(400, f"Fournis entre 1 et {_MAX_RACE_URLS} URLs de course.")
    try:
        urls = [_validate_race_url(u) for u in urls]
    except ValueError as exc:
        raise HTTPException(400, f"URL de course refusée : {exc}") from exc
    race_id = uuid.uuid4().hex[:12]
    db.create_race(race_id, urls)
    background_tasks.add_task(run_pipeline, race_id, urls)
    return {"race_id": race_id, "status": "EN_ATTENTE"}


@app.get("/api/races")
def list_races(limit: int = Query(50, ge=1, le=100)):
    return db.list_races(limit=limit)


class DiscoverRequest(BaseModel):
    date: str
    hippodrome: str | None = None
    course_num: int | None = None
    course_name: str | None = None
    reunion_num: int | None = None


@app.post("/api/discover")
def discover_race(req: DiscoverRequest):
    if not req.hippodrome and not (req.reunion_num is not None and req.course_num is not None):
        raise HTTPException(400, "Fournis soit l'hippodrome, soit (réunion + course).")
    try:
        candidates = find_race_url(req.date, req.hippodrome, req.course_num,
                                    req.course_name, req.reunion_num)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return [{"url": c.url, "label": c.label, "score": c.score,
             "reunion": c.reunion, "course": c.course} for c in candidates[:5]]



class ResolveRequest(BaseModel):
    date: str  # AAAA-MM-JJ
    reunion: int
    numero_course: int
    hippodrome_attendu: str | None = None
    discipline_attendue: str | None = None


@app.post("/api/resolve")
def resolve_course(req: ResolveRequest):
    """Résolution R+C prioritaire (v1.26) — retourne URLs candidates + journal."""
    from app.scraping.race_resolver import resolve_course_urls, CourseResolutionError
    try:
        return resolve_course_urls(req.model_dump())
    except CourseResolutionError as e:
        raise HTTPException(status_code=400, detail=str(e))




class PriorRaceLookupRequest(BaseModel):
    date: str
    hippodrome: str | None = None
    distance_m: int | None = None
    discipline: str | None = None
    reunion_num: int | None = None
    course_num: int | None = None


@app.post("/api/races/lookup-prior")
def lookup_prior(req: PriorRaceLookupRequest):
    """Vérifie si une course (date ± hippodrome ± distance/discipline/R+C) a déjà été traitée."""
    from app.integrations.prior_race import lookup_prior_race
    date_value = req.date.strip()
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime, timedelta
        _paris_today = datetime.now(ZoneInfo("Europe/Paris")).date()
    except Exception:
        from datetime import timedelta
        _paris_today = date_cls.today()
    low = date_value.lower()
    if low in ("aujourd'hui", "aujourdhui", "today", ""):
        date_value = _paris_today.isoformat()
    elif low in ("demain", "tomorrow"):
        date_value = (_paris_today + timedelta(days=1)).isoformat()
    elif low in ("hier", "yesterday"):
        date_value = (_paris_today - timedelta(days=1)).isoformat()
    hippo = req.hippodrome
    if hippo:
        resolved, score = resolve_hippodrome(hippo)
        if resolved and score >= 0.72:
            hippo = resolved
    priors = lookup_prior_race(
        date_value,
        hippodrome=hippo,
        distance_m=req.distance_m,
        discipline=req.discipline,
        reunion_num=req.reunion_num,
        course_num=req.course_num,
    )
    return {
        "deja_traitee": bool(priors),
        "correspondances": priors[:10],
        "version_moteur_actuelle": VERSION_BUILD,
    }


class AutoRaceRequest(BaseModel):
    date: str = "aujourd'hui"     # AAAA-MM-JJ, ou "aujourd'hui"/"demain"
    # Changé le 07/09/2026 (demande de Golden) : hippodrome devient
    # FACULTATIF -- réunion + course suffisent à identifier une course
    # de façon exacte et évitent le blocage sur une faute de frappe
    # d'hippodrome. hippodrome et course_name restent utilisables comme
    # informations complémentaires (bonus de confiance), jamais comme filtres
    # obligatoires. Au moins l'un des deux modes doit être fourni,
    # vérifié dans create_race_auto ci-dessous.
    hippodrome: str | None = None
    course_num: int | None = None
    course_name: str | None = None
    reunion_num: int | None = None
    # Ajouté le 08/09/2026 pour le mode walk-forward historique : si True,
    # lance automatiquement l'audit post-course dès que le ticket est prêt
    # (utile pour une course PASSÉE dont le résultat est déjà connu -- pas
    # besoin de revenir cliquer "Audit post-course" ensuite). Sans effet
    # utile sur une course du jour pas encore courue (l'audit échouera
    # juste silencieusement faute de résultat, cf. run_pipeline).
    auto_audit: bool = False
    # Si True : l'utilisateur a confirmé de continuer malgré un taux < 66%
    # (au moins 2 sources trouvées). Sinon, en dessous du seuil avec ≥2
    # sources, l'API renvoie decision_requise sans lancer le pipeline.
    force_continue: bool = False
    # Si True : l'utilisateur confirme le retraitement d'une course déjà présente
    # dans l'historique (local ou Hugging Face). Sinon, alerte + decision_requise.
    force_reprocess: bool = False


@app.post("/api/races/auto")
def create_race_auto(req: AutoRaceRequest, background_tasks: BackgroundTasks):
    """Un seul appel : donne réunion+course (recommandé, identification
    exacte) ou hippodrome (+ date/n° de course si tu les as), le système
    retrouve l'URL sur CHAQUE source configurée (Turfoo, CanalTurf,
    Zone-Turf -- Frequence-Turf est automatique, pas besoin de le
    chercher), centralise, et lance l'exécution -- SAUF si le taux de
    collecte < 66% : si ≥2 sources ont trouvé la course, l'API renvoie
    decision_requise (l'UI propose Continuer ou Relancer la recherche).
    force_continue=true lance quand même le pipeline. Si <2 sources,
    blocage dur (422)."""
    if not req.hippodrome and not (req.reunion_num is not None and req.course_num is not None):
        raise HTTPException(400, "Fournis soit l'hippodrome, soit (réunion + course).")

    date_value = req.date.strip().lower()
    # Calendrier hippique = Europe/Paris (Render UTC : 22h UTC = déjà J+1 Paris).
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime, timedelta
        _paris_today = datetime.now(ZoneInfo("Europe/Paris")).date()
    except Exception:
        from datetime import timedelta
        _paris_today = date_cls.today()
    if date_value in ("aujourd'hui", "aujourdhui", "today", ""):
        date_value = _paris_today.isoformat()
    elif date_value in ("demain", "tomorrow"):
        date_value = (_paris_today + timedelta(days=1)).isoformat()
    elif date_value in ("hier", "yesterday"):
        date_value = (_paris_today - timedelta(days=1)).isoformat()
    else:
        date_value = req.date  # AAAA-MM-JJ

    hippo = req.hippodrome
    if hippo:
        resolved, score = resolve_hippodrome(hippo)
        if resolved and score >= 0.72:
            hippo = resolved

    # --- Anti-doublon : course déjà traitée (historique local + HF) ---
    if not req.force_reprocess:
        try:
            from app.integrations.prior_race import lookup_prior_race
            priors = lookup_prior_race(
                date_value,
                hippodrome=hippo,
                reunion_num=req.reunion_num,
                course_num=req.course_num,
            )
        except Exception as e:
            logger.warning("lookup_prior_race: %s", e)
            priors = []
        if priors:
            best = priors[0]
            disc_l = best.get("discipline") or "?"
            dist_l = best.get("distance_m")
            dist_s = f"{dist_l} m" if dist_l else "distance inconnue"
            hip_l = best.get("hippodrome") or hippo or "?"
            ver = best.get("version_moteur") or "version inconnue"
            cap_label = best.get("capture_label") or (
                (best.get("capture") or {}).get("label_court") if isinstance(best.get("capture"), dict) else None
            ) or "capture non disponible"
            msg = (
                f"Cette course a déjà été traitée : {best.get('date_course') or date_value} · "
                f"{hip_l} · {disc_l} · {dist_s}. "
                f"Moteur utilisé : {ver}. "
                f"Taux de capture (traitement précédent) : {cap_label}. "
                f"{'Audit post-course présent.' if best.get('a_un_audit') else 'Pas d’audit post-course enregistré.'} "
                f"Voulez-vous la retraiter avec la dernière version du protocole, ou passer à une nouvelle course ?"
            )
            return {
                "decision_requise": True,
                "raison": "course_deja_traitee",
                "message": msg,
                "course_existante": best,
                "correspondances": priors[:5],
                "version_moteur_actuelle": VERSION_BUILD,
            }

    try:
        report = discover_all_sources(date_value, hippo, req.course_num,
                                       req.course_name, req.reunion_num)
    except ValueError as e:
        raise HTTPException(404, str(e))

    # Règles v1.29.40 :
    # - < 2 sources trouvées → blocage dur, QUEL QUE SOIT le taux (avant, une
    #   seule source pouvait passer à 100 % quand les autres étaient exclues)
    # - ≥ 2 sources mais taux < 66% → demander à l'utilisateur (sauf force_continue)
    # - taux ≥ 66% (2 sources sur 3) ou force_continue → lancer le pipeline
    if report.sources_reussies < 2 or not report.urls:
        raise HTTPException(422, {
            "message": f"Moins de 2 sources ont identifié la course ({report.sources_reussies}/{report.sources_applicables}) — exécution impossible.",
            "taux_collecte": report.taux_collecte, "sources_reussies": report.sources_reussies,
            "sources_applicables": report.sources_applicables, "detail_par_source": report.par_source,
            "urls_decouvertes": report.urls, "seuil": SEUIL_TAUX_COLLECTE_MIN,
        })
    if report.taux_collecte < SEUIL_TAUX_COLLECTE_MIN:
        payload = {
            "message": (
                f"Taux de collecte insuffisant : {report.taux_collecte:.0%} "
                f"({report.sources_reussies}/{report.sources_applicables} sources), "
                f"minimum requis {SEUIL_TAUX_COLLECTE_MIN:.0%}."
            ),
            "taux_collecte": report.taux_collecte,
            "sources_reussies": report.sources_reussies,
            "sources_applicables": report.sources_applicables,
            "detail_par_source": report.par_source,
            "urls_decouvertes": report.urls,
            "seuil": SEUIL_TAUX_COLLECTE_MIN,
        }
        if report.sources_reussies < 2 or not report.urls:
            payload["message"] += " Moins de 2 sources trouvées — exécution impossible."
            raise HTTPException(422, payload)
        if not req.force_continue:
            payload["decision_requise"] = True
            payload["message"] += (
                " Au moins 2 sources ont identifié la course. "
                "Continuer l'exécution avec ces sources, ou relancer la recherche "
                "sur les sources manquantes ?"
            )
            return payload
        # force_continue : on poursuit avec les URLs disponibles

    race_id = uuid.uuid4().hex[:12]
    db.create_race(race_id, report.urls)
    background_tasks.add_task(
        run_pipeline, race_id, report.urls, req.auto_audit,
        {
            "urls": report.urls,
            "taux_collecte": report.taux_collecte,
            "par_source": report.par_source,
            "hippodrome_attendu": hippo,
            "date": date_value,
            "reunion_num": req.reunion_num,
            "course_num": req.course_num,
        },
    )
    return {
        "race_id": race_id,
        "status": "EN_ATTENTE",
        "urls_decouvertes": report.urls,
        "taux_collecte": report.taux_collecte,
        "sources": report.par_source,
        "force_continue": bool(req.force_continue and report.taux_collecte < SEUIL_TAUX_COLLECTE_MIN),
    }


@app.get("/api/races/{race_id}")
def get_race(race_id: str):
    r = db.get_race(race_id)
    if not r:
        raise HTTPException(404, "Course introuvable.")
    return r


@app.post("/api/races/{race_id}/retry")
def retry_race(race_id: str, background_tasks: BackgroundTasks):
    r = db.get_race(race_id)
    if not r:
        raise HTTPException(404, "Course introuvable.")
    try:
        urls = [_validate_race_url(u) for u in (r.get("urls") or [])]
    except ValueError as exc:
        raise HTTPException(400, f"URLs persistées refusées : {exc}") from exc
    db.update_status(race_id, "EN_ATTENTE", error=None)
    background_tasks.add_task(run_pipeline, race_id, urls)
    return {"race_id": race_id, "status": "EN_ATTENTE"}




@app.post("/api/ai/test")
def ai_test():
    """Teste chaque fournisseur IA (Groq, Gemini, Anthropic) : clé valide ? modèle disponible ? message d'erreur exact."""
    from app.llm.supervisor import test_providers
    return test_providers()


@app.get("/api/ai/status")
def ai_status():
    """Diagnostic IA (clés présentes, provider, modèles configurés) — sans appeler le LLM."""
    try:
        from app.llm.supervisor import ai_runtime_status
        return ai_runtime_status()
    except Exception as e:
        return {"status": "ERROR", "error": str(e)[:200]}


@app.post("/api/races/{race_id}/audit")
def audit_race(race_id: str):
    r = db.get_race(race_id)
    if not r:
        raise HTTPException(404, "Course introuvable.")
    if not r.get("result"):
        raise HTTPException(400, "L'analyse de cette course n'est pas encore terminée.")

    result = RaceResult.model_validate(r["result"])

    try:
        from app.engine.post_race_audit import run_full_audit
        return run_full_audit(race_id, result, r.get("urls") or [])
    except ValueError as e:
        raise HTTPException(
            422,
            f"Arrivée officielle indisponible ou non confirmée : {e}. "
            "Vérifier que la course est terminée, que date_course et R/C sont renseignés, "
            "et qu'au moins une URL Turfoo ou l'API PMU répond.",
        )


@app.get("/api/races/{race_id}/audit/download")
def download_audit(race_id: str):
    """Rapport d'audit post-course en JSON compressé gzip (demandé le
    06/09/2026) -- réduit la taille du fichier téléchargé, notamment
    utile si l'agrégation multi-courses (cf. /api/audits/patterns) est
    incluse plus tard dans ce même format.

    Intègre aussi le rapport d'EXÉCUTION bout en bout (demandé le
    12/09/2026) sous la clé "rapport_execution" -- répond à "où ça a
    cassé techniquement" (quelle étape/source a échoué) en plus de "le
    ticket a-t-il capturé le Top5" (l'audit lui-même). Absent si aucune
    exécution tracée pour cette course (ne bloque pas le téléchargement
    de l'audit seul)."""
    r = db.get_race(race_id)
    if not r:
        raise HTTPException(404, "Course introuvable.")
    if not r.get("audit"):
        raise HTTPException(404, "Aucun audit pour cette course -- lancer l'audit d'abord.")

    combine: Dict[str, Any] = dict(r["audit"])
    if r.get("execution_report"):
        combine["rapport_execution"] = r["execution_report"]
    else:
        combine["rapport_execution"] = {
            "disponible": False,
            "raison": "Aucun rapport d'exécution tracé pour cette course (ExecutionReport absent en base).",
        }

    import gzip
    from app.integrations.hf_export import archive_basename_for_race
    base = archive_basename_for_race(race_id, r)
    payload = json.dumps(combine, ensure_ascii=False, indent=2).encode("utf-8")
    compresse = gzip.compress(payload)
    return Response(
        content=compresse, media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{base}_audit.json.gz"',
                 "Content-Encoding": "identity"},  # identity : le corps EST le .gz, pas à décompresser par le navigateur
    )


@app.get("/api/ml/status")
def ml_status():
    """Statut de l'apprentissage continu (v1.29.15) : nb d'exemples
    accumulés, modèle entraîné ou non, dernière date d'entraînement --
    et statut de l'export Hugging Face (activé/configuré ou non). Rien
    ici n'influence jamais le ticket certifié."""
    from app.ml.continuous_learning import get_learning_status
    from app.integrations.hf_export import status as hf_status
    return {
        "apprentissage_continu": get_learning_status(),
        "export_hugging_face": hf_status(),
    }


@app.get("/api/audits/patterns")
def audit_patterns(limit_courses: int = Query(100, ge=1, le=100)):
    """Agrégation des audits sur plusieurs courses (demandé le
    06/09/2026) : "comprendre en quoi le protocole a fauté... si les
    mêmes erreurs se reproduisent sur plusieurs courses". Parcourt les
    `limit_courses` courses les plus récentes qui ont un audit
    enregistré et compte la récurrence des causes de manqué/sur-évalué."""
    from app.engine.post_race_audit import aggregate_audit_patterns
    audits = db.list_audits(limit=limit_courses)
    if not audits:
        raise HTTPException(404, "Aucun audit enregistré pour l'instant.")
    return aggregate_audit_patterns(audits)


class BatchRequest(BaseModel):
    courses: str                      # une course par ligne : « 2026-10-11 R1C3 Auteuil »
    auto_audit: bool = True
    pause_s: float = 10.0


@app.post("/api/batch")
def batch_create(req: BatchRequest):
    """Lance un lot de courses (analyse + audit automatique, une par une, file persistante)."""
    from app import batch
    try:
        specs = batch.parse_lines(req.courses)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if len(specs) > 120:
        raise HTTPException(400, "Maximum 120 courses par lot.")
    bid = batch.enqueue(specs, req.auto_audit, max(0.0, req.pause_s))
    return {"batch_id": bid, "courses": len(specs)}


@app.get("/api/batch")
def batch_list():
    from app import batch
    return batch.list_batches()


@app.get("/api/batch/{batch_id}")
def batch_status(batch_id: str):
    from app import batch
    st = batch.status(batch_id)
    if not st.get("existe"):
        raise HTTPException(404, "Lot introuvable.")
    return st


@app.post("/api/batch/{batch_id}/cancel")
def batch_cancel(batch_id: str):
    from app import batch
    return {"annulees": batch.cancel(batch_id)}


@app.post("/api/batch/{batch_id}/retry-failed")
def batch_retry(batch_id: str):
    from app import batch
    return {"relancees": batch.retry_failed(batch_id)}


@app.get("/api/export/analyse.zip")
def export_analyse(mode: str = Query("ALL", pattern="^(ALL|REJEU|PRE_COURSE)$"), limit: int = Query(300, ge=1, le=1000),
                   complet: bool = False):
    """UN fichier zip pour analyse/calibration : courses.csv + partants.csv + audits JSON de toutes les courses de l'historique."""
    from fastapi.responses import Response
    from app import batch
    data = batch.export_analyse_zip(limit=limit, mode=mode, complet=complet)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="vantage_analyse_{datetime.now().strftime("%Y%m%d_%H%M")}.zip"'})


@app.get("/api/batch/{batch_id}/export.csv")
def batch_export(batch_id: str):
    from fastapi.responses import Response
    from app import batch
    if not batch.status(batch_id).get("existe"):
        raise HTTPException(404, "Lot introuvable.")
    return Response(batch.export_csv(batch_id), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=lot_{batch_id}.csv"})


@app.get("/api/history/hf/status")
def hf_status():
    from app.integrations.hf_export import status
    return status()


@app.post("/api/history/hf/test")
def hf_test():
    """Vérifie le jeton et le dépôt Hugging Face (crée le dataset privé si besoin, écrit et relit un fichier)."""
    from app.integrations.hf_export import test_connection
    return test_connection()


@app.post("/api/history/hf/restore")
def hf_restore(limit: int = Query(300, ge=1, le=5000), overwrite: bool = False):
    from app.integrations.hf_export import restore
    return restore(limit=limit, overwrite=overwrite)


@app.post("/api/history/hf/sync-all")
def hf_sync_all(only_missing: bool = True):
    """Rattrapage : envoie vers Hugging Face toutes les courses locales absentes du dataset."""
    from app.integrations.hf_export import sync_all
    return sync_all(only_missing=only_missing)


@app.get("/api/audits/analyse-ia")
def audits_analyse_ia(limit_courses: int = Query(50, ge=10, le=100)):
    """Hypothèses testables sur les motifs de manqués (>= 10 audits). Statistiques déterministes + IA
    (aucune valeur de paramètre proposée ; chaque hypothèse cite un chiffre des statistiques)."""
    from app.llm.tasks import analyze_misses
    audits = db.list_audits(limit=limit_courses)
    if not audits:
        raise HTTPException(404, "Aucun audit enregistré pour l'instant.")
    return analyze_misses(audits)


@app.get("/api/races/{race_id}/execution-report")
def get_execution_report(race_id: str):
    """Rapport d'EXÉCUTION -- distinct de /audit. Répond à "la stratégie
    a-t-elle été exécutée correctement de bout en bout ?" et "où ça a
    cassé ?", pas "a-t-elle bien prédit ?". Consultable même pendant que
    le pipeline tourne encore (sauvegardé après chaque étape)."""
    r = db.get_race(race_id)
    if not r:
        raise HTTPException(404, "Course introuvable.")
    if not r.get("execution_report"):
        raise HTTPException(404, "Aucun rapport d'exécution pour cette course (pipeline pas encore démarré ?).")
    return r["execution_report"]


@app.get("/api/races/{race_id}/execution-report/download")
def download_execution_report(race_id: str):
    """Même contenu que ci-dessus, mis en forme en markdown et renvoyé
    comme fichier téléchargeable (Content-Disposition: attachment)."""
    r = db.get_race(race_id)
    if not r:
        raise HTTPException(404, "Course introuvable.")
    if not r.get("execution_report"):
        raise HTTPException(404, "Aucun rapport d'exécution pour cette course.")

    from app.integrations.hf_export import archive_basename_for_race
    base = archive_basename_for_race(race_id, r)
    report = ExecutionReport.model_validate(r["execution_report"])
    md = render_execution_report_md(report)
    return Response(
        content=md, media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{base}_rapport.md"'},
    )


@app.get("/api/races/{race_id}/bundle/download")
def download_bundle(race_id: str):
    """Téléchargement UNIQUE (demandé 20/09/2026) : un seul fichier ZIP
    contenant à la fois le rapport d'exécution (Markdown humain, étape
    par étape) et l'audit post-course (JSON complet, avec
    rapport_execution embarqué si disponible).

    Remplace la dualité des boutons par un seul bouton en bas de page.
    Aucune perte de détail : le MD reste le document de traçabilité
    technique ; le JSON reste le document d'évaluation walk-forward."""
    import io
    import zipfile
    import gzip
    from app.integrations.hf_export import archive_basename_for_race

    r = db.get_race(race_id)
    if not r:
        raise HTTPException(404, "Course introuvable.")

    base = archive_basename_for_race(race_id, r)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1) Rapport d'exécution Markdown (humain)
        if r.get("execution_report"):
            try:
                report = ExecutionReport.model_validate(r["execution_report"])
                md = render_execution_report_md(report)
                zf.writestr(f"{base}_rapport.md", md.encode("utf-8"))
            except Exception as e:
                zf.writestr(
                    f"{base}_rapport_ERREUR.txt",
                    f"Impossible de rendre le rapport d'exécution : {e}".encode("utf-8"),
                )
        else:
            zf.writestr(
                f"{base}_rapport_ABSENT.txt",
                b"Aucun rapport d'execution trace pour cette course.",
            )

        # 2) Audit post-course JSON (complet, avec rapport_execution embarque)
        if r.get("audit"):
            combine: Dict[str, Any] = dict(r["audit"])
            if r.get("execution_report"):
                combine["rapport_execution"] = r["execution_report"]
            else:
                combine["rapport_execution"] = {
                    "disponible": False,
                    "raison": "Aucun rapport d'execution trace pour cette course.",
                }
            payload = json.dumps(combine, ensure_ascii=False, indent=2).encode("utf-8")
            zf.writestr(f"{base}_audit.json", payload)
            zf.writestr(f"{base}_audit.json.gz", gzip.compress(payload))
        else:
            zf.writestr(
                f"{base}_audit_ABSENT.txt",
                b"Aucun audit pour cette course -- lancer l'audit d'abord.",
            )

        # 3) README explicatif
        readme = (
            f"Bundle PROTOCOL VANTAGE -- {base}\n"
            f"==========================================\n"
            f"race_id : {race_id}\n\n"
            f"Contenu de ce ZIP :\n"
            f"  1. {base}_rapport.md\n"
            f"     Trace etape par etape du pipeline (collecte, enrichissement,\n"
            f"     scoring, GMO-V, contraintes, ticket). Repond a :\n"
            f"     « la strategie a-t-elle ete executee correctement ? »\n\n"
            f"  2. {base}_audit.json (+ .json.gz)\n"
            f"     Audit post-course walk-forward : arrivee officielle, taux de\n"
            f"     capture Top5, chevaux captures/manques, signaux sous/surevalues.\n"
            f"     Repond a : « la strategie a-t-elle bien predit ? »\n"
            f"     Contient aussi la cle « rapport_execution » (structuree).\n\n"
            f"Aucun detail n'est perdu par rapport aux deux telechargements separes.\n"
        )
        zf.writestr("README.txt", readme.encode("utf-8"))

    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{base}.zip"',
        },
    )


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")
