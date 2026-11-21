"""
canalturf_fiche_personne.py -- Fiches jockey/driver et entraîneur
CanalTurf (courses_fiche_jockey.php?idjockey=X, courses_fiche_entraineur.
php?identraineur=X). Comble le trou laissé par enrichment.py
(FICHE_JOCKEY_CANALTURF_NON_IMPLEMENTEE / FICHE_ENTRAINEUR_CANALTURF_
NON_IMPLEMENTEE) -- une course dont la source retenue est CanalTurf
n'avait jusqu'ici aucune stat driver/entraîneur.

Structure vérifiée le 04/08/2026 sur une vraie fiche (Jérome CLAUDIC,
idjockey=82) -- server-rendu, pas de JS nécessaire, même fiabilité que
canalturf_fiche_cheval.py.

Différence avec Turfoo : CanalTurf donne une liste datée de "dernières
montes" (rang + date, pas de nombre de partants) au lieu de fenêtres déjà
calculées -- on recalcule les fenêtres nous-mêmes avec la même fonction
`fenetres_victoires` que Turfoo (turfoo_fiche_personne.py), qui n'inclut
que les fenêtres réellement couvertes par les données récupérées (cf.
correctif du même jour dans ce fichier).

Bonus non exploité pour l'instant (pas de champ correspondant dans
DriverStats) : la page donne aussi un taux de réussite CARRIÈRE et un
taux de réussite spécifique Quinté+ ("Statistiques des courses Quinté+"),
potentiellement plus pertinent que des fenêtres glissantes pour ce
protocole -- capturé dans `CanalturfPersonneStats.taux_victoire_quinte`
si besoin de le brancher plus tard.
"""
from __future__ import annotations
import re
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from bs4 import BeautifulSoup

from app.scraping.base import fetch_html
from app.scraping.turfoo_fiche_personne import CourseHistorique

logger = logging.getLogger("vantage.scraping.canalturf_fiche_personne")

_DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_RANG_RE = re.compile(r"^\s*(\d+)")
_HIPPO_RE = re.compile(r"\d+/1\s+([A-ZÀ-Ü][A-ZÀ-Ü\-'\s]{2,30}?)\s+-\s+")


@dataclass
class CanalturfPersonneStats:
    historique: List[CourseHistorique]
    nb_courses_pmu: Optional[int] = None
    taux_victoire_pmu: Optional[float] = None
    nb_courses_quinte: Optional[int] = None
    taux_victoire_quinte: Optional[float] = None


def fetch_canalturf_fiche_personne(url_or_id, kind: str = "jockeys") -> CanalturfPersonneStats:
    """kind : 'jockeys' ou 'entraineurs' (détermine juste l'URL si un id nu est passé)."""
    if isinstance(url_or_id, str) and url_or_id.startswith("http"):
        url = url_or_id
    else:
        page = "courses_fiche_jockey.php?idjockey=" if kind == "jockeys" else "courses_fiche_entraineur.php?identraineur="
        url = f"https://www.canalturf.com/{page}{url_or_id}"

    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")

    historique: List[CourseHistorique] = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 3:
            continue
        m_rang = _RANG_RE.match(cells[0].get_text(strip=True))
        m_date = _DATE_RE.search(cells[1].get_text(strip=True))
        if not m_rang or not m_date:
            continue
        jour, mois, annee = m_date.groups()
        date_iso = f"{annee}-{mois}-{jour}"
        detail_text = cells[2].get_text(" ", strip=True)
        m_hippo = _HIPPO_RE.search(detail_text)
        hippodrome = m_hippo.group(1).strip() if m_hippo else ""
        historique.append(CourseHistorique(date=date_iso, hippodrome=hippodrome,
                                            partants=0, rang=int(m_rang.group(1))))

    stats = CanalturfPersonneStats(historique=historique)
    text = soup.get_text("\n", strip=True)

    m_pmu = re.search(r"Nombre de courses PMU\s*:\s*(\d+)", text)
    if m_pmu:
        stats.nb_courses_pmu = int(m_pmu.group(1))
        m_1er = re.search(r"1er[^%]{0,20}?([\d,.]+)\s*%", text)
        if m_1er:
            stats.taux_victoire_pmu = float(m_1er.group(1).replace(",", "."))

    m_q = re.search(r"Nombre de courses Quinté\+?\s*:\s*(\d+)", text)
    if m_q:
        stats.nb_courses_quinte = int(m_q.group(1))
        section_q = text[m_q.start():m_q.start() + 500]
        m_1er_q = re.search(r"1er[^%]{0,20}?([\d,.]+)\s*%", section_q)
        if m_1er_q:
            stats.taux_victoire_quinte = float(m_1er_q.group(1).replace(",", "."))

    if not historique:
        logger.warning("Aucune monte extraite pour %s -- structure de page probablement différente de celle vérifiée le 04/08/2026.", url)
    return stats
