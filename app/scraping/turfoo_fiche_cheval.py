"""
turfoo_fiche_cheval.py -- Scraper de la fiche individuelle d'un cheval
(turfoo.fr/fiches/chevaux/{slug}/), vérifié en conditions réelles.

Chaque entrée d'historique a la forme observée (texte, une ligne d'en-tête
suivie d'un petit tableau d'arrivée) :

  "08 AOUT 2022-CLAIREFONTAINE   PRIX ... -33000-Steeple - Classe 3 -
   4 ans et 5 - 3700 mètres, Corde à droite   9 PARTANTS - 3 1/2- ...
   ENTRAINEUR : LAGENESTE & MACAIRE (S)   TERRAIN : TR SOUPLE"
  suivi d'un tableau avec rang, nom, jockey, poids, cote pour chaque partant.

On y extrait, pour NOTRE cheval (déjà identifié par son nom) : date exacte
(-> delai_j), hippodrome, distance, terrain (qualitatif -> converti en
pénétromètre approximatif), corde, rang obtenu.

Utilisation : enrichissement optionnel, best-effort (une page par cheval,
donc N requêtes HTTP supplémentaires par course -- résilient, un échec
n'interrompt pas le reste du pipeline).
"""
from __future__ import annotations
import re
import logging
from dataclasses import dataclass
from datetime import date as date_cls, datetime
from typing import List, Optional
from bs4 import BeautifulSoup

from app.scraping.base import fetch_html

logger = logging.getLogger("vantage.scraping.turfoo_fiche")

_MOIS = {
    "JANVIER": 1, "FEVRIER": 2, "FÉVRIER": 2, "MARS": 3, "AVRIL": 4, "MAI": 5, "JUIN": 6,
    "JUILLET": 7, "AOUT": 8, "AOÛT": 8, "SEPTEMBRE": 9, "OCTOBRE": 10, "NOVEMBRE": 11, "DECEMBRE": 12,
    "DÉCEMBRE": 12,
}

# Conversion approximative qualificatif terrain -> pénétromètre PMU (Partie 1.8
# du protocole). Documentée comme approximation -- aucune échelle officielle
# publique associant les deux avec précision.
_TERRAIN_QUALIF_TO_PENETRO = {
    "TRES LEGER": 0.8, "TRÈS LÉGER": 0.8, "LEGER": 1.5, "LÉGER": 1.5,
    "BON LEGER": 2.3, "BON LÉGER": 2.3, "BON": 3.0, "BON SOUPLE": 3.7,
    "SOUPLE": 4.5, "TR SOUPLE": 5.0, "TRES SOUPLE": 5.0, "COLLANT": 6.5,
    "LOURD": 6.0, "TRES LOURD": 7.5, "TRÈS LOURD": 7.5, "STANDARD": 3.5,
}

_ENTRY_START_RE = re.compile(
    r"(\d{1,2})\s+([A-ZÉÛÀÇ]+)\s+(\d{4})-([A-ZÀ-Ü][A-ZÀ-Ü\-'\s]*?)\s*-?\s*PRIX",
    re.I,
)
_DISTANCE_RE = re.compile(r"(\d[\d.,\s\xa0]{2,6})\s*m[eè]tres", re.I)
_CORDE_RE = re.compile(r"Corde\s*à\s*(\w+)", re.I)
_PARTANTS_RE = re.compile(r"(\d{1,2})\s*PARTANTS", re.I)
_TERRAIN_RE = re.compile(r"TERRAIN\s*:\s*([A-ZÀ-Ü\s]{2,25}?)(?=\n|\||\s{2,}|$)", re.I)
# Discipline dans l'en-tête de course (ex. "-Steeple - Classe 3", "Plat -", "Trot Attelé")
_DISC_HIST_RE = re.compile(
    r"\b(Steeple(?:-chase)?|Haies?|Plat|Trot\s*Attel[ée]|Trot\s*Mont[ée]|Obstacle)\b",
    re.I,
)
_DISC_HIST_MAP = {
    "steeple": "STEEPLE", "steeple-chase": "STEEPLE", "steeplechase": "STEEPLE",
    "haie": "HAIES", "haies": "HAIES",
    "plat": "PLAT",
    "trot attelé": "TROT_ATTELE", "trot attele": "TROT_ATTELE",
    "trot monté": "TROT_MONTE", "trot monte": "TROT_MONTE",
    "obstacle": "STEEPLE",  # générique → steeple par défaut
}


