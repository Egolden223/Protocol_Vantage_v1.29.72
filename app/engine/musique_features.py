"""Features musique portées du Top5 Optimizer (forme, régularité, déferrage).

Utilisées en complément PMU-only pour densifier le signal quand les fiches
manquent. N'écrase pas PCH / ORDRE ; alimente le modèle opérationnel via
un bonus soft optionnel.
"""
from __future__ import annotations
import re
from typing import List, Optional, Tuple


# Valeur de position attribuée à un incident dans les calculs de forme (non classé = 10). HYPOTHÈSE documentée :
# un RÉTROGRADÉ a franchi la ligne dans une place puis a été relégué de quelques rangs -> milieu de tableau (6),
# pas « non placé ». À calibrer avec les audits (musique conservée dans dataset_calibration).
_POSITION_INCIDENT = {"RETROGRADE": 6}


def extraire_positions(musique: Optional[str]) -> List[int]:
    """Rangs (du plus récent au plus ancien) d'une musique, via le parseur unique scraping/musique.parse_musique
    (v1.29.48). Corrige 4 erreurs de l'ancien lecteur : « 0 » (= non placé) lu comme position 0, « (24) » lu
    comme une 24e place, « Inédit » lu comme des incidents, et places à deux chiffres / codes longs (Tbé, Arr, Ret,
    Dér, Dpag) mal ou pas lus. Incident (D, A, T) = 10 ; rétrogradé = 6."""
    from app.scraping.musique import parse_musique
    out: List[int] = []
    for p in parse_musique(musique):
        if p.incident:
            out.append(_POSITION_INCIDENT.get(p.incident, 10))
        else:
            out.append(p.rang if p.rang is not None else 10)
    return out


def calculer_forme(musique: Optional[str]) -> float:
    positions = extraire_positions(musique)[:5]
    if not positions:
        return 0.5
    poids = [0.35, 0.25, 0.20, 0.12, 0.08]
    while len(positions) < 5:
        positions.append(10)
    score = sum(p * w for p, w in zip(positions, poids))
    return max(0.0, min(1.0, 1.0 - (score - 1.0) / 15.0))


def calculer_regularite(musique: Optional[str]) -> float:
    positions = extraire_positions(musique)
    if len(positions) < 2:
        return 0.5
    moy = sum(positions) / len(positions)
    var = sum((p - moy) ** 2 for p in positions) / len(positions)
    return max(0.0, min(1.0, 1.0 - (var ** 0.5) / 5.0))


def encoder_deferrage(deferre: Optional[str]) -> float:
    if not deferre:
        return 0.0
    return {"D4": 1.0, "DP": 0.5, "DA": 0.5, "D0": 0.0}.get(deferre.upper().strip(), 0.0)


def score_musique_composite(musique: Optional[str], deferre: Optional[str] = None) -> float:
    """Score 0..1 : 0.55 forme + 0.35 régularité + 0.10 déferrage."""
    f = calculer_forme(musique)
    r = calculer_regularite(musique)
    d = encoder_deferrage(deferre)
    return max(0.0, min(1.0, 0.55 * f + 0.35 * r + 0.10 * d))


# ---------------------------------------------------------------------------
# v1.29.19 (port Grok) — Profil forme Top5 par tranche, pour maximiser
# P(Top5 ⊂ ticket 8). Distinct de score_musique_composite (0..1 continu,
# déjà utilisé ailleurs) : ici un profil DISCRET aligné spécifiquement sur
# la régularité de places Top5/Top3 récentes, utilisé (a) comme petit
# multiplicateur soft sur p_boost (gmo_v.py) et (b) comme voie alternative
# d'éligibilité T3/T4 (RAH-266 assoupli si forme régulière/forte même avec
# un tocard_score un peu sous le seuil).
# ---------------------------------------------------------------------------

def nb_places_top_n(musique: Optional[str], n_courses: int = 3, seuil_rang: int = 5) -> int:
    """Nombre de places <= seuil_rang sur les n_courses plus récentes.
    Incidents (D/T/A) comptent comme non-placé. Rang 0 / 10 = hors Top."""
    positions = extraire_positions(musique)[:n_courses]
    if not positions:
        return 0
    return sum(1 for p in positions if 1 <= p <= seuil_rang)


def nb_top5_recent(musique: Optional[str], n_courses: int = 3) -> int:
    """Places dans le Top5 sur les n courses les plus récentes."""
    return nb_places_top_n(musique, n_courses=n_courses, seuil_rang=5)


def nb_top3_recent(musique: Optional[str], n_courses: int = 3) -> int:
    """Places dans le Top3 sur les n courses les plus récentes."""
    return nb_places_top_n(musique, n_courses=n_courses, seuil_rang=3)


def profil_forme_recente(musique: Optional[str], n_courses: int = 3) -> str:
    """Profil discret pour filtres / boosts par tranche (aligné stats Top5).

    FORTE      : >=2 places Top5 sur n  (régularité capture -- recherche Quinté)
    REGULIERE  : exactement 1 place Top5 sur n
    FAIBLE     : 0 Top5 mais au moins une place <=8
    MORTE      : aucune place utile / musique absente / rangs >=9 ou incidents
    """
    positions = extraire_positions(musique)[:n_courses]
    if not positions:
        return "MORTE"
    n5 = sum(1 for p in positions if 1 <= p <= 5)
    if n5 >= 2:
        return "FORTE"
    if n5 == 1:
        return "REGULIERE"
    if any(1 <= p <= 8 for p in positions):
        return "FAIBLE"
    return "MORTE"


