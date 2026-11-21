"""
open_pmu_api.py -- Client pour open-pmu-api (github.com/nanaelie/open-pmu-api),
une API REST tierce, gratuite et open source (non affiliée au PMU), qui
donne les arrivées de courses PMU du 22/01/2004 à aujourd'hui, avec le
détail par cheval (musique, cotes, gains, corde, jockey, entraîneur).

Ajouté le 05/09/2026 pour tenter de débloquer SUPRA Phase 2 (SCORE_SIM /
PROFIL_GAGNANT_TYPE), qui manquait jusqu'ici d'un corpus de courses
passées -- cf. supra_phase2.py pour l'utilisation.

STATUT DE VÉRIFICATION -- IMPORTANT, à lire avant de faire confiance à ce
module en production :
  - Le endpoint `?date=MM/DD/YYYY` (format US) a été testé en direct le 05/09/2026 et
    a renvoyé une vraie course PMU complète et cohérente (Prix de l'Île
    de la Cité, Paris-Longchamp, 06/07/2026).
  - Les endpoints `?hippo=...` et `?prix=...` n'ont PAS pu être vérifiés
    : dans l'environnement de développement utilisé pour écrire ce
    module, les appels suivants ont tous renvoyé la MÊME réponse que le
    tout premier appel, quel que soit le paramètre (y compris une valeur
    absurde comme prix=INEXISTANT_TEST_12345) -- symptôme d'un cache
    agressif côté outil de récupération web utilisé pour tester, PAS une
    conclusion sur le comportement réel de l'API. Le filtrage par
    hippodrome n'a donc PAS pu être confirmé.
  - Pagination, limite de débit (rate limit) et volume de réponse pour
    un hippodrome couvrant 2004-2026 : totalement inconnus. Un hippodrome
    actif comme Vincennes a probablement des dizaines de milliers de
    courses sur cette période -- si l'API renvoie tout sans pagination,
    une requête par hippodrome pourrait être extrêmement lourde ou
    échouer purement et simplement.
  - Le corps de la fonction ci-dessous est donc écrit défensivement
    (timeout, retries, cap dur sur le nombre de résultats exploités,
    dégradation silencieuse vers [] en cas d'échec) mais DOIT être
    validé par un vrai test réseau (depuis Render ou le poste de Golden,
    qui ont un accès réseau normal) avant d'être activé en production.
    Voir supra_phase2.py::ACTIVER_SUPRA_PHASE2_REEL (désactivé par
    défaut tant que cette validation n'est pas faite).
  - Source tierce non officielle, pas de garantie de disponibilité
    continue (hébergée sur Vercel par un développeur indépendant) --
    garder impérativement un chemin de repli (l'heuristique existante),
    jamais une dépendance dure.
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import re

from app.scraping.base import fetch_html

logger = logging.getLogger("vantage.scraping.open_pmu_api")

_BASE_URL = "https://open-pmu-api.vercel.app/api/arrivees"

# Cap dur sur le nombre de courses exploitées par appel -- garde-fou tant
# que le volume réel d'une réponse "par hippodrome" n'est pas mesuré.
MAX_COURSES_PAR_APPEL = 500


@dataclass
class ArriveeChevalOPA:
    numero: int
    nom_cheval: str
    sexe: Optional[str] = None
    annee_de_naissance: Optional[int] = None
    nom_jockey: Optional[str] = None
    nom_entraineur: Optional[str] = None
    musique: Optional[str] = None
    cotes: List[str] = field(default_factory=list)  # [cote_matin, cote_intermediaire, cote_finale] à confirmer
    gains: Optional[int] = None
    corde: Optional[int] = None
    discipline: Optional[str] = None
    distance_m: Optional[int] = None


@dataclass
class ArriveeCourseOPA:
    type_discipline: Optional[str]        # "Plat", "Trot", etc. -- champ "type" de l'API
    montant_eur: Optional[int]            # champ "montant" -- allocation, à confirmer (centimes ou euros ?)
    distance_m: Optional[int]
    prix: Optional[str]
    hippodrome: Optional[str]             # champ "lieu"
    heure_depart: Optional[str]
    details: Optional[str]                # texte libre : corde, catégorie, conditions d'âge/sexe
    partants: Optional[int]
    non_partants: List[int]
    ordre_arrivee: List[int]              # champ "arrivee" -- numéros dans l'ordre, PAS forcément tous les partants
    reunion_course: Optional[str]         # champ "r/c", ex. "R1/C3"
    date_iso: Optional[str]
    chevaux_par_numero: Dict[int, ArriveeChevalOPA] = field(default_factory=dict)


def _parse_arrivee_course(raw: dict) -> Optional[ArriveeCourseOPA]:
    try:
        chevaux: Dict[int, ArriveeChevalOPA] = {}
        for numero_str, detail in (raw.get("arrivee_details") or {}).items():
            try:
                numero = int(numero_str)
            except (TypeError, ValueError):
                continue
            chevaux[numero] = ArriveeChevalOPA(
                numero=numero,
                nom_cheval=detail.get("nom_cheval", ""),
                sexe=detail.get("sexe"),
                annee_de_naissance=detail.get("annee_de_naissance"),
                nom_jockey=detail.get("nom_jockey"),
                nom_entraineur=detail.get("nom_entraineur"),
                musique=detail.get("musique"),
                # Les sources historiques peuvent renvoyer None ou des
                # chaînes vides : les retirer à l'entrée évite des crashes
                # dans les consommateurs numériques.
                cotes=[v for v in (detail.get("cotes") or []) if v not in (None, "")],
                gains=detail.get("gains"),
                corde=detail.get("corde"),
                discipline=detail.get("discipline"),
                distance_m=detail.get("distance"),
            )
        return ArriveeCourseOPA(
            type_discipline=raw.get("type"),
            montant_eur=raw.get("montant"),
            distance_m=raw.get("distance"),
            prix=raw.get("prix"),
            hippodrome=raw.get("lieu"),
            heure_depart=raw.get("heure_depart"),
            details=raw.get("details"),
            partants=raw.get("partants"),
            non_partants=raw.get("non_partants") or [],
            ordre_arrivee=raw.get("arrivee") or [],
            reunion_course=raw.get("r/c"),
            date_iso=raw.get("date"),
            chevaux_par_numero=chevaux,
        )
    except Exception as e:
        logger.warning("Ligne arrivée open-pmu-api ignorée (structure inattendue) : %s", e)
        return None



def date_to_opa_format(iso_or_fr: str) -> str:
    """Convertit YYYY-MM-DD ou DD/MM/YYYY vers MM/DD/YYYY (API open-pmu)."""
    s = (iso_or_fr or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        y, m, d = s.split("-")
        return f"{m}/{d}/{y}"
    if re.match(r"^\d{2}/\d{2}/\d{4}$", s):
        # assume DD/MM/YYYY from our UI → flip
        d, m, y = s.split("/")
        return f"{m}/{d}/{y}"
    return s  # already MM/DD or unknown


def fetch_arrivees_raw(date: Optional[str] = None, hippo: Optional[str] = None,
                        prix: Optional[str] = None, timeout: int = 15) -> List[dict]:
    """Comme fetch_arrivees, mais retourne les dicts JSON bruts (avant
    conversion en ArriveeCourseOPA) -- utilisé par supra_phase2.py pour
    mettre en cache sur disque sans dépendre de la (dé)sérialisation des
    dataclasses. fetch_arrivees() est une fine couche au-dessus de
    celle-ci."""
    if sum(p is not None for p in (date, hippo, prix)) != 1:
        raise ValueError("fetch_arrivees_raw: fournir exactement un de date/hippo/prix")

    params = {"date": date_to_opa_format(date)} if date else {"hippo": hippo} if hippo else {"prix": prix}
    key, value = next(iter(params.items()))
    url = f"{_BASE_URL}?{key}={value}"

    try:
        raw_text = fetch_html(url, timeout=timeout, retries=1, extra_headers={
            "Accept": "application/json",
            "Referer": "https://open-pmu-api.vercel.app/",
        })
        data = json.loads(raw_text)
    except Exception as e:
        logger.warning("open-pmu-api indisponible ou réponse invalide (%s=%s) : %s", key, value, e)
        return []

    if data.get("error"):
        logger.warning("open-pmu-api a renvoyé error=true pour %s=%s : %s", key, value, data)
        return []

    messages = data.get("message") or []
    if len(messages) > MAX_COURSES_PAR_APPEL:
        logger.warning(
            "open-pmu-api : %d courses reçues pour %s=%s, tronqué à %d (MAX_COURSES_PAR_APPEL) -- "
            "le volume réel d'une réponse par hippodrome n'a jamais été mesuré, cf. docstring du module.",
            len(messages), key, value, MAX_COURSES_PAR_APPEL)
        messages = messages[:MAX_COURSES_PAR_APPEL]
    return messages


def fetch_arrivees(date: Optional[str] = None, hippo: Optional[str] = None,
                    prix: Optional[str] = None, timeout: int = 15) -> List[ArriveeCourseOPA]:
    """Interroge open-pmu-api. Exactement un des 3 paramètres doit être
    fourni (comportement de l'API en cas de combinaison non documenté --
    non testé). `date` au format DD/MM/YYYY (convention de l'API, PAS
    ISO). Retourne [] (jamais d'exception propagée) en cas d'échec réseau
    ou de réponse inattendue : cette source est un enrichissement
    optionnel, jamais un point de défaillance dur du pipeline."""
    messages = fetch_arrivees_raw(date=date, hippo=hippo, prix=prix, timeout=timeout)
    return [c for c in (_parse_arrivee_course(m) for m in messages) if c is not None]
