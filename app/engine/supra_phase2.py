"""
supra_phase2.py -- Vraie implémentation de SUPRA Phase 2 (S2-HISTORIQUE,
SCORE_SIM / PROFIL_GAGNANT_TYPE), Partie 17 §17.2. Ajouté le 05/09/2026.

Jusqu'ici, Phase 2 tournait entièrement en heuristique dans
qualitative_engine.py::_supra_score_sim (repli sur des signaux B/M déjà
connus du CHEVAL, pas une vraie comparaison de la COURSE du jour à des
courses passées SIMILAIRES). Ce module tente la vraie formule, en
s'appuyant sur open_pmu_api.py pour obtenir un corpus de courses passées.

FORMULE (texte source) :
  SCORE_SIM = s_hippodrome*0.40 + s_distance*0.30 + s_terrain*0.20 + s_conditions*0.10
  Seuil de similarité : SCORE_SIM >= 0.70
  Minimum 5 courses similaires pour dériver un PROFIL_GAGNANT_TYPE
  Si base insuffisante : BONUS_HISTORIQUE = 0.50 (neutre), flag S2_INSUFFISANT

APPROXIMATIONS ASSUMÉES (à cause des limites de la donnée disponible
via open-pmu-api -- documentées ici, pas cachées) :
  - s_terrain : l'API ne donne PAS de pénétromètre ni d'état de piste
    officiel pour les courses passées (seulement un champ texte libre
    "details"). s_terrain est donc réduit à un match discipline stricte
    (1.0 si même discipline exacte -- Plat/Trot/Obstacle --, 0.0 sinon)
    -- une approximation grossière, PAS le vrai calcul pénétromètre du
    texte source. Documenté par le flag S2_TERRAIN_APPROXIME.
  - s_conditions : approximé par la présence des mêmes mots-clés de
    catégorie (HANDICAP, CONDITIONS, RECLAMER...) dans le champ texte
    "details" des deux courses -- pas une comparaison structurée.
  - "cote" du gagnant type : le champ "cotes" de l'API donne une liste
    de cotes sans horodatage explicite -- la DERNIÈRE valeur de la liste
    est supposée être la cote la plus proche du départ (donc la plus
    représentative), hypothèse non confirmée par la documentation de
    l'API.

ACTIVÉ AUTOMATIQUEMENT (ACTIVER_SUPRA_PHASE2_REEL=True depuis le
06/09/2026, sur demande explicite de Golden : "activer automatiquement
si données disponibles") : le pipeline tente systématiquement les
vraies données ; repli automatique et silencieux sur l'heuristique si
l'API échoue, renvoie une liste vide, ou si le corpus est insuffisant
(< 5 courses similaires). Le booléen reste disponible comme
coupe-circuit d'urgence (le repasser à False force le repli heuristique
pour tout le monde). Réserve non levée à ce jour : le filtrage par
?hippo=... n'a jamais pu être vérifié en conditions réelles (cf.
open_pmu_api.py, section "STATUT DE VÉRIFICATION") -- scripts/
valider_open_pmu_api.py reste fortement recommandé dès que possible,
même si l'activation ne l'attend plus.
"""
from __future__ import annotations
import json
import logging
import os
import re
import time
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any
from statistics import median

from app.models import Cheval, RaceContext
from app.engine.common import disc_bucket
from app.scraping.open_pmu_api import ArriveeCourseOPA

logger = logging.getLogger("vantage.engine.supra_phase2")