def forme_boost_mult(musique: Optional[str], tranche_value: Optional[str] = None) -> Tuple[float, str]:
    """Multiplicateur soft p_boost selon profil forme x tranche.

    T1/T2 : asymétrie (bonus si FORTE, quasi neutre si MORTE -- pas
    d'écrasement d'un favori sur ce seul critère).
    T3/T4 : bonus si FORTE/REGULIERE, léger malus si MORTE.
    Retourne (mult, label_flag)."""
    profil = profil_forme_recente(musique)
    tv = (tranche_value or "").upper()
    is_t12 = tv in ("T1", "T2")
    is_t34 = tv in ("T3", "T4A", "T4B", "T4")

    if profil == "FORTE":
        return (1.05 if is_t12 else 1.06, f"FORME_FORTE_{profil}")
    if profil == "REGULIERE":
        return (1.02 if is_t12 else 1.04, f"FORME_REGULIERE_{profil}")
    if profil == "FAIBLE":
        return (1.00, f"FORME_FAIBLE_{profil}")
    # MORTE
    if is_t34:
        return (0.97, f"FORME_MORTE_{profil}")
    return (0.99, f"FORME_MORTE_{profil}")


# ---------------------------------------------------------------------------
# v1.29.21 — Forme Top5 filtrée par discipline de la course (anti-bruit
# musique hors-spécialité : un 1p ne compte pas comme forme en attelé).
# ---------------------------------------------------------------------------

_DISC_RACE_TO_MUS = {
    "TROT_ATTELE": {"TROT_ATTELE", "TROT_MONTE"},
    "TROT_MONTE": {"TROT_MONTE", "TROT_ATTELE"},
    "PLAT": {"PLAT"},
    "HAIES": {"HAIES", "STEEPLE"},
    "STEEPLE": {"STEEPLE", "HAIES"},
    "OBSTACLE": {"HAIES", "STEEPLE"},
}


def _norm_disc(disc) -> str:
    if disc is None:
        return ""
    if hasattr(disc, "value"):
        disc = disc.value
    s = str(disc).upper().replace(" ", "_")
    if "ATTEL" in s:
        return "TROT_ATTELE"
    if "MONT" in s:
        return "TROT_MONTE"
    if "PLAT" in s or "GALOP" in s:
        return "PLAT"
    if "HAIE" in s:
        return "HAIES"
    if "STEEP" in s or "OBST" in s:
        return "STEEPLE"
    return s


def positions_meme_discipline(musique, race_discipline, n_courses: int = 5):
    """Rangs récents dans la même famille de discipline que la course."""
    try:
        from app.scraping.musique import parse_musique
    except ImportError:
        return extraire_positions(musique)[:n_courses]
    rd = _norm_disc(race_discipline)
    allowed = _DISC_RACE_TO_MUS.get(rd)
    perfs = parse_musique(musique)
    if not perfs:
        return extraire_positions(musique)[:n_courses]
    out = []
    for p in perfs:
        if allowed and p.discipline not in allowed:
            continue
        if p.incident is not None:
            out.append(10)
        elif p.rang is not None:
            out.append(int(p.rang))
        if len(out) >= n_courses:
            break
    # Repli : si aucune perf même discipline, musique globale (évite MORTE artificiel)
    if not out:
        return extraire_positions(musique)[:n_courses]
    return out


def nb_top5_recent_disc(musique, race_discipline, n_courses: int = 3) -> int:
    pos = positions_meme_discipline(musique, race_discipline, n_courses=n_courses)
    return sum(1 for p in pos if 1 <= p <= 5)


def profil_forme_recente_disc(musique, race_discipline, n_courses: int = 3) -> str:
    """Comme profil_forme_recente mais filtré discipline course."""
    positions = positions_meme_discipline(musique, race_discipline, n_courses=n_courses)
    if not positions:
        return "MORTE"
    n5 = sum(1 for p in positions if 1 <= p <= 5)
    if n5 >= 2:
        return "FORTE"
    if n5 == 1:
        return "REGULIERE"
    if any(1 <= p <= 8 for p in positions):
        return "FAIBLE"
    return "MORTE"


def forme_boost_mult_disc(musique, tranche_value=None, race_discipline=None):
    """Multiplicateur soft — même barème que forme_boost_mult, profil disc."""
    if race_discipline is not None:
        profil = profil_forme_recente_disc(musique, race_discipline)
    else:
        profil = profil_forme_recente(musique)
    tv = (tranche_value or "").upper()
    is_t12 = tv in ("T1", "T2")
    is_t34 = tv in ("T3", "T4A", "T4B", "T4")
    if profil == "FORTE":
        return (1.05 if is_t12 else 1.06, f"FORME_DISC_FORTE")
    if profil == "REGULIERE":
        return (1.02 if is_t12 else 1.04, f"FORME_DISC_REGULIERE")
    if profil == "FAIBLE":
        return (1.00, f"FORME_DISC_FAIBLE")
    if is_t34:
        return (0.97, f"FORME_DISC_MORTE")
    return (0.99, f"FORME_DISC_MORTE")
