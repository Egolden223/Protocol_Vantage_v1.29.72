"""
pmu_corpus_analyse.py -- Analyses complémentaires bâties sur le corpus
open-pmu-api déjà mis en cache par supra_phase2.py (une seule
récupération par hippodrome, réutilisée pour plusieurs analyses).
Ajouté le 06/09/2026, suite à une revue du texte source + connaissances
générales de handicapping + recherche web (biais de corde, cf.
PASSATION pour les sources : Turf.bzh, iturf.fr, Boturfers -- pratique
reconnue du milieu, pas une intuition personnelle).

Toutes les fonctions de ce module retournent un résultat neutre/vide en
cas d'échec ou si supra_phase2.ACTIVER_SUPRA_PHASE2_REEL (supra_phase2.py) est False
-- aucune ne doit jamais faire échouer le pipeline principal.

NOUVEAU CATALOGUE, PAS DANS LE TEXTE SOURCE : le biais de corde n'est
PAS un signal du PROTOCOL_VANTAGE_MASTER -- c'est un ajout proposé par
Claude à la demande explicite de Golden ("selon tes propres
connaissances"), pas une implémentation d'un signal du document. Il
alimente qual.bonus_corde_empirique (nouveau champ), séparé des bonus
catalogue B/M/GAMMA existants pour ne pas se faire passer pour un
signal du protocole d'origine.
"""
from __future__ import annotations
import logging
import os
from typing import List, Optional, Tuple, Dict
from collections import defaultdict

from app.models import RaceContext, Cheval
from app.engine.common import disc_bucket
from app.engine import supra_phase2
from app.engine.supra_phase2 import _normalise_nom, _DISCIPLINE_API_VERS_BUCKET

logger = logging.getLogger("vantage.engine.pmu_corpus_analyse")

_TOLERANCE_DISTANCE_M = 200
_MIN_COURSES_BIAIS_CORDE = 30  # en dessous, le taux par corde est trop bruité pour être exploitable


def _corde_v2_actif() -> bool:
    return os.environ.get("VANTAGE_CORDE_V2", "0").strip().lower() in ("1", "true", "oui", "on")


def _filtrer_courses_pertinentes(race: RaceContext, tolerance: Optional[int] = _TOLERANCE_DISTANCE_M, courses: Optional[List] = None) -> List:
    if courses is None:
        if not supra_phase2.ACTIVER_SUPRA_PHASE2_REEL:
            return []
        try:
            courses = supra_phase2.get_courses_historiques(race.hippodrome)
        except Exception as e:
            logger.warning("pmu_corpus_analyse : échec récupération corpus pour %s : %s", race.hippodrome, e)
            return []
    bucket_ref = disc_bucket(race.discipline)
    return [c for c in courses
            if _DISCIPLINE_API_VERS_BUCKET.get((c.type_discipline or "").strip().lower()) == bucket_ref
            and (tolerance is None or (c.distance_m is not None and abs(c.distance_m - race.distance_m) <= tolerance))]


def compute_biais_corde(race: RaceContext) -> Dict[int, float]:
    """Taux de victoire empirique par numéro de corde, sur les courses du même hippodrome x discipline x distance (± 200 m) déjà en
    cache. Retourne {} si le corpus est trop petit (< 30 courses) ou si Phase 2 réel est désactivé/en échec.

    v1.29.63 (VANTAGE_CORDE_V2=1, défaut OFF) : taux de TOP 5 par corde (3 fois plus d'événements que la victoire), rétréci vers la
    moyenne (K = 20), filtre assoupli par paliers (distance ± 200 m, puis ± 400 m, puis discipline seule) jusqu'à 30 courses.
    Rejeu 55 courses : aucun effet de la place de départ détectable après contrôle du marché (IC95 % incluant 0) → à valider sur un lot."""
    if _corde_v2_actif():
        return _biais_corde_v2(race)
    courses = _filtrer_courses_pertinentes(race)
    if len(courses) < _MIN_COURSES_BIAIS_CORDE:
        return {}

    victoires_par_corde: Dict[int, int] = defaultdict(int)
    courses_par_corde: Dict[int, int] = defaultdict(int)
    for course in courses:
        if not course.ordre_arrivee:
            continue
        gagnant_numero = course.ordre_arrivee[0]
        for numero, cheval_api in course.chevaux_par_numero.items():
            if cheval_api.corde is None:
                continue
            courses_par_corde[cheval_api.corde] += 1
            if numero == gagnant_numero:
                victoires_par_corde[cheval_api.corde] += 1

    return {corde: victoires_par_corde.get(corde, 0) / nb
            for corde, nb in courses_par_corde.items() if nb >= 5}