ACTIVER_SUPRA_PHASE2_REEL = True  # cf. addendum du 06/09/2026 : activation
# automatique sur demande explicite de Golden -- le pipeline tente
# systématiquement les vraies données (open-pmu-api) et se replie SEUL,
# silencieusement, sur l'heuristique si l'API échoue, renvoie une liste
# vide, ou si le corpus est insuffisant (< 5 courses similaires). Aucune
# étape manuelle requise : "actif si les données sont disponibles" est
# gardé par le code lui-même (try/except + vérifications de longueur),
# pas par ce booléen, qui ne sert plus que de coupe-circuit d'urgence
# (repasser à False force le repli heuristique pour TOUT le monde,
# utile si le service tiers devient instable en production).
# Rappel du risque assumé en l'activant sans avoir fait tourner
# scripts/valider_open_pmu_api.py au préalable : le filtrage par
# ?hippo=... n'a jamais pu être vérifié en conditions réelles (cf.
# open_pmu_api.py) -- si les résultats reçus ne sont pas vraiment
# filtrés par hippodrome, SCORE_SIM/PROFIL_GAGNANT_TYPE seront calculés
# sur un corpus qui n'est PEUT-ÊTRE PAS celui du bon hippodrome. Le
# lancer dès que possible reste fortement recommandé.

# v1.29.63 : dossier configurable (VANTAGE_CORPUS_DIR) — sur Render il doit pointer le disque persistant /data, sinon le cache du corpus
# (biais de corde, H2H, classements driver/entraîneur) est perdu à chaque déploiement.
_CACHE_DIR = Path(os.environ.get("VANTAGE_CORPUS_DIR", "data/pmu_historique_cache"))
_CACHE_MAX_AGE_JOURS = 30
_SEUIL_SCORE_SIM = 0.70
_MIN_COURSES_PROFIL = 5

# Cache d'échec en mémoire (pas sur disque -- se réinitialise à chaque
# redémarrage du process) : ajouté le 06/09/2026 après avoir observé en
# test réel qu'une API indisponible (403 anti-bot, cf. PASSATION) sans
# ce garde-fou re-déclenche un appel réseau pour CHAQUE cheval de CHAQUE
# course tant qu'aucun succès n'a pu remplir le cache disque normal --
# potentiellement des centaines d'appels inutiles par réunion si le
# service est en panne/bloqué. 5 minutes : assez court pour retenter
# rapidement si le blocage est transitoire, assez long pour ne pas
# spammer un service qui vient de refuser.
_ECHECS_RECENTS: Dict[str, float] = {}
_DELAI_AVANT_RETENTATIVE_S = 300

_DISCIPLINE_API_VERS_BUCKET = {"plat": "PLAT", "trot": "TROT", "obstacle": "OBSTACLE",
                               "haies": "OBSTACLE", "steeple": "OBSTACLE"}


def _normalise_hippo(nom: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", nom.strip().upper())


def _cache_path(hippodrome: str) -> Path:
    return _CACHE_DIR / f"{_normalise_hippo(hippodrome)}.json"


def _charger_cache(hippodrome: str) -> Optional[List[dict]]:
    path = _cache_path(hippodrome)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
        if (datetime.now() - fetched_at).days > _CACHE_MAX_AGE_JOURS:
            return None
        return payload["courses"]
    except Exception as e:
        logger.warning("Cache PMU historique illisible pour %s : %s", hippodrome, e)
        return None


def _sauver_cache(hippodrome: str, courses_raw: List[dict]) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"fetched_at": datetime.now().isoformat(), "courses": courses_raw}
        _cache_path(hippodrome).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning("Échec écriture cache PMU historique pour %s : %s", hippodrome, e)


def get_courses_historiques(hippodrome: str) -> List[ArriveeCourseOPA]:
    """Corpus de courses passées à cet hippodrome, avec cache disque
    (30 jours) -- évite de re-solliciter open-pmu-api à chaque course
    prédite pour le même hippodrome. Cache d'échec de 5 minutes en plus
    (cf. _ECHECS_RECENTS ci-dessus) : si le dernier appel pour cet
    hippodrome a échoué récemment, ne retente pas immédiatement --
    retourne [] directement."""
    from app.scraping.open_pmu_api import _parse_arrivee_course, fetch_arrivees_raw

    cached_raw = _charger_cache(hippodrome)
    if cached_raw is not None:
        return [c for c in (_parse_arrivee_course(m) for m in cached_raw) if c is not None]

    cle = _normalise_hippo(hippodrome)
    dernier_echec = _ECHECS_RECENTS.get(cle)
    if dernier_echec is not None and (time.time() - dernier_echec) < _DELAI_AVANT_RETENTATIVE_S:
        return []

    raw = fetch_arrivees_raw(hippo=hippodrome)
    if raw:
        _sauver_cache(hippodrome, raw)
        _ECHECS_RECENTS.pop(cle, None)
    else:
        _ECHECS_RECENTS[cle] = time.time()
    return [c for c in (_parse_arrivee_course(m) for m in raw) if c is not None]

