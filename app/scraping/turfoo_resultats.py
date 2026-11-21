"""
turfoo_resultats.py -- Récupère l'arrivée officielle d'une course déjà
courue sur Turfoo.fr. Même structure d'URL que les pronostics, avec
"programmes-courses" remplacé par "resultats-courses".

Réécrit le 05/08/2026 après un vrai échec en production (0 chevaux
extraits sur une course réelle, 19/07/2026 Chantilly C3) : l'ancienne
version supposait les chevaux séparés par "·"/"-"/"–" dans le texte
aplati de la page ("1 6 LUCIA DE BUSSET · 2 3 LIBERTY ZEN · ..."). Vérifié
sur la vraie page : ce format n'existe pas, les entrées se suivent sans
aucun délimiteur ("1 1 MOST GLAMOROUS (USA) 13 15 2 13 WEEMAGATEE ..."),
ce qui faisait échouer le split et renvoyait 0 résultat.

Nouvelle approche, ancrée sur une structure fiable plutôt que sur du
texte aplati : chaque cheval de l'arrivée est un lien vers sa fiche
(/fiches/chevaux/...), précédé de "RANG NUMERO" dans le même bloc.
Turfoo n'affiche que le Top 5 avec nom+lien (le reste est derrière "Voir
plus", non exploité ici -- suffisant pour l'audit Quinté qui se limite
au Top 5).
"""
from __future__ import annotations
import re
import logging
from dataclasses import dataclass
from typing import List, Optional
from bs4 import BeautifulSoup

from app.scraping.base import fetch_html

logger = logging.getLogger("vantage.scraping.turfoo_resultats")


@dataclass
class ArrivalHorse:
    rang: int
    numero: int
    nom: str


def resultats_url_from_pronostics_url(url: str) -> str:
    """Convertit une URL /programmes-courses/.../ en son équivalent
    /resultats-courses/.../ (même chemin réunion/course)."""
    return re.sub(r"/programmes-courses/", "/resultats-courses/", url).split("?")[0].rstrip("/") + "/"


def fetch_arrival(url: str) -> List[ArrivalHorse]:
    """url : une URL /resultats-courses/... (ou /programmes-courses/... ,
    convertie automatiquement). Retourne le Top 5 (généralement) dans
    l'ordre d'arrivée -- ce que Turfoo affiche nommément avec lien fiche."""
    if "/programmes-courses/" in url:
        url = resultats_url_from_pronostics_url(url)

    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")

    marker = soup.find(string=re.compile(r"Arriv[ée]e(?:\s+(?:officielle|provisoire))?", re.I))
    if marker is None:
        raise ValueError(
            f"Aucune arrivée trouvée sur {url} -- la course n'a peut-être pas encore "
            "eu lieu, ou la page a une structure différente (vérifie manuellement)."
        )
    if "provisoire" in marker.lower():
        logger.warning("Seule une arrivée PROVISOIRE a été trouvée pour %s", url)

    arrival: List[ArrivalHorse] = []
    for a in marker.find_all_next("a", href=True):
        if "/fiches/chevaux/" not in a["href"]:
            continue
        nom = a.get_text(strip=True)
        if not nom:
            continue
        container = a.parent
        full_text = container.get_text(" ", strip=True) if container else ""
        prefix = full_text[:-len(nom)].strip() if full_text.endswith(nom) else ""
        m = re.match(r"^(\d+)\s+(\d+)$", prefix)
        if not m:
            # bloc suivant sans "rang numero" en préfixe direct -> on est
            # probablement sortis de la liste d'arrivée (lien annexe
            # ailleurs sur la page, ex. module différent) -- on arrête
            # plutôt que de risquer un faux positif
            if arrival:
                break
            continue
        rang, numero = int(m.group(1)), int(m.group(2))
        arrival.append(ArrivalHorse(rang=rang, numero=numero, nom=nom))
        if len(arrival) >= 16:  # garde-fou, jamais plus de partants qu'un champ complet
            break

    if len(arrival) < 3:
        raise ValueError(f"Arrivée mal reconnue sur {url} (seulement {len(arrival)} chevaux extraits).")

    return arrival