def _biais_corde_v2(race: RaceContext, courses_source: Optional[List] = None, k_retrecissement: float = 20.0) -> Dict[int, float]:
    for tol in (_TOLERANCE_DISTANCE_M, 2 * _TOLERANCE_DISTANCE_M, None):
        courses = _filtrer_courses_pertinentes(race, tol, courses_source)
        courses = [c for c in courses if c.ordre_arrivee]
        if len(courses) >= _MIN_COURSES_BIAIS_CORDE:
            break
    else:
        return {}
    n_c: Dict[int, int] = defaultdict(int); t5_c: Dict[int, int] = defaultdict(int)
    for course in courses:
        top5 = set(course.ordre_arrivee[:5])
        for numero, ch in course.chevaux_par_numero.items():
            if ch.corde is None:
                continue
            n_c[ch.corde] += 1
            t5_c[ch.corde] += numero in top5
    tot = sum(n_c.values())
    if tot < 100:
        return {}
    p0 = sum(t5_c.values()) / tot
    return {c: (t5_c[c] + k_retrecissement * p0) / (n + k_retrecissement) for c, n in n_c.items() if n >= 5}


def bonus_corde_empirique(cheval: Cheval, race: RaceContext, biais: Dict[int, float]) -> Tuple[float, List[str]]:
    """Compare le taux empirique de la corde du cheval du jour au taux moyen toutes cordes confondues sur le même échantillon.

    v1.29.63 : la clé est la PLACE DE CORDE réelle (`numero_autostart`, alimentée par `placeCorde` de l'API PMU). Avant, le galop
    utilisait `cheval.numero`, qui n'est PAS la corde (identique dans 5 % seulement des partants de plat) → bonus appliqué à la mauvaise
    clé. Sans place de corde connue, aucun bonus (jamais un numéro de cheval pris pour une corde)."""
    numero_ref = cheval.numero_autostart
    if not biais or numero_ref is None or numero_ref not in biais:
        return 0.0, []
    moyenne = sum(biais.values()) / len(biais)
    if moyenne <= 0:
        return 0.0, []
    ecart_relatif = (biais[numero_ref] - moyenne) / moyenne
    seuil, valeur = (0.25, 3.0) if _corde_v2_actif() else (0.30, 5.0)
    if ecart_relatif >= seuil:
        return valeur, ["BIAIS_CORDE_FAVORABLE"]
    if ecart_relatif <= -seuil:
        return -valeur, ["BIAIS_CORDE_DEFAVORABLE"]
    return 0.0, []


def diagnostic_race(race: RaceContext) -> Dict[str, object]:
    """État des données de corde / corpus pour CETTE course, SANS appel réseau (cache disque uniquement)."""
    out: Dict[str, object] = {"corpus_courses_hippodrome": None, "corpus_courses_similaires": 0, "biais_corde_seuil": _MIN_COURSES_BIAIS_CORDE,
                              "biais_corde_possible": False, "corde_v2": _corde_v2_actif()}
    try:
        from app.scraping.open_pmu_api import _parse_arrivee_course
        raw = supra_phase2._charger_cache(race.hippodrome)
        if raw is None:
            out["corpus_courses_hippodrome"] = 0
            return out
        courses = [c for c in (_parse_arrivee_course(m) for m in raw) if c is not None]
        out["corpus_courses_hippodrome"] = len(courses)
        sim = _filtrer_courses_pertinentes(race, _TOLERANCE_DISTANCE_M, courses)
        out["corpus_courses_similaires"] = len(sim)
        out["biais_corde_possible"] = len(sim) >= _MIN_COURSES_BIAIS_CORDE
    except Exception as e:  # noqa: BLE001
        out["erreur"] = str(e)[:80]
    return out