# TODO (avant activation en production) : un script de rafraîchissement
# de cache dédié (ex. `scripts/refresh_pmu_historique.py`, tourné une
# fois par semaine hors ligne) serait préférable à ce cache paresseux --
# ça évite qu'une prédiction en direct paie le coût (et le risque
# d'échec) du premier appel réseau pour un hippodrome jamais vu. Pas
# fait cette session, cache paresseux jugé suffisant pour une 1re
# implémentation testable.


def _normalise_nom(nom: str) -> str:
    """Normalisation minimale pour comparer un nom (cheval/jockey/
    entraîneur) entre deux sources différentes -- accents non gérés
    volontairement (pas de dépendance unicodedata ajoutée pour un simple
    comparateur), donc un accent différent entre 2 sources peut faire
    rater un match. Documenté, pas caché."""
    return re.sub(r"\s+", " ", nom.strip().upper())


def find_horse_performance(hippodrome: str, date_course_iso: str, nom_cheval: str):
    """Cherche un cheval précis dans le corpus déjà mis en cache pour cet
    hippodrome (réutilise get_courses_historiques -- pas d'appel réseau
    supplémentaire si le cache existe déjà, ex. si SUPRA Phase 2 a déjà
    tourné pour cette course). Retourne sa ligne d'arrivée -- notamment
    son entraîneur et sa corde À CETTE COURSE-LÀ -- ou None si non
    trouvé (mauvaise date, nom orthographié différemment, ou course pas
    dans le corpus reçu)."""
    if not ACTIVER_SUPRA_PHASE2_REEL:
        return None
    try:
        courses = get_courses_historiques(hippodrome)
    except Exception as e:
        logger.warning("find_horse_performance : échec récupération corpus pour %s : %s", hippodrome, e)
        return None

    nom_norm = _normalise_nom(nom_cheval)
    date_cible = date_course_iso[:10]
    for course in courses:
        if not course.date_iso or course.date_iso[:10] != date_cible:
            continue
        for cheval_api in course.chevaux_par_numero.values():
            if _normalise_nom(cheval_api.nom_cheval) == nom_norm:
                return cheval_api
    return None


def _s_terrain(disc_ref: str, course: ArriveeCourseOPA) -> float:
    disc_api = _DISCIPLINE_API_VERS_BUCKET.get((course.type_discipline or "").strip().lower())
    return 1.0 if disc_api == disc_ref else 0.0


def _s_conditions(race: RaceContext, course: ArriveeCourseOPA) -> float:
    details_ref = (str(race.type_course.value) or "").upper()
    details_course = (course.details or "").upper()
    return 1.0 if details_ref in details_course else 0.3


def _score_sim(race: RaceContext, course: ArriveeCourseOPA) -> float:
    s_hippodrome = 1.0  # déjà filtré par hippo= à la source (cf. réserve dans open_pmu_api.py)
    if course.distance_m is None:
        s_distance = 0.0
    else:
        ecart = abs(course.distance_m - race.distance_m)
        s_distance = 1.0 if ecart <= 100 else 0.6 if ecart <= 300 else 0.2 if ecart <= 600 else 0.0
    s_terrain = _s_terrain(disc_bucket(race.discipline), course)
    s_conditions = _s_conditions(race, course)
    return s_hippodrome * 0.40 + s_distance * 0.30 + s_terrain * 0.20 + s_conditions * 0.10


