"""
turfoo_fiche_personne.py -- Fiches jockeys/entraîneurs (turfoo.fr/fiches/
jockeys/{slug}/, /fiches/entraineurs/{slug}/).

Réécrit le 06/08/2026 après un vrai échec en production (0/14 chevaux
avec driver_stats sur une course réelle) : l'ancien `_ENTRY_RE` attendait
un format texte libre ("06 AOUT 2026-CABOURG - PRIX... 14 PARTANTS") qui
ne correspond à RIEN sur la vraie page -- déjà signalé comme non vérifié
dans une version précédente de ce fichier, confirmé aujourd'hui.

Vraie structure (vérifiée sur turfoo.fr/fiches/jockeys/lagadeuc-f/,
06/08/2026) : un tableau "Hippodrome | Date | Cheval | Dist | Cote |
Place", date au format DD/MM/YY (année sur 2 chiffres), avec des lignes
supplémentaires "Déferré : ..." / "Quinté : X" intercalées entre les
vraies lignes de monte -- pas des montes séparées, à ignorer. Place est
soit un nombre, soit "DAI" (distancé) ou vide (non classé mais arrivé).
Pas de colonne "nombre de partants" sur cette page (contrairement à
l'ancienne hypothèse) -- laissé à 0 (inconnu), non utilisé par
fenetres_victoires de toute façon.

Colonne "Cheval" (index 2) extraite depuis le 03/09/2026 pour construire
un vrai tandem_driver_cheval (jockey/driver + CE cheval précis, historique
complet plutôt que les seules "dernières perfs" limitées de CanalTurf).
Risque plus faible qu'une extraction neuve : la structure de ligne
(6 cellules, index 5 = Place) est déjà validée par le code existant --
lire l'index 2 en plus suit la même indexation, ce n'est pas une nouvelle
hypothèse de structure. Reste néanmoins NON vérifié en conditions
réelles sur cette colonne précise (contrairement à hippodrome/date/place)
-- à confirmer dès qu'un vrai run sur Render le permettra.
"""
from __future__ import annotations
import re
import logging
from dataclasses import dataclass
from datetime import date as date_cls, datetime, timedelta
from typing import List, Optional
from bs4 import BeautifulSoup

from app.scraping.base import fetch_html

logger = logging.getLogger("vantage.scraping.turfoo_fiche_personne")

_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{2})$")


@dataclass
class CourseHistorique:
    date: str
    hippodrome: str
    partants: int
    rang: Optional[int]  # None si non retrouvé dans le mini-tableau
    # Colonne "Cheval" de la table (Hippodrome|Date|Cheval|Dist|Cote|Place)
    # -- présente sur la page et déjà comprise dans l'indexation de
    # colonnes déjà validée (cells[5]=Place fonctionne, donc cells[2]=
    # Cheval suit la même structure de ligne, pas une nouvelle
    # hypothèse) mais jamais extraite jusqu'au 03/09/2026. Optionnelle
    # pour ne pas casser un appelant qui construirait cet objet sans elle.
    cheval: Optional[str] = None


def _parse_date_2digits(txt: str) -> Optional[str]:
    m = _DATE_RE.match(txt.strip())
    if not m:
        return None
    jour, mois, annee2 = m.groups()
    annee = 2000 + int(annee2)  # hypothèse raisonnable jusqu'en 2099
    try:
        return date_cls(annee, int(mois), int(jour)).isoformat()
    except ValueError:
        return None


def fetch_historique_personne(url_or_slug: str, kind: str, nom_personne: str = "") -> List[CourseHistorique]:
    """kind: 'jockeys' ou 'entraineurs'. nom_personne n'est plus utilisé
    (gardé pour compatibilité de signature avec les appelants existants)
    -- la vraie table n'a pas besoin de rechercher le nom, chaque ligne
    EST déjà la monte de cette personne."""
    url = url_or_slug if url_or_slug.startswith("http") else f"https://www.turfoo.fr/fiches/{kind}/{url_or_slug}/"
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")

    table = None
    for t in soup.find_all("table"):
        header = t.find("tr")
        if header and "hippodrome" in header.get_text(" ", strip=True).lower():
            table = t
            break
    if table is None:
        logger.warning("Table historique introuvable sur %s (structure différente de celle vérifiée le 06/08/2026).", url)
        return []

    historique: List[CourseHistorique] = []
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all(["td", "th"])
        if len(cells) < 6:
            continue  # ligne "Déferré :"/"Quinté :" intercalée, pas une monte
        hippodrome = cells[0].get_text(strip=True)
        date_iso = _parse_date_2digits(cells[1].get_text(strip=True))
        if not date_iso or not hippodrome:
            continue  # confirme qu'on est bien sur une ligne de monte, pas une ligne de métadonnées
        cheval_nom = cells[2].get_text(strip=True) if len(cells) > 2 else None
        place_txt = cells[5].get_text(strip=True)
        rang = int(place_txt) if place_txt.isdigit() else None
        historique.append(CourseHistorique(date=date_iso, hippodrome=hippodrome, partants=0, rang=rang,
                                            cheval=cheval_nom or None))

    if not historique:
        logger.warning("0 monte extraite sur %s malgré une table trouvée -- structure de ligne différente de celle vérifiée.", url)
    return historique


def fenetres_victoires(historique: List[CourseHistorique], date_reference: str,
                        fenetres_jours: List[int]) -> List[dict]:
    """Retourne [{jours, victoires, courses}, ...] au format DriverTrainerWindow.
    N'inclut une fenêtre que si l'historique récupéré remonte RÉELLEMENT
    au moins jusqu'au début de cette fenêtre -- sinon le comptage serait
    une sous-estimation silencieuse (ex. page ne montrant que les 10
    dernières montes = ~1-2 semaines pour un jockey actif ; répondre quand
    même pour la fenêtre 60j donnerait un "0 victoire sur 60 jours" qui
    n'a jamais été vérifié au-delà de la 2e semaine). Corrigé le
    04/08/2026 -- s'applique aussi bien à la source Turfoo qu'à CanalTurf."""
    try:
        d_ref = datetime.fromisoformat(date_reference).date()
    except ValueError:
        return []

    dates_valides = [datetime.fromisoformat(h.date).date() for h in historique if h.date]
    plus_ancienne = min(dates_valides) if dates_valides else None

    resultats = []
    for jours in fenetres_jours:
        seuil = d_ref - timedelta(days=jours)
        if plus_ancienne is None or plus_ancienne > seuil:
            continue  # couverture insuffisante pour cette fenêtre -- on omet plutôt que d'inventer
        dans_fenetre = [h for h in historique
                        if h.date and seuil <= datetime.fromisoformat(h.date).date() < d_ref]  # v1.29.40 : jour J exclu
        victoires = sum(1 for h in dans_fenetre if h.rang == 1)
        resultats.append({"jours": jours, "victoires": victoires, "courses": len(dans_fenetre)})
    return resultats
