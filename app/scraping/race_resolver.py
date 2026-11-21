"""Résolution course par identifiants date + R + C (porté v1.26, adapté prod).

Priorité : identité R+C (pas une URL utilisateur). Construit des URLs
candidates via discovery_multi + patterns publics, journal de résolution.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("vantage.scraping.race_resolver")


class CourseResolutionError(ValueError):
    """Course non identifiable sans ambiguïté."""


def _optionnel_texte(payload: Dict[str, Any], key: str) -> Optional[str]:
    value = payload.get(key)
    if value is None:
        return None
    text = str(value).strip().upper()
    return None if text in {"", "NONE", "NULL", "NC", "N/A", "NA"} else text


def normaliser_identifiants_course(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Valide date / réunion / n° course (format AAAA-MM-JJ)."""
    if not isinstance(payload, dict):
        raise CourseResolutionError("Le corps de requête doit être un objet JSON")
    date_value = str(payload.get("date", "")).strip()
    reunion_value = payload.get("reunion")
    course_value = payload.get("numero_course", payload.get("course"))
    if not date_value:
        raise CourseResolutionError("Le champ date est obligatoire")
    try:
        date_obj = datetime.strptime(date_value, "%Y-%m-%d")
    except ValueError as exc:
        raise CourseResolutionError("La date doit respecter le format AAAA-MM-JJ") from exc
    try:
        reunion = int(reunion_value)
        numero_course = int(course_value)
    except (TypeError, ValueError) as exc:
        raise CourseResolutionError("reunion et numero_course doivent être des entiers") from exc
    if reunion < 1 or numero_course < 1:
        raise CourseResolutionError("reunion et numero_course doivent être ≥ 1")
    date_pmu = date_obj.strftime("%d%m%Y")
    return {
        "date": date_value,
        "date_pmu": date_pmu,
        "reunion": reunion,
        "numero_course": numero_course,
        "hippodrome_attendu": _optionnel_texte(payload, "hippodrome_attendu"),
        "discipline_attendue": _optionnel_texte(payload, "discipline_attendue"),
        "mode_execution": payload.get("mode_execution", "AUTO_CONTINUE"),
    }


def construire_urls_candidates(ids: Dict[str, Any]) -> List[str]:
    """URLs publiques candidates (sans demander d'URL à l'utilisateur)."""
    date_pmu = ids["date_pmu"]
    reunion = ids["reunion"]
    course = ids["numero_course"]
    return [
        f"https://www.pmu.fr/turf/programme/{date_pmu}/R{reunion}/C{course}",
        f"https://www.turf.bzh/pronostics-pmu-{date_pmu}-R{reunion}C{course}.html",
    ]


def resolve_course_urls(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Résout les URLs via discovery_multi + candidats statiques.

    Retourne un journal exploitable (urls, par_source, taux_collecte).
    """
    ids = normaliser_identifiants_course(payload)
    report: Dict[str, Any] = {
        "identifiants": ids,
        "urls": [],
        "par_source": {},
        "taux_collecte": 0.0,
        "status": "PENDING",
    }
    candidates = construire_urls_candidates(ids)
    report["par_source"]["static_candidates"] = {"urls": candidates}

    try:
        from app.scraping.discovery_multi import discover_all_sources
        disco = discover_all_sources(
            ids["date"],
            hippodrome=ids.get("hippodrome_attendu"),
            course_num=ids["numero_course"],
            reunion_num=ids["reunion"],
        )
        report["par_source"]["discovery_multi"] = {
            "urls": list(disco.urls),
            "par_source": disco.par_source,
            "taux_collecte": disco.taux_collecte,
        }
        urls = list(dict.fromkeys(list(disco.urls)))  # v1.29.40 : pmu.fr/turf.bzh (JS, rejetés par le routeur) restent informatifs
        report["urls"] = urls
        report["taux_collecte"] = float(disco.taux_collecte)
        report["status"] = "OK" if urls else "EMPTY"
    except TypeError:
        # signature discovery peut différer
        try:
            from app.scraping.discovery_multi import discover_all_sources
            disco = discover_all_sources(
                ids["date"],
                ids.get("hippodrome_attendu"),
                ids["numero_course"],
            )
            urls = list(dict.fromkeys(list(disco.urls)))
            report["urls"] = urls
            report["taux_collecte"] = float(getattr(disco, "taux_collecte", 0.0))
            report["par_source"]["discovery_multi"] = getattr(disco, "par_source", {})
            report["status"] = "OK" if urls else "EMPTY"
        except Exception as e:
            logger.warning("discovery_multi échec : %s", e)
            report["urls"] = candidates
            report["status"] = "FALLBACK_STATIC"
            report["par_source"]["discovery_error"] = str(e)
    except Exception as e:
        logger.warning("resolve_course_urls : %s", e)
        report["urls"] = candidates
        report["status"] = "FALLBACK_STATIC"
        report["par_source"]["error"] = str(e)

    report["evidence"] = {
        "identity_priority": "R+C",
        "date": ids["date"],
        "reunion": ids["reunion"],
        "course": ids["numero_course"],
        "n_urls": len(report["urls"]),
    }
    return report
