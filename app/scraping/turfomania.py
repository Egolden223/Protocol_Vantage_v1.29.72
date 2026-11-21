"""turfomania.py — Source secondaire d'enrichissement (v1.29.28).

Turfomania publie pour le trot (ex. GNT) :
  - Dist. par cheval → recul_m
  - Def / ferrure (D4, PADP…)
  - gains, record, musique, délai (17j)
  - driver / entraîneur

Ne remplit QUE les champs encore vides. Échecs non bloquants.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from app.models import Cheval, RaceContext
from app.scraping.base import fetch_html

logger = logging.getLogger("vantage.turfomania")

_MONTHS_FR = {
    1: "janvier", 2: "fevrier", 3: "mars", 4: "avril", 5: "mai", 6: "juin",
    7: "juillet", 8: "aout", 9: "septembre", 10: "octobre", 11: "novembre", 12: "decembre",
}
_JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _slug(s: str) -> str:
    s = (s or "").lower()
    for a, b in (
        ("é", "e"), ("è", "e"), ("ê", "e"), ("à", "a"), ("â", "a"),
        ("ô", "o"), ("ù", "u"), ("û", "u"), ("î", "i"), ("ç", "c"), ("'", "-"),
        (" ", "-"),
    ):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9\-]+", "", s)


def _parse_int(s: Any) -> Optional[int]:
    if s is None:
        return None
    m = re.search(r"(\d+)", str(s).replace("\xa0", "").replace(" ", ""))
    return int(m.group(1)) if m else None


def _parse_eur(s: Any) -> Optional[float]:
    if s is None:
        return None
    t = str(s).replace("\xa0", " ").replace("€", "").replace(" ", "").replace(",", ".")
    m = re.search(r"([\d.]+)", t)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def candidate_urls(race: RaceContext) -> List[str]:
    """Construit des URL Turfomania candidates à partir de date + hippodrome."""
    urls: List[str] = []
    date_s = getattr(race, "date_course", None) or ""
    hippo = _slug(getattr(race, "hippodrome", "") or "")
    if not date_s or not hippo:
        return urls
    try:
        d = datetime.fromisoformat(date_s[:10])
    except ValueError:
        return urls
    jour = _JOURS[d.weekday()]
    mois = _MONTHS_FR[d.month]
    # Patterns observés 2026
    base = (
        f"https://www.turfomania.fr/pronostics/partants-{jour}-{d.day}-{mois}-{d.year}"
        f"-{hippo}"
    )
    urls.append(f"{base}-grand-national-du-trot.html")
    urls.append(f"{base}.html")
    # Variante sans "partants-"
    urls.append(
        f"https://www.turfomania.fr/pronostics/{jour}-{d.day}-{mois}-{d.year}-{hippo}.html"
    )
    return urls


def _find_partants_table(soup: BeautifulSoup):
    for table in soup.find_all("table"):
        text = table.get_text(" ", strip=True)[:200].lower()
        if "cheval" in text and ("dist" in text or "cote" in text or "driver" in text):
            return table
    return None


def parse_turfomania_partants(html: str, race: RaceContext) -> Tuple[Dict[int, Dict[str, Any]], List[str]]:
    """Extrait par numéro: recul, ferrure, gains, musique, delai_j approximatif."""
    soup = BeautifulSoup(html, "html.parser")
    table = _find_partants_table(soup)
    out: Dict[int, Dict[str, Any]] = {}
    warnings: List[str] = []
    if not table:
        return out, ["TURFOMANIA_TABLE_INTROUVABLE"]

    rows = table.find_all("tr")
    if not rows:
        return out, ["TURFOMANIA_ROWS_VIDES"]

    base_dist = race.distance_m or 0
    for tr in rows[1:]:
        cells = tr.find_all(["td", "th"])
        if len(cells) < 3:
            continue
        texts = [c.get_text(" ", strip=True) for c in cells]
        # Première cellule souvent "N° + nom + musique"
        head = texts[0]
        m_num = re.match(r"^(\d{1,2})\s*(.*)$", head)
        if not m_num:
            # parfois N° dans cellule séparée
            m_num = re.match(r"^(\d{1,2})$", texts[0])
            if not m_num:
                continue
            numero = int(m_num.group(1))
            nom_mus = texts[1] if len(texts) > 1 else ""
        else:
            numero = int(m_num.group(1))
            nom_mus = m_num.group(2)

        # Musique: séquence type 3a 4a 1a ou (17j)
        delai_j = None
        m_delai = re.search(r"\((\d+)\s*j\)", nom_mus, re.I)
        if m_delai:
            delai_j = int(m_delai.group(1))
        musique = None
        m_mus = re.search(r"((?:\d+[a-zA-Z]|Da|Dm|0a|Ga)(?:\s+(?:\d+[a-zA-Z]|Da|Dm|0a|Ga)){2,})", nom_mus)
        if m_mus:
            musique = m_mus.group(1).strip()

        dist_ligne = None
        fer = None
        gains = None
        for tx in texts[1:]:
            # Distance pure
            if re.fullmatch(r"\d{3,4}", tx.replace(" ", "")):
                dist_ligne = int(tx.replace(" ", ""))
            # Ferrure codes
            elif re.fullmatch(r"(D4|DA|DP|PA|PP|P4|PADP|Pa\s*Dp|F4|DP/PA|DA/PP)", tx, re.I):
                fer = tx.upper().replace(" ", "")
                if fer in ("PADP", "PADP"):
                    fer = "PADP"
            # Gains
            elif "€" in tx or re.search(r"\d[\d\s]{4,}", tx):
                g = _parse_eur(tx)
                if g and g > 1000:
                    gains = g

        recul_m = None
        if dist_ligne and base_dist:
            delta = dist_ligne - base_dist
            if delta >= 0:
                recul_m = delta

        deferre = None
        if fer and fer.startswith("D"):
            deferre = fer
        elif fer in ("PA", "PP", "P4"):
            deferre = "FERRE"

        out[numero] = {
            "recul_m": recul_m,
            "distance_ligne": dist_ligne,
            "ferrure_type": fer,
            "deferre": deferre,
            "gains_totaux_eur": gains,
            "musique": musique,
            "delai_j": delai_j,
        }
    if not out:
        warnings.append("TURFOMANIA_AUCUN_PARTANT_PARSE")
    return out, warnings


def enrich_race_with_turfomania(race: RaceContext, chevaux: List[Cheval]) -> Dict[str, Any]:
    """Enrichit les chevaux depuis Turfomania (champs vides seulement)."""
    report: Dict[str, Any] = {"status": "SKIPPED", "fields_filled": 0, "url": None, "warnings": []}
    urls = candidate_urls(race)
    html = None
    used = None
    for url in urls:
        try:
            html = fetch_html(url)
            if html and len(html) > 2000 and "cheval" in html.lower():
                used = url
                break
        except Exception as e:
            report["warnings"].append(f"fetch:{url[:60]}:{str(e)[:60]}")
    if not used or not html:
        # Recherche DDG site:turfomania.fr
        try:
            q = f'site:turfomania.fr partants {getattr(race, "hippodrome", "")} {getattr(race, "date_course", "")[:10]}'
            from app.scraping.web_search_enrich import duckduckgo_search_urls
            found = duckduckgo_search_urls(q, max_results=5)
            for u in found:
                if "turfomania.fr" not in u:
                    continue
                try:
                    html = fetch_html(u)
                    if html and "cheval" in html.lower():
                        used = u
                        break
                except Exception:
                    continue
        except Exception as e:
            report["warnings"].append(f"ddg:{str(e)[:80]}")

    if not used or not html:
        report["status"] = "NOT_FOUND"
        return report

    report["url"] = used
    by_num, warns = parse_turfomania_partants(html, race)
    report["warnings"].extend(warns)
    filled = 0
    by_cheval = {c.numero: c for c in chevaux}
    for num, data in by_num.items():
        c = by_cheval.get(num)
        if not c:
            continue
        for field, val in data.items():
            if field == "distance_ligne":
                continue
            if val is None or val == "":
                continue
            cur = getattr(c, field, None)
            if cur is None or cur == "" or cur == []:
                setattr(c, field, val)
                filled += 1
                flags = list(c.flags or [])
                flags.append(f"ENRICHI_TURFOMANIA_{field.upper()}")
                c.flags = flags
    report["fields_filled"] = filled
    report["status"] = "OK" if filled or by_num else "EMPTY"
    report["nb_partants_parses"] = len(by_num)
    return report
