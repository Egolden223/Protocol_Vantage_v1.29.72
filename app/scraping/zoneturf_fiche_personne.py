"""Fiches jockey/driver et entraîneur Zone-Turf.fr.

URL types observés :
  /jockey/m-guyon-821/
  /entraineur/a-murphy-s-631216/

Tableau performances : Date | Rang | … | Hippodrome | Cheval | Poids | …
Best-effort, jamais bloquant.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from bs4 import BeautifulSoup

from app.scraping.base import fetch_html
from app.scraping.turfoo_fiche_personne import CourseHistorique

logger = logging.getLogger("vantage.scraping.zoneturf_fiche_personne")

_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{2,4})$")


@dataclass
class ZoneTurfPersonneStats:
    nom: str = ""
    historique: List[CourseHistorique] = field(default_factory=list)
    nb_courses: Optional[int] = None
    nb_victoires: Optional[int] = None
    nb_places: Optional[int] = None
    taux_place_pct: Optional[float] = None
    musique: Optional[str] = None


def fetch_zoneturf_fiche_personne(url: str) -> ZoneTurfPersonneStats:
    if not url.startswith("http"):
        url = f"https://www.zone-turf.fr{url}"
    url = url.split("#")[0]
    if not url.endswith("/"):
        url += "/"
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1")
    nom = h1.get_text(" ", strip=True) if h1 else ""
    text = soup.get_text(" ", strip=True)

    nb_c = nb_v = nb_p = None
    m = re.search(r"Courses\s*courues\s*:\s*(\d+)", text, re.I)
    if m:
        nb_c = int(m.group(1))
    m = re.search(r"Nb\s*de\s*victoires\s*:\s*(\d+)", text, re.I)
    if m:
        nb_v = int(m.group(1))
    m = re.search(r"Nb\s*de\s*places\s*:\s*(\d+)", text, re.I)
    if m:
        nb_p = int(m.group(1))
    taux = None
    m = re.search(r"%\s*Réussite\s*à\s*la\s*place\s*:\s*([\d.,]+)\s*%", text, re.I)
    if m:
        try:
            taux = float(m.group(1).replace(",", "."))
        except ValueError:
            pass
    musique = None
    m = re.search(r"Musique\s*:\s*([0-9a-zA-Z\s]{3,60})", text, re.I)
    if m:
        musique = re.sub(r"\s+", " ", m.group(1)).strip()

    historique: List[CourseHistorique] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        if not any("date" in h for h in headers):
            continue
        if not any("rang" in h for h in headers):
            continue
        # index columns
        def idx(*names):
            for i, h in enumerate(headers):
                if any(n in h for n in names):
                    return i
            return None
        i_date = idx("date")
        i_rang = idx("rang")
        i_hippo = idx("hippodrome", "hippo")
        i_cheval = idx("cheval")
        for tr in rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if i_date is None or i_date >= len(cells):
                continue
            dm = _DATE_RE.match(cells[i_date].strip())
            if not dm:
                continue
            jj, mm, aa = dm.groups()
            if len(aa) == 2:
                aa = "20" + aa
            date_iso = f"{aa}-{mm}-{jj}"
            rang = None
            if i_rang is not None and i_rang < len(cells):
                try:
                    rang = int(re.sub(r"\D", "", cells[i_rang]) or "0") or None
                except ValueError:
                    rang = None
            hippo = cells[i_hippo] if i_hippo is not None and i_hippo < len(cells) else ""
            cheval = cells[i_cheval] if i_cheval is not None and i_cheval < len(cells) else None
            historique.append(CourseHistorique(
                date=date_iso, hippodrome=hippo, partants=0, rang=rang, cheval=cheval,
            ))
        if historique:
            break

    if not historique:
        logger.warning("ZT personne: aucune monte pour %s", url)

    return ZoneTurfPersonneStats(
        nom=nom,
        historique=historique,
        nb_courses=nb_c,
        nb_victoires=nb_v,
        nb_places=nb_p,
        taux_place_pct=taux,
        musique=musique,
    )