@dataclass
class FicheChevalHistorique:
    date: Optional[str]        # ISO
    hippodrome: str
    distance_m: Optional[int]
    corde: Optional[str]
    terrain_qualificatif: str
    penetrometre_approx: Optional[float]
    partants: Optional[int]
    notre_rang: Optional[int]
    # Discipline de la course historique (extrait du texte d'en-tête)
    # Valeurs : PLAT | TROT_ATTELE | TROT_MONTE | HAIES | STEEPLE | None
    discipline: Optional[str] = None


@dataclass
class FicheCheval:
    age: Optional[int]
    sexe: Optional[str]
    origine: Optional[str]
    proprietaire: Optional[str]
    musique: Optional[str]
    courses_carriere: Optional[int]
    victoires_carriere: Optional[int]
    places_carriere: Optional[int]
    historique: List[FicheChevalHistorique]


def _parse_date(jour: str, mois: str, annee: str) -> Optional[str]:
    m = _MOIS.get(mois.upper().strip())
    if not m:
        return None
    try:
        return date_cls(int(annee), m, int(jour)).isoformat()
    except ValueError:
        return None


_RANG_SEUL_RE = re.compile(r"^\s*(\d+|TBE|TET|NP|DAI|ARR)\s*$", re.I)


def _find_rang_in_mini_table(table_text: str, nom_cheval: str) -> Optional[int]:
    """Cherche le rang de notre cheval dans le petit tableau d'arrivée qui
    suit l'en-tête de la course. Corrigé le 06/08/2026 : avec
    get_text("\\n"), chaque CELLULE de la ligne de tableau devient sa
    propre ligne de texte -- le rang et le nom du cheval ne sont donc
    JAMAIS sur la même ligne (rang = cellule précédente, à 1-3 lignes
    d'écart selon les colonnes vides). On cherche maintenant en arrière
    depuis la ligne du nom plutôt que sur la même ligne (qui ne contient
    jamais que le nom seul)."""
    nom_norm = re.sub(r"\s+", " ", nom_cheval.strip().upper())
    lines = table_text.splitlines()
    for i, line in enumerate(lines):
        if nom_norm in line.upper():
            for back in range(1, 4):
                j = i - back
                if j < 0:
                    break
                m = _RANG_SEUL_RE.match(lines[j].strip())
                if m:
                    val = m.group(1)
                    return int(val) if val.isdigit() else None
            return None
    return None