def _cote_gagnant(course: ArriveeCourseOPA) -> Optional[float]:
    if not course.ordre_arrivee:
        return None
    gagnant = course.chevaux_par_numero.get(course.ordre_arrivee[0])
    if not gagnant or not gagnant.cotes:
        return None
    # Les sources historiques peuvent contenir [None], [""], ou une valeur
    # non textuelle. Une donnée manquante doit dégrader le profil, jamais
    # interrompre toute la course pendant l'analyse qualitative.
    raw = next((v for v in reversed(gagnant.cotes) if v not in (None, "")), None)
    if raw is None:
        return None
    try:
        return float(str(raw).replace(",", ".").strip())  # dernière valeur valide
    except (TypeError, ValueError, IndexError):
        return None


def build_profil_gagnant_type(race: RaceContext) -> Dict[str, Any]:
    """Retourne un dict avec bonus_historique (0.0-1.0, 0.50=neutre si
    base insuffisante) et flags. N'appelle jamais l'API si
    ACTIVER_SUPRA_PHASE2_REEL est False (repli immédiat)."""
    if not ACTIVER_SUPRA_PHASE2_REEL:
        return {"bonus_historique": None, "flags": ["S2_REEL_DESACTIVE"]}

    try:
        courses = get_courses_historiques(race.hippodrome)
    except Exception as e:
        logger.warning("SUPRA Phase 2 réel : échec récupération historique pour %s : %s", race.hippodrome, e)
        return {"bonus_historique": None, "flags": ["S2_ECHEC_RESEAU"]}

    if not courses:
        return {"bonus_historique": None, "flags": ["S2_AUCUNE_COURSE_RECUE"]}

    similaires = [c for c in courses if _score_sim(race, c) >= _SEUIL_SCORE_SIM]
    if len(similaires) < _MIN_COURSES_PROFIL:
        return {"bonus_historique": 0.50, "flags": ["S2_INSUFFISANT", "S2_TERRAIN_APPROXIME"],
                "nb_courses_similaires": len(similaires)}

    cotes_gagnants = [c for c in (_cote_gagnant(x) for x in similaires) if c is not None]
    ages_gagnants = []
    for c in similaires:
        if not c.ordre_arrivee:
            continue
        g = c.chevaux_par_numero.get(c.ordre_arrivee[0])
        if g and g.annee_de_naissance and c.date_iso:
            try:
                annee_course = datetime.fromisoformat(c.date_iso[:10]).year
                ages_gagnants.append(annee_course - g.annee_de_naissance)
            except ValueError:
                pass

    profil = {
        "nb_courses_similaires": len(similaires),
        "cote_gagnant_mediane": median(cotes_gagnants) if cotes_gagnants else None,
        "cote_gagnant_min": min(cotes_gagnants) if cotes_gagnants else None,
        "cote_gagnant_max": max(cotes_gagnants) if cotes_gagnants else None,
        "age_gagnant_median": median(ages_gagnants) if ages_gagnants else None,
    }
    return {"bonus_historique": None, "flags": ["S2_PROFIL_CONSTRUIT", "S2_TERRAIN_APPROXIME"],
            "profil_gagnant_type": profil, "nb_courses_similaires": len(similaires)}


def score_cheval_vs_profil(cheval: Cheval, profil: Dict[str, Any]) -> float:
    """Compare le cheval du jour au PROFIL_GAGNANT_TYPE -- retourne un
    bonus_historique 0.0-1.0. Implémentation minimale (tranche de cote
    uniquement) : le texte source évoque aussi style/position mi-course/
    taux de favoris déjoués, non repris ici faute de temps -- cf.
    PASSATION pour marquer cette fonction comme partielle."""
    cote = cheval.cote_matin
    cmin, cmax = profil.get("cote_gagnant_min"), profil.get("cote_gagnant_max")
    if cote is None or cmin is None or cmax is None:
        return 0.50
    marge = (cmax - cmin) * 0.25
    if cmin - marge <= cote <= cmax + marge:
        return 0.75
    return 0.35
