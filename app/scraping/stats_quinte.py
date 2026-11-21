"""
stats_quinte.py -- Source secondaire ICP (repli Fréquence-Turf).

Validé le 20/09/2026 sur https://stats-quinte.com/presse-quinte/
(Quinté Vincennes R1C4) : classements presse structurés parseables
(Aisne Nouvelle, Bilto, Europe 1, La Voix du Nord, etc.).

Principe anti-surévaluation des favoris (exigence 20/09/2026) :
  Positions 1-3 :
    T1/T2 → 1 pt | T3 → 2 pts | T4 → 3 pts
  Positions 4-7 :
    T1/T2 → 0,5 | T3 → 1 | T4 → 2
  Position 8+ : 0

icp_proxy = min(10, score_brut / max(1, nb_sources * 1.5))
Flag : ICP_PROXY_MULTI_PRESSE (jamais écrase un ICP Fréquence-Turf).
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

from app.models import Cheval, RaceContext, Tranche
from app.engine.tranches import classify_tranche
from app.scraping.base import fetch_html

logger = logging.getLogger("vantage.scraping.stats_quinte")

URL_PRESSE = "https://stats-quinte.com/presse-quinte/"
URL_PRONO = "https://stats-quinte.com/pronostic-quinte-du-jour/"


def _paris_today() -> date:
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        return datetime.now(ZoneInfo("Europe/Paris")).date()
    except Exception:
        return date.today()


def _stats_quinte_urls_for_date(d: Optional[date]) -> List[str]:
    """URLs candidats. stats-quinte n'archive pas toujours : hors jour J,
    on tente des slugs datés puis on laisse le filtre overlap décider."""
    urls = []
    if d is not None:
        urls.extend([
            f"https://stats-quinte.com/presse-quinte/{d.isoformat()}/",
            f"https://stats-quinte.com/presse-quinte-{d.strftime('%d-%m-%Y')}/",
            f"https://stats-quinte.com/presse-quinte-{d.day}-{d.month}-{d.year}/",
        ])
    # Pages « du jour » : uniquement si d is None (inconnu) ou d == Paris today
    if d is None or d == _paris_today():
        urls.extend([URL_PRESSE, URL_PRONO])
    return list(dict.fromkeys(urls))

# Grille anti-favoris
_PTS_POS_1_3 = {
    Tranche.T1: 1.0,
    Tranche.T2: 1.0,
    Tranche.T3: 2.0,
    Tranche.T4A: 3.0,
    Tranche.T4B: 3.0,
}
_PTS_POS_4_7 = {
    Tranche.T1: 0.5,
    Tranche.T2: 0.5,
    Tranche.T3: 1.0,
    Tranche.T4A: 2.0,
    Tranche.T4B: 2.0,
}


def _points_for(tranche: Optional[Tranche], position: int) -> float:
    if position < 1:
        return 0.0
    if position <= 3:
        return _PTS_POS_1_3.get(tranche or Tranche.T3, 1.5)
    if position <= 7:
        return _PTS_POS_4_7.get(tranche or Tranche.T3, 0.75)
    return 0.0


def _parse_ranking_line(text: str) -> Optional[List[int]]:
    """Extrait une séquence de numéros type '9-12-7-1-5-13-4-2'."""
    text = text.strip()
    m = re.search(r"\b(\d{1,2}(?:\s*[-–—,/]\s*\d{1,2}){2,11})\b", text)
    if not m:
        return None
    nums = re.findall(r"\d{1,2}", m.group(1))
    out: List[int] = []
    for n in nums:
        try:
            v = int(n)
            if 1 <= v <= 20 and v not in out:
                out.append(v)
        except ValueError:
            continue
    return out if len(out) >= 3 else None


def parse_presse_quinte_html(html: str) -> Dict[str, Any]:
    """Parse la page presse-quinte : map source → ranking (liste de numéros).

    Retourne {
      "sources": { "Bilto": [13,8,2,...], ... },
      "nb_sources": N,
      "warnings": [...]
    }
    """
    soup = BeautifulSoup(html, "html.parser")
    sources: Dict[str, List[int]] = {}
    warnings: List[str] = []

    # 1) Tables : lignes "Nom source | 9-12-7-..."
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            name = cells[0].strip()
            # Ignorer en-têtes / lignes non-journal
            if not name or len(name) < 3 or name.lower().startswith("nom"):
                continue
            ranking = None
            for cell in cells[1:]:
                ranking = _parse_ranking_line(cell)
                if ranking:
                    break
            if ranking and name not in sources:
                sources[name] = ranking

    # 2) Fallback : paragraphes / listes contenant "Source : 1-2-3-..."
    if len(sources) < 3:
        for el in soup.find_all(["p", "li", "div", "span"]):
            txt = el.get_text(" ", strip=True)
            if len(txt) > 120 or len(txt) < 8:
                continue
            ranking = _parse_ranking_line(txt)
            if not ranking:
                continue
            # Préfixe avant le ranking comme nom de source
            m = re.match(r"^([A-Za-zÀ-ÿ0-9 .'\-]{3,40})\s*[:|]?\s*\d", txt)
            name = m.group(1).strip() if m else f"source_{len(sources)+1}"
            if name not in sources:
                sources[name] = ranking

    if not sources:
        warnings.append("Aucun classement presse parseable sur stats-quinte.com")
    else:
        warnings.append(f"{len(sources)} source(s) presse extraites de stats-quinte")

    return {"sources": sources, "nb_sources": len(sources), "warnings": warnings}


def compute_icp_proxy(
    chevaux: List[Cheval],
    sources: Dict[str, List[int]],
) -> Dict[str, Any]:
    """Calcule score_brut + icp_proxy par numéro selon la grille anti-favoris.

    Ne modifie pas encore les chevaux — l'appelant décide d'appliquer.
    """
    by_num = {c.numero: c for c in chevaux}
    scores: Dict[int, float] = {c.numero: 0.0 for c in chevaux}
    citations_detail: Dict[int, Dict[str, int]] = {c.numero: {} for c in chevaux}

    for src_name, ranking in sources.items():
        for pos, numero in enumerate(ranking, start=1):
            if numero not in by_num:
                continue
            cheval = by_num[numero]
            tranche = classify_tranche(cheval.cote_matin)
            pts = _points_for(tranche, pos)
            if pts <= 0:
                continue
            scores[numero] += pts
            citations_detail[numero][src_name] = pos

    nb_src = max(len(sources), 1)
    facteur = max(1.0, nb_src * 1.5)
    icp_map: Dict[int, float] = {}
    for num, brut in scores.items():
        if brut <= 0:
            continue
        icp_map[num] = round(min(10.0, brut / facteur), 2)

    return {
        "scores_bruts": scores,
        "icp_proxy": icp_map,
        "citations_detail": citations_detail,
        "nb_sources": nb_src,
        "facteur_norm": facteur,
    }


def apply_icp_proxy_to_chevaux(
    chevaux: List[Cheval],
    icp_result: Dict[str, Any],
    *,
    only_if_empty: bool = True,
) -> int:
    """Applique icp_proxy + citations. Retourne nb chevaux modifiés.

    only_if_empty=True : n'écrase jamais un icp_global déjà renseigné (FT prioritaire).
    """
    icp_map: Dict[int, float] = icp_result.get("icp_proxy") or {}
    detail: Dict[int, Dict[str, int]] = icp_result.get("citations_detail") or {}
    n = 0
    for cheval in chevaux:
        if only_if_empty and cheval.icp_global is not None and cheval.icp_global > 0:
            continue
        proxy = icp_map.get(cheval.numero)
        if proxy is None or proxy <= 0:
            continue
        # icp_global stocké en int (modèle) — on arrondit le proxy
        cheval.icp_global = max(1, int(round(proxy)))
        # icp_pondere peut rester float si le champ le permet
        if hasattr(cheval, "icp_pondere"):
            cheval.icp_pondere = float(proxy)
        cites = dict(cheval.citations_top5_par_source or {})
        for src, pos in (detail.get(cheval.numero) or {}).items():
            # cité Top5 si position <= 5
            cites[f"StatsQuinte:{src}"] = pos <= 5
        cheval.citations_top5_par_source = cites
        # flag traçabilité
        flags = list(getattr(cheval, "flags", None) or [])
        if "ICP_PROXY_MULTI_PRESSE" not in flags:
            flags.append("ICP_PROXY_MULTI_PRESSE")
        try:
            cheval.flags = flags
        except Exception:
            pass
        n += 1
    return n


def enrichir_course_stats_quinte(
    race: RaceContext,
    chevaux: List[Cheval],
) -> Dict[str, Any]:
    """Point d'entrée orchestrateur : scrape + scoring + application si ICP vide.

    Appelé en repli de Fréquence-Turf (étape 2.3bis).
    """
    rapport: Dict[str, Any] = {
        "status": "EMPTY",
        "source": "stats-quinte.com",
        "url": URL_PRESSE,
        "nb_sources": 0,
        "nb_icp_appliques": 0,
        "warnings": [],
        "grille": {
            "pos_1_3": {"T1/T2": 1, "T3": 2, "T4": 3},
            "pos_4_7": {"T1/T2": 0.5, "T3": 1, "T4": 2},
            "pos_8_plus": 0,
        },
    }

    # Ne pas écraser si déjà bien couvert par FT
    n_deja = sum(1 for c in chevaux if c.icp_global is not None and c.icp_global > 0)
    if n_deja >= max(3, len(chevaux) // 3):
        rapport["status"] = "SKIPPED"
        rapport["warnings"].append(
            f"ICP déjà renseigné pour {n_deja}/{len(chevaux)} — stats-quinte non appliqué (FT prioritaire)"
        )
        return rapport

    # Date de la course → URLs (jour J Paris vs historique)
    d_race: Optional[date] = None
    if getattr(race, "date_course", None):
        try:
            d_race = date.fromisoformat(str(race.date_course)[:10])
        except ValueError:
            d_race = None
    urls_try = _stats_quinte_urls_for_date(d_race)
    if not urls_try:
        # Course passée / future sans archive stats-quinte connue
        rapport["status"] = "SKIPPED"
        rapport["warnings"].append(
            f"stats-quinte : pas d'URL fiable pour la date {d_race} "
            f"(pages « du jour » réservées au calendrier Paris du jour). "
            f"Repli ICP non appliqué pour éviter un mauvais Quinté."
        )
        return rapport

    html = None
    url_ok = None
    for u in urls_try:
        try:
            html = fetch_html(u, timeout=18, retries=2)
            if html and len(html) > 2000 and "404" not in (html[:500] or "").lower():
                url_ok = u
                break
        except Exception as e:
            rapport["warnings"].append(f"Fetch {u} : {e}")
            logger.warning("stats_quinte fetch %s : %s", u, e)
            html = None
    if not html or not url_ok:
        rapport["status"] = "ERROR"
        rapport["warnings"].append("Tous les fetches stats-quinte ont échoué")
        return rapport
    rapport["url"] = url_ok

    parsed = parse_presse_quinte_html(html)
    rapport["warnings"].extend(parsed.get("warnings") or [])
    rapport["nb_sources"] = parsed.get("nb_sources", 0)
    sources = parsed.get("sources") or {}

    if not sources:
        rapport["status"] = "EMPTY"
        return rapport

    # Vérifier que les numéros collent au peloton (sinon mauvaise course / jour)
    nums_partants = {c.numero for c in chevaux}
    overlap = 0
    for ranking in sources.values():
        overlap += sum(1 for n in ranking[:5] if n in nums_partants)
    if overlap < 3:
        rapport["status"] = "MISMATCH"
        rapport["warnings"].append(
            f"Peu de recouvrement partants ({overlap}) — page peut concerner un autre Quinté"
        )
        # On applique quand même si au moins 1 chevauchement
        if overlap == 0:
            return rapport

    icp_result = compute_icp_proxy(chevaux, sources)
    n_app = apply_icp_proxy_to_chevaux(chevaux, icp_result, only_if_empty=True)
    rapport["nb_icp_appliques"] = n_app
    rapport["icp_proxy_sample"] = {
        str(k): v for k, v in list((icp_result.get("icp_proxy") or {}).items())[:8]
    }
    rapport["scores_bruts_sample"] = {
        str(k): round(v, 2)
        for k, v in list((icp_result.get("scores_bruts") or {}).items())[:8]
        if v > 0
    }
    rapport["status"] = "OK" if n_app > 0 else "PARTIAL"
    rapport["sources_noms"] = list(sources.keys())[:20]
    return rapport
