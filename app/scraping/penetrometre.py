"""
penetrometre.py — Collecte multi-sources de l'état du terrain / pénétromètre.

Sources de repli (gratuites, accessibles publiquement), ordre de priorité :
  1. API PMU (si déjà rempli en amont)
  2. Fréquence-Turf (texte prono + météo FT)
  3. Equidia (page course programme)
  4. CanalTurf (page course / pronostics)
  5. France Galop / LeTrot (pages hippodrome / réunions — texte)
  6. Turfoo / Zone-Turf (libellé terrain page programme)

Ne bloque jamais le pipeline. Retourne un rapport transparent.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("vantage.scraping.penetrometre")

_NUM = re.compile(
    r"(?:p[eé]n[eé]trom[eè]tre|indice(?:\s+p[eé]n[eé]trom[eé]trique)?|"
    r"etat\s+du\s+terrain|état\s+du\s+terrain)"
    r"[^\d]{0,40}(\d+[.,]\d+)",
    re.I,
)
_LABEL = re.compile(
    r"(?:terrain|piste)\s*(?:annonc[eé]e?\s*)?"
    r"(très\s+lourd|lourd|souple|bon\s+souple|bon|léger|tres\s+leger|très\s+léger|"
    r"très\s+souple|tres\s+souple|collant|profond)",
    re.I,
)
_LABEL_TO_APPROX = {
    "tres leger": 2.2, "très léger": 2.2, "léger": 2.5, "leger": 2.5,
    "bon": 3.0, "bon souple": 3.3, "souple": 3.5, "très souple": 3.9, "tres souple": 3.9,
    "collant": 4.2, "lourd": 4.5, "très lourd": 4.9, "tres lourd": 4.9, "profond": 4.7,
}


def _parse_html_terrain(html: str) -> Tuple[Optional[float], Optional[str], str]:
    if not html:
        return None, None, "empty"
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    m = _NUM.search(text)
    if m:
        try:
            val = float(m.group(1).replace(",", "."))
            if 1.5 <= val <= 6.5:
                return val, None, "indice_numerique"
        except ValueError:
            pass
    m2 = _LABEL.search(text)
    if m2:
        lab = m2.group(1).strip().lower()
        lab_n = re.sub(r"\s+", " ", lab)
        approx = None
        for k, v in _LABEL_TO_APPROX.items():
            if k in lab_n:
                approx = v
                break
        return approx, lab_n, "label_texte"
    return None, None, "non_trouve"


def _fetch(url: str, timeout: int = 18) -> str:
    try:
        from app.scraping.base import fetch_html
        return fetch_html(url) or ""
    except Exception as e:
        logger.warning("penetrometre fetch %s: %s", url, e)
        return ""


def _urls_for_race(race) -> List[Tuple[str, str]]:
    """(source_name, url) candidates."""
    out: List[Tuple[str, str]] = []
    d = getattr(race, "date_course", None)
    hippo = (getattr(race, "hippodrome", None) or "").strip()
    urls_meta = getattr(race, "urls_sources", None) or {}
    # CanalTurf / Turfoo / Zone-Turf déjà connus
    for key, name in (
        ("canalturf", "canalturf"),
        ("turfoo", "turfoo"),
        ("zoneturf", "zoneturf"),
        ("geny", "geny"),
        ("equidia", "equidia"),
        ("primaire", "primaire"),
    ):
        u = None
        if isinstance(urls_meta, dict):
            u = urls_meta.get(key) or urls_meta.get(name)
        if u:
            out.append((name, str(u)))

    # Equidia programme R/C
    try:
        from app.scraping.pmu_api import extraire_reunion_course, resolve_rc_from_programme
        from app.scraping.equidia import build_equidia_url
        rc = extraire_reunion_course(race) or resolve_rc_from_programme(race)
        if rc and d:
            date_iso = str(d)[:10]
            out.append(("equidia", build_equidia_url(date_iso, rc[0], rc[1])))
    except Exception:
        pass

    # Fréquence-Turf prono + météo
    if d:
        try:
            from app.scraping.frequence_turf import build_frequence_turf_urls
            ft = build_frequence_turf_urls(d) if callable(build_frequence_turf_urls) else {}
            if isinstance(ft, dict):
                for k in ("base_tocard", "presse", "meteo"):
                    if ft.get(k):
                        out.append((f"frequence_turf_{k}", ft[k]))
            # météo FT pattern
            try:
                from datetime import date as date_cls
                dd = d if hasattr(d, "day") else date_cls.fromisoformat(str(d)[:10])
                jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
                mois = ["janvier", "fevrier", "mars", "avril", "mai", "juin",
                        "juillet", "aout", "septembre", "octobre", "novembre", "decembre"]
                # accents simplified for URL
                mois_fr = ["janvier", "février", "mars", "avril", "mai", "juin",
                           "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
                jn = jours[dd.weekday()]
                mn = mois_fr[dd.month - 1]
                slug = f"{jn}-{dd.day}-{mn}-{dd.year}"
                out.append(("frequence_turf_meteo", f"https://frequence-turf.fr/meteo-quinte-{slug}/"))
                out.append(("frequence_turf_prono", f"https://frequence-turf.fr/pronostic-quinte-pmu-{slug}/"))
            except Exception:
                pass
        except Exception:
            pass

    # France Galop hippodrome pages (terrain souvent en news / live)
    hippo_l = hippo.lower()
    fg_map = {
        "auteuil": "https://www.france-galop.com/fr/hippodromeauteuil",
        "longchamp": "https://www.france-galop.com/fr/hippodromeparislongchamp",
        "chantilly": "https://www.france-galop.com/fr/hippodromechantilly",
        "deauville": "https://www.france-galop.com/fr/hippodromedeauville",
        "saint-cloud": "https://www.france-galop.com/fr/hippodromesaintcloud",
        "saint cloud": "https://www.france-galop.com/fr/hippodromesaintcloud",
    }
    for key, url in fg_map.items():
        if key in hippo_l:
            out.append(("france_galop_hippo", url))
            break

    # Dédup
    seen = set()
    uniq = []
    for name, u in out:
        if u and u not in seen:
            seen.add(u)
            uniq.append((name, u))
    return uniq


def enrich_penetrometre(race, chevaux=None) -> Dict[str, Any]:
    """Remplit race.penetrometre et/ou race.etat_terrain si manquants."""
    report: Dict[str, Any] = {
        "status": "SKIP",
        "sources_tentees": [],
        "source_retenue": None,
        "penetrometre": getattr(race, "penetrometre", None),
        "etat_terrain": getattr(race, "etat_terrain", None),
    }
    already = getattr(race, "penetrometre", None)
    if already is not None:
        report["status"] = "OK_DEJA_PRESENT"
        report["source_retenue"] = "preexistant"
        return report

    tentatives = []
    for name, url in _urls_for_race(race):
        html = _fetch(url)
        val, label, how = _parse_html_terrain(html)
        tentatives.append({"source": name, "url": url, "how": how, "val": val, "label": label})
        if val is not None or label:
            try:
                if val is not None:
                    race.penetrometre = float(val)
                if label and not getattr(race, "etat_terrain", None):
                    try:
                        race.etat_terrain = label
                    except Exception:
                        pass
                # stocker aussi un libellé si seul approx
                if val is not None and not getattr(race, "etat_terrain", None):
                    # inverse approx -> label grossier
                    if val < 2.8:
                        race.etat_terrain = race.etat_terrain or "leger"
                    elif val < 3.4:
                        race.etat_terrain = race.etat_terrain or "bon"
                    elif val < 4.0:
                        race.etat_terrain = race.etat_terrain or "souple"
                    else:
                        race.etat_terrain = race.etat_terrain or "lourd"
                report["status"] = "OK"
                report["source_retenue"] = name
                report["penetrometre"] = getattr(race, "penetrometre", None)
                report["etat_terrain"] = getattr(race, "etat_terrain", None)
                report["sources_tentees"] = tentatives
                return report
            except Exception as e:
                tentatives[-1]["error"] = str(e)

    report["status"] = "EMPTY"
    report["sources_tentees"] = tentatives
    return report