def h2h_hippodrome_scope(race: RaceContext, nom_cheval_a: str, nom_cheval_b: str) -> Optional[Tuple[int, int, int]]:
    """Confrontations directes entre 2 chevaux, cherchées UNIQUEMENT
    dans les courses déjà en cache pour l'hippodrome du jour -- PAS une
    recherche exhaustive tous hippodromes confondus (open-pmu-api ne
    permet pas de chercher par nom de cheval directement ; il faudrait
    interroger chaque hippodrome de France pour une vraie exhaustivité,
    ce qui n'est pas raisonnable en direct). Résultat donc probablement
    incomplet -- de vraies confrontations ailleurs qu'à cet hippodrome
    ne seront jamais vues par cette fonction. Retourne (victoires_a,
    victoires_b, nb_confrontations) ou None si Phase 2 réel désactivé/
    en échec."""
    if not supra_phase2.ACTIVER_SUPRA_PHASE2_REEL:
        return None
    try:
        courses = supra_phase2.get_courses_historiques(race.hippodrome)
    except Exception as e:
        logger.warning("h2h_hippodrome_scope : échec récupération corpus pour %s : %s", race.hippodrome, e)
        return None

    nom_a, nom_b = _normalise_nom(nom_cheval_a), _normalise_nom(nom_cheval_b)
    victoires_a = victoires_b = confrontations = 0
    for course in courses:
        numeros_par_nom = {_normalise_nom(c.nom_cheval): n for n, c in course.chevaux_par_numero.items()}
        if nom_a not in numeros_par_nom or nom_b not in numeros_par_nom or not course.ordre_arrivee:
            continue
        rang_a = _rang_dans_arrivee(course.ordre_arrivee, numeros_par_nom[nom_a])
        rang_b = _rang_dans_arrivee(course.ordre_arrivee, numeros_par_nom[nom_b])
        if rang_a is None or rang_b is None:
            continue
        confrontations += 1
        if rang_a < rang_b:
            victoires_a += 1
        elif rang_b < rang_a:
            victoires_b += 1
    if confrontations == 0:
        return None
    return victoires_a, victoires_b, confrontations


def populate_confrontations_directes(cheval: Cheval, champ: List[Cheval], race: RaceContext) -> List[str]:
    """Peuple cheval.confrontations_directes (Bloc N, jamais alimenté par
    aucun scraper jusqu'ici -- module_n_h2h tournait donc systématiquement
    en repli tandem ou à 0). Un confrontation dict par course passée
    PARTAGÉE avec un autre partant du jour, À CET HIPPODROME UNIQUEMENT
    (même réserve d'exhaustivité que h2h_hippodrome_scope -- ne couvre
    pas les confrontations ailleurs). Format attendu par module_n_h2h
    (modules_ap.py) : {"rang": <rang du cheval du jour dans cette
    course-là>, "weight": 1.0}."""
    if not supra_phase2.ACTIVER_SUPRA_PHASE2_REEL or cheval.confrontations_directes:
        return []  # ne jamais écraser une éventuelle donnée déjà posée par ailleurs
    try:
        courses = supra_phase2.get_courses_historiques(race.hippodrome)
    except Exception as e:
        logger.warning("populate_confrontations_directes : échec récupération corpus pour %s : %s",
                        race.hippodrome, e)
        return []

    nom_cheval = _normalise_nom(cheval.nom)
    noms_adversaires = {_normalise_nom(c.nom) for c in champ if c.numero != cheval.numero}
    confrontations = []
    for course in courses:
        numeros_par_nom = {_normalise_nom(c.nom_cheval): n for n, c in course.chevaux_par_numero.items()}
        if nom_cheval not in numeros_par_nom or not course.ordre_arrivee:
            continue
        if not (noms_adversaires & numeros_par_nom.keys()):
            continue  # aucun partant du jour présent dans cette course passée
        rang = _rang_dans_arrivee(course.ordre_arrivee, numeros_par_nom[nom_cheval])
        if rang is not None:
            confrontations.append({"rang": rang + 1, "weight": 1.0})  # +1 : index0 -> rang1

    if confrontations:
        cheval.confrontations_directes = confrontations
        return ["H2H_REEL_HIPPODROME_SCOPE"]
    return []


def _rang_dans_arrivee(ordre_arrivee: List[int], numero: int) -> Optional[int]:
    try:
        return ordre_arrivee.index(numero)
    except ValueError:
        return None  # non classé ou hors de la liste d'arrivée fournie par l'API