def fetch_fiche_cheval(url_or_slug: str, nom_cheval: str) -> FicheCheval:
    url = url_or_slug if url_or_slug.startswith("http") else f"https://www.turfoo.fr/fiches/chevaux/{url_or_slug}/"
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text("\n", strip=True)

    age = sexe = origine = proprietaire = musique = None
    m = re.search(r"Age\s*\|?\s*(\d+)\s*ANS", text, re.I)
    if m:
        age = int(m.group(1))
    m = re.search(r"Sexe\s*\|?\s*(F[EÉ]MELLE|M[AÂ]LE|HONGRE)", text, re.I)
    if m:
        sexe = m.group(1).upper()[0]
    # Corrigé le 06/08/2026 : le "|" en fin de motif était obligatoire alors
    # qu'il n'existe QUE dans le rendu markdown utilisé pour visualiser la
    # page (artefact de mise en forme d'un tableau HTML), jamais dans le
    # texte réellement extrait par get_text() -- ces 3 regex ne matchaient
    # donc jamais rien en conditions réelles (confirmé sur une vraie page,
    # JAINA D'ESSARTS). "|" rendu optionnel, comme pour Age/Sexe déjà.
    m = re.search(r"Origine\s*\|?\s*(.+?)\s*(?:\||Propri[ée]taire|Record|Musique|$)", text)
    if m:
        origine = m.group(1).strip()
    m = re.search(r"Propri[ée]taire\s*\|?\s*(.+?)\s*(?:\||Musique|Carri[èe]re|$)", text)
    if m:
        proprietaire = m.group(1).strip()
    m = re.search(r"Musique\s*\|?\s*([\dA-Za-z()\s]+?)\s*(?:\||Carri[èe]re|$)", text)
    if m:
        musique = m.group(1).strip()

    courses = victoires = places = None
    m = re.search(r"Courses\s*\|?\s*(\d+)\s*\|?\s*(\d+)\s*\|?\s*(\d+)", text)
    if m:
        courses, victoires, places = int(m.group(1)), int(m.group(2)), int(m.group(3))

    historique = []
    all_matches = list(_ENTRY_START_RE.finditer(text))
    for i, entry in enumerate(all_matches):
        jour, mois, annee, hippo = entry.groups()
        window_end = all_matches[i + 1].start() if i + 1 < len(all_matches) else entry.end() + 1500
        window = text[entry.end():window_end]

        dist_m = _DISTANCE_RE.search(window)
        distance = None
        if dist_m:
            raw = re.sub(r"[^\d]", "", dist_m.group(1))  # "2.100"/"2 100" -> "2100" (le point est un séparateur de milliers, pas une décimale)
            distance = int(raw) if raw else None

        corde_m = _CORDE_RE.search(window)
        corde = corde_m.group(1) if corde_m else None  # absent si départ autostart (TROT)

        partants_m = _PARTANTS_RE.search(window)
        partants = int(partants_m.group(1)) if partants_m else None

        terrain_m = _TERRAIN_RE.search(window)
        terrain_norm = re.sub(r"\s+", " ", terrain_m.group(1).strip().upper()) if terrain_m else None
        penetro = _TERRAIN_QUALIF_TO_PENETRO.get(terrain_norm) if terrain_norm else None

        rang = _find_rang_in_mini_table(window[:800], nom_cheval)

        disc_m = _DISC_HIST_RE.search(window[:400])
        disc_hist = None
        if disc_m:
            key = re.sub(r"\s+", " ", disc_m.group(1).strip().lower())
            disc_hist = _DISC_HIST_MAP.get(key)
            if disc_hist is None:
                # fuzzy : steeple / haie / plat / trot
                if "steeple" in key:
                    disc_hist = "STEEPLE"
                elif "haie" in key:
                    disc_hist = "HAIES"
                elif "plat" in key:
                    disc_hist = "PLAT"
                elif "attel" in key:
                    disc_hist = "TROT_ATTELE"
                elif "mont" in key:
                    disc_hist = "TROT_MONTE"

        historique.append(FicheChevalHistorique(
            date=_parse_date(jour, mois, annee), hippodrome=hippo.strip(),
            distance_m=distance, corde=corde,
            terrain_qualificatif=terrain_norm or "INCONNU", penetrometre_approx=penetro,
            partants=partants, notre_rang=rang,
            discipline=disc_hist,
        ))

    return FicheCheval(age=age, sexe=sexe, origine=origine, proprietaire=proprietaire,
                        musique=musique, courses_carriere=courses, victoires_carriere=victoires,
                        places_carriere=places, historique=historique)


def compute_delai_j(historique: List[FicheChevalHistorique], date_course_actuelle: str) -> Optional[int]:
    try:
        d_course = datetime.fromisoformat(date_course_actuelle).date()
    except ValueError:
        return None
    # v1.29.40 : seules les perfs STRICTEMENT antérieures à la course comptent
    dates = []
    for h in historique:
        if not h.date:
            continue
        try:
            if datetime.fromisoformat(h.date).date() < d_course:
                dates.append(h.date)
        except ValueError:
            continue
    if not dates:
        return None
    dates.sort(reverse=True)
    try:
        d_derniere = datetime.fromisoformat(dates[0]).date()
        return (d_course - d_derniere).days
    except ValueError:
        return None
