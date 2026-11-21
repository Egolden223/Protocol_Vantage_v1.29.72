"""
zoneturf_fiche_cheval.py -- Fiche individuelle cheval sur zone-turf.fr/cheval/{slug}/.

Données extraites (vérifiées en conditions réelles 13/09/2026) :
  - musique affichée
  - performances détaillées : date, hippodrome, distance, discipline,
    terrain (BON/SOUPLE/PSF/…), rang du cheval, jockey

Utilisé par enrichment.py quand fiche_url pointe vers zone-turf.fr
(Turfoo souvent inaccessible sans curl_cffi).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from bs4 import BeautifulSoup

from app.scraping.base import fetch_html

logger = logging.getLogger("vantage.scraping.zoneturf_fiche")

_DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_DIST_RE = re.compile(r"(\d{3,4})\s*m\b", re.I)
_TERRAIN_RE = re.compile(
    r"\b(BON|SOUPLE|TRÈS SOUPLE|TR SOUPLE|LOURD|COLLANT|PSF|BONNE|YIELDING|SOFT|HEAVY|FIRM|GOOD)\b",
    re.I,
)
_DISC_RE = re.compile(r"\b(Plat|Trot|Attelé|Monté|Haies|Steeple|Obstacle)\b", re.I)


@dataclass
class ZoneTurfPerf:
    date: str  # ISO YYYY-MM-DD
    hippodrome: str
    distance_m: Optional[int]
    discipline: Optional[str]
    terrain: Optional[str]
    rang: Optional[int]
    jockey: Optional[str] = None
    cote: Optional[float] = None
    poids_kg: Optional[float] = None


@dataclass
class ZoneTurfFicheCheval:
    nom: str
    musique: Optional[str] = None
    historique: List[ZoneTurfPerf] = field(default_factory=list)
    nb_courses: Optional[int] = None
    nb_victoires: Optional[int] = None
    nb_places: Optional[int] = None
    gains_totaux_eur: Optional[float] = None
    valeur_handicap: Optional[float] = None
    aptitudes_terrain: Optional[dict] = None  # BON/SOUPLE/LOURD/PSF


def _iso(d: str, m: str, y: str) -> str:
    return f"{y}-{m}-{d}"


def _norm_disc(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = raw.lower()
    if "attel" in s or (s == "trot"):
        return "TROT_ATTELE"
    if "monté" in s or "monte" in s:
        return "TROT_MONTE"
    if "haie" in s:
        return "HAIES"
    if "steeple" in s or "obstacle" in s:
        return "STEEPLE"
    if "plat" in s:
        return "PLAT"
    return raw.upper()


def fetch_zoneturf_fiche_cheval(url_or_path: str, nom_cheval: Optional[str] = None) -> ZoneTurfFicheCheval:
    url = url_or_path if url_or_path.startswith("http") else f"https://www.zone-turf.fr{url_or_path}"
    # drop fragment
    url = url.split("#")[0]
    if not url.endswith("/"):
        url += "/"

    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")

    h1 = soup.find("h1")
    nom = (h1.get_text(" ", strip=True) if h1 else (nom_cheval or "")).split(" H")[0].split(" F")[0].strip()
    if nom_cheval and not nom:
        nom = nom_cheval

    musique = None
    m_el = soup.find(id="musique-filtre-perf")
    if m_el:
        musique = m_el.get_text(" ", strip=True) or None

    historique: List[ZoneTurfPerf] = []
    # Chaque past race = div.bloc.data.inner-bloc.course
    for bloc in soup.select("div.bloc.data.inner-bloc.course, div.inner-bloc.course"):
        header = bloc.get_text(" ", strip=True)[:220]
        dm = _DATE_RE.search(header)
        if not dm:
            continue
        date_iso = _iso(dm.group(1), dm.group(2), dm.group(3))
        # hippodrome : texte avant la date
        hippo = header[: dm.start()].strip(" -–|\t")
        hippo = re.sub(r"\s+", " ", hippo).strip() or "INCONNU"
        dist_m = None
        dm2 = _DIST_RE.search(header)
        if dm2:
            dist_m = int(dm2.group(1))
        terr = None
        tm = _TERRAIN_RE.search(header)
        if tm:
            terr = tm.group(1).upper()
        disc = None
        dcm = _DISC_RE.search(header)
        if dcm:
            disc = _norm_disc(dcm.group(1))

        # Rang du cheval cible dans le tableau du bloc
        rang = None
        jockey = None
        cote = None
        poids_kg = None
        jockey = None
        cote = None
        nom_u = (nom_cheval or nom).strip().upper()
        table = bloc.find("table")
        if table:
            for tr in table.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if len(cells) < 2:
                    continue
                # col0 = rang, col1 = nom cheval
                try:
                    r0 = int(re.sub(r"\D", "", cells[0]) or "0")
                except ValueError:
                    continue
                if r0 <= 0:
                    continue
                horse_cell = cells[1].upper()
                if nom_u and nom_u in horse_cell:
                    rang = r0
                    # jockey often col 5 or 6
                    for c in cells[2:]:
                        if re.match(r"^[A-ZÀ-Ü]\.\s*[A-ZÀ-Ü]", c, re.I) or (
                            len(c) > 2 and c[0].isalpha() and not re.match(r"^[\d.,]+$", c)
                        ):
                            if not re.match(r"^[\d.,]+$", c) and "m" not in c.lower()[:3]:
                                if re.search(r"[A-Za-z]", c) and len(c) < 40:
                                    jockey = c
                                    break
                    for c in cells:
                        if re.match(r"^[\d]+[.,][\d]+$", c) or re.match(r"^[\d]+$", c):
                            try:
                                v = float(c.replace(",", "."))
                                if 1.1 <= v <= 200:
                                    cote = v
                                    break
                            except ValueError:
                                pass
                    # Poids plat typique 50-75
                    poids_kg = None
                    for c in cells:
                        cm = re.match(r"^(\d{2})(?:[.,](\d))?$", c.strip())
                        if cm:
                            try:
                                v = float(c.replace(",", "."))
                                if 45.0 <= v <= 78.0:
                                    poids_kg = v
                                    break
                            except ValueError:
                                pass
                    break

        if rang is None:
            # parfois le rang n'est pas retrouvé ; on garde la course si header ok
            continue

        historique.append(
            ZoneTurfPerf(
                date=date_iso,
                hippodrome=hippo,
                distance_m=dist_m,
                discipline=disc,
                terrain=terr,
                rang=rang,
                jockey=jockey,
                cote=cote,
                poids_kg=locals().get("poids_kg"),
            )
        )

    # dédup + tri date desc
    seen = set()
    uniq = []
    for p in sorted(historique, key=lambda x: x.date, reverse=True):
        key = (p.date, p.hippodrome, p.rang, p.distance_m)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)

    text = soup.get_text(" ", strip=True)
    gains = None
    m = re.search(r"Gains\s*:\s*([\d\s\xa0]+)\s*€", text, re.I)
    if m:
        raw = re.sub(r"[\s\xa0]", "", m.group(1))
        try:
            gains = float(raw)
        except ValueError:
            pass
    valeur = None
    m = re.search(r"Valeur\s*handicap\s*:\s*([\d.,]+)", text, re.I)
    if m:
        try:
            valeur = float(m.group(1).replace(",", "."))
        except ValueError:
            pass
    n_c = n_v = n_p = None
    m = re.search(r"Courses\s*courues\s*:\s*(\d+)", text, re.I)
    if m:
        n_c = int(m.group(1))
    m = re.search(r"Victoires\s*:\s*(\d+)", text, re.I)
    if m:
        n_v = int(m.group(1))
    m = re.search(r"Plac[ée]s?\s*:\s*(\d+)", text, re.I)
    if m:
        n_p = int(m.group(1))
    apt = {}
    for lab in ("Bon", "Souple", "Lourd", "PSF"):
        mm = re.search(lab + r"\s*:\s*([\d]+\s*%|-)", text, re.I)
        if mm and mm.group(1).strip() != "-":
            try:
                apt[lab.upper()] = float(mm.group(1).replace("%", "").strip())
            except ValueError:
                pass

    nb_v = n_v if n_v is not None else (sum(1 for p in uniq if p.rang == 1) if uniq else None)
    nb_c = n_c if n_c is not None else (len(uniq) if uniq else None)
    return ZoneTurfFicheCheval(
        nom=nom,
        musique=musique,
        historique=uniq,
        nb_courses=nb_c,
        nb_victoires=nb_v,
        nb_places=n_p,
        gains_totaux_eur=gains,
        valeur_handicap=valeur,
        aptitudes_terrain=apt or None,
    )
