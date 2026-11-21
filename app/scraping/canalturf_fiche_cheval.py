"""
canalturf_fiche_cheval.py -- Fiche individuelle cheval sur CanalTurf.com
(courses_fiche_cheval.php?idcheval=N), vérifiée en conditions réelles.

Structure bien plus simple que la fiche Turfoo : gains en clair, et
"Dernières performances PMU" en une ligne par course (rang, date, jockey,
cote, hippodrome, prix, lien résultats) -- pas de mini-tableau à
désimbriquer.
"""
from __future__ import annotations
import re
import logging
from dataclasses import dataclass
from typing import List, Optional
from bs4 import BeautifulSoup

from app.scraping.base import fetch_html

logger = logging.getLogger("vantage.scraping.canalturf_fiche")

_PERF_RE = re.compile(
    r"(\d{1,2})(?:er|ère|ème|nd)?\s*"
    r"(\d{2})/(\d{2})/(\d{4})\s*"
    r"[A-ZÀ-Ü][\w'\.\s]*?\(([A-ZÀ-Ü\.\s]+)\)\s*-\s*"
    r"([\d.,]+)/1\s+([A-ZÀ-Ü][A-ZÀ-Ü\- ]*?)\s*-\s*(.+?)(?=\n|\||$)",
    re.M,
)


@dataclass
class CanalturfPerf:
    rang: int
    date: str  # ISO
    jockey: str
    cote: Optional[float]
    hippodrome: str
    prix: str


@dataclass
class CanalturfFicheCheval:
    sexe: Optional[str]
    age: Optional[int]
    robe: Optional[str]
    pere: Optional[str]
    mere: Optional[str]
    proprietaire: Optional[str]
    entraineur: Optional[str]
    gains_totaux_eur: Optional[float]
    nb_courses: Optional[int]
    nb_victoires: Optional[int]
    nb_places: Optional[int]
    dernieres_perfs: List[CanalturfPerf]
    musique: Optional[str] = None


def _parse_float(s: str) -> Optional[float]:
    s = re.sub(r"[€\s]", "", s).replace(",", ".")
    m = re.search(r"-?\d+(\.\d+)?", s)
    return float(m.group()) if m else None


def fetch_canalturf_fiche_cheval(url_or_id) -> CanalturfFicheCheval:
    url = url_or_id if str(url_or_id).startswith("http") else \
        f"https://www.canalturf.com/courses_fiche_cheval.php?idcheval={url_or_id}"
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text("\n", strip=True)

    sexe = age = robe = pere = mere = proprietaire = entraineur = None
    m = re.search(r"Sexe/Age\s*:?\s*\n?([A-Za-z])(\d+)", text)
    if m:
        sexe, age = m.group(1).upper(), int(m.group(2))
    m = re.search(r"Robe\s*:?\s*\n?([A-ZÀ-Ü ]+)", text)
    if m:
        robe = m.group(1).strip()
    m = re.search(r"Père\s*:?\s*\n?([A-ZÀ-Ü0-9' \-]+?)(?=\n|Mère)", text)
    if m:
        pere = m.group(1).strip()
    m = re.search(r"Mère\s*:?\s*\n?([A-ZÀ-Ü0-9' \-]+?)(?=\n|Père de Mère|Propriétaire)", text)
    if m:
        mere = m.group(1).strip()
    m = re.search(r"Propriétaire\s*:?\s*\n?(.+?)(?=\n|Entraineur)", text)
    if m:
        proprietaire = m.group(1).strip()
    m = re.search(r"Entraineur\s*:?\s*\n?(.+?)(?=\n|$)", text)
    if m:
        entraineur = m.group(1).strip()

    gains = nb_courses = nb_victoires = nb_places = None
    m = re.search(r"Gains\s*:?\s*\n?([\d\s\xa0]+)\s*€", text)
    if m:
        gains = _parse_float(m.group(1))
    m = re.search(r"Course\(s\)\s*:?\s*\n?(\d+)", text)
    if m:
        nb_courses = int(m.group(1))
    m = re.search(r"Victoire\(s\)\s*:?\s*\n?(\d+)", text)
    if m:
        nb_victoires = int(m.group(1))
    m = re.search(r"Placé\(s\)\s*:?\s*\n?(\d+)", text)
    if m:
        nb_places = int(m.group(1))
    musique = None
    m = re.search(r"Perf\.\s*:?\s*\n?([0-9a-zA-Z]{4,40})", text)
    if m:
        musique = m.group(1).strip()

    perfs = []
    section_m = re.search(r"Dernières performances PMU(.+?)(?=Stats palmarès|\Z)", text, re.S)
    section = section_m.group(1) if section_m else ""
    for pm in _PERF_RE.finditer(section):
        rang, jj, mm, aaaa, jockey, cote, hippo, prix = pm.groups()
        try:
            date_iso = f"{aaaa}-{mm}-{jj}"
        except Exception:
            continue
        perfs.append(CanalturfPerf(
            rang=int(rang), date=date_iso, jockey=jockey.strip(),
            cote=_parse_float(cote) if cote else None,
            hippodrome=hippo.strip(), prix=prix.strip()[:60],
        ))

    return CanalturfFicheCheval(
        sexe=sexe, age=age, robe=robe, pere=pere, mere=mere, proprietaire=proprietaire,
        entraineur=entraineur, gains_totaux_eur=gains, nb_courses=nb_courses,
        nb_victoires=nb_victoires, nb_places=nb_places, musique=musique,
        dernieres_perfs=perfs,
    )
