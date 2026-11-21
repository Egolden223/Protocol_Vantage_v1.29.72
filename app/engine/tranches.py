"""
Partie 3bis (modulation par tranche de cote) et Partie 3ter (décote de
corrélation intra-famille), et Partie 17.9 (sous-tranches T4a/T4b).
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional
import os
from app.models import Tranche
from app.engine.common import clamp

# ---------------------------------------------------------------------------
# Tranches (bornes unifiées, Partie 17.9 -- sur cote_matin uniquement)
# Calibrage 2026-09-18 (arrivées Quinté FR + Dataturf + G56) :
#   T1 <9 favoris | T2 9-15 semi | T3 15-35 outsiders utiles top5
#   T4A 35-100 longshots | T4B 100-300 extrêmes (4e/5e documentés)
# Frontière T3/T4 : 50 → 35 (alignement ruptures 15-30 / ≥35 et extreme_range G56)
# ---------------------------------------------------------------------------
def classify_tranche(cote_matin: Optional[float], cote_fallback: Optional[float] = None) -> Optional[Tranche]:
    """Classe T1–T4b. Fallback cote_avant_course si matin absente.
    >300 → T4B (évite HORS_TRANCHE massif qui casse les quotas [3,5])."""
    cote = cote_matin if cote_matin is not None and cote_matin > 0 else cote_fallback
    if cote is None or cote <= 0:
        return None
    if cote < 9:
        return Tranche.T1
    if cote < 15:
        return Tranche.T2
    if cote < 35:
        return Tranche.T3
    if cote < 100:
        return Tranche.T4A
    # ≥100 y compris extrêmes >300 : T4B (quota-compatible)
    return Tranche.T4B


# 21/09/2026 : assouplissement LÉGER des malus T1/T2.
# 21/09/2026 (v1.29.11) : T2 encore un cran plus doux que T1
# (semi-favoris 9–15 moins écrasés que les très courts <9).
# T3/T4 inchangés (déjà atténués côté outsider_penalty_mult).
_MALUS_TRANCHE_MULT = {Tranche.T1: 1.10, Tranche.T2: 0.95, Tranche.T3: 0.90,
                        Tranche.T4A: 0.70, Tranche.T4B: 0.70}
_BONUS_TRANCHE_MULT = {Tranche.T1: 0.70, Tranche.T2: 0.90, Tranche.T3: 1.10,
                        Tranche.T4A: 1.30, Tranche.T4B: 1.30}

# Malus exclus de l'atténuation RAH-310 (risques absolus, toujours pleine valeur)
_MALUS_EXCLUS_ATTENUATION = {"M25", "M17", "M18", "STAB_CRITIQUE"}

# RAH-310bis / RAH-310ter (2026-09-19) : atténuation des pénalités modules
# primaires A-P (scores négatifs uniquement).
#   T4a/T4b → ×0.50 (moitié)   — longshots / extrêmes
#   T3      → ×0.75 (−25 %)    — outsiders utiles Top5
#   T1      → ×0.90 (−10 %)    — favoris courts
#   T2      → ×0.88 (−12 %)    — semi-favoris (un cran plus doux que T1)
_T4_PENALTY_ATTENUATION = 0.50
_T3_PENALTY_ATTENUATION = 0.75
_T1_PENALTY_ATTENUATION = 0.90
_T2_PENALTY_ATTENUATION = 0.88
_TRANCHES_T4 = (Tranche.T4A, Tranche.T4B)


def bonus_tranche_mult(tranche: Optional[Tranche]) -> float:
    return _BONUS_TRANCHE_MULT.get(tranche, 1.00)


def malus_tranche_mult(tranche: Optional[Tranche]) -> float:
    return _MALUS_TRANCHE_MULT.get(tranche, 1.00)


def is_t4(tranche: Optional[Tranche]) -> bool:
    """True si la tranche est T4a ou T4b (longshot / extrême)."""
    return tranche in _TRANCHES_T4


def is_t3(tranche: Optional[Tranche]) -> bool:
    """True si la tranche est T3 (outsider utile Top5)."""
    return tranche == Tranche.T3


def t4_penalty_mult(tranche: Optional[Tranche]) -> float:
    """Rétrocompatibilité — alias de outsider_penalty_mult (RAH-310bis)."""
    return outsider_penalty_mult(tranche)


def outsider_penalty_mult(tranche: Optional[Tranche]) -> float:
    """Multiplicateur sur scores négatifs des modules primaires A-P.
    T4→0.50 | T3→0.75 | T1→0.90 | T2→0.88 | sinon 1.00."""
    if is_t4(tranche):
        return _T4_PENALTY_ATTENUATION
    if is_t3(tranche):
        return _T3_PENALTY_ATTENUATION
    if tranche == Tranche.T1:
        return _T1_PENALTY_ATTENUATION
    if tranche == Tranche.T2:
        return _T2_PENALTY_ATTENUATION
    return 1.00


# ---------------------------------------------------------------------------
# Familles de signaux (Partie 1.5) -- table de correspondance ID -> famille
# ---------------------------------------------------------------------------
_FAMILLE_PAR_SIGNAL: Dict[str, str] = {
    # Famille C -- conseil humain
    "B09": "C", "B11": "C", "B12": "C", "B38": "C", "B51": "C", "B52": "C", "C56": "C",
    "B60": "C", "B61": "C", "B62": "C", "B63": "C", "B64": "C",
    "TANDEM_BONUS": "C", "BSH": "C", "BSC": "C", "RAH-203": "C", "RAH-281": "C",
    # Famille L -- lieu (hippodrome/distance/terrain)
    "B04": "L", "B05": "L", "B15": "L", "B17": "L", "B19": "L", "B28": "L", "B33": "L",
    "B34": "L", "B39": "L", "B44": "L", "B45": "L", "B46": "L",
    "RAH-182": "L", "RAH-183": "L", "RAH-184": "L",
    # Famille F -- forme récente
    "B01": "F", "B20": "F", "B23": "F", "B24": "F", "B25": "F", "B47": "F", "B47bis": "F",
    "B54": "F", "RAH-309": "F", "FORME_LINEAIRE": "F", "M30": "F",
    # Famille M -- marché
    "B06": "M", "B16": "M", "B35": "M", "B36": "M", "B41": "M", "B53": "M",
    "SOV_v2": "M", "RAH-297": "M", "RAH-308": "M", "RAH-180": "M",
    # Famille P -- physique
    "B21": "P", "B42": "P", "B43": "P", "B48": "P", "RAH-304": "P", "RAH-306": "P",
}


def famille_de(signal_id: str) -> Optional[str]:
    return _FAMILLE_PAR_SIGNAL.get(signal_id)


class SignalActif:
    """Structure légère utilisée pour la décote de famille."""
    __slots__ = ("id", "valeur_brute", "catalog", "famille", "confiance")

    def __init__(self, id: str, valeur_brute: float, catalog: str, famille: Optional[str] = None, confiance: Optional[str] = None):
        self.id = id
        self.valeur_brute = valeur_brute
        self.catalog = catalog  # "B" (bonus) ou "M" (malus)
        self.famille = famille if famille is not None else famille_de(id)
        self.confiance = str(confiance or "").upper() or None


_DECOTE_RANG = [1.00, 0.60, 0.35, 0.20]


def appliquer_decote_famille(signaux: List[SignalActif]) -> List[float]:
    """Retourne la liste des valeurs décotées, dans le même ordre que
    l'entrée. Les signaux sans famille reconnue ne subissent pas de décote
    (traités comme famille singleton)."""
    par_famille: Dict[str, List[int]] = {}
    for idx, s in enumerate(signaux):
        if s.famille:
            par_famille.setdefault(s.famille, []).append(idx)

    resultat = [s.valeur_brute for s in signaux]
    for famille, indices in par_famille.items():
        indices_tries = sorted(indices, key=lambda i: abs(signaux[i].valeur_brute), reverse=True)
        for rang, idx in enumerate(indices_tries):
            mult = _DECOTE_RANG[rang] if rang < len(_DECOTE_RANG) else _DECOTE_RANG[-1]
            resultat[idx] = signaux[idx].valeur_brute * mult
    return resultat


def _env_mult(name: str, default: float, low: float = 0.25, high: float = 1.0) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _confiance_m_mult(signal: SignalActif) -> float:
    if signal.catalog != "M":
        return 1.0
    if signal.confiance == "DEGRADE":
        return _env_mult("VANTAGE_MALUS_M_DEGRADE_MULT", 0.75)
    if signal.confiance == "MINIMAL":
        return _env_mult("VANTAGE_MALUS_M_MINIMAL_MULT", 0.50)
    return 1.0  # STRICT ou confiance absente : pas d’atténuation inventée


def sommer_bonus_malus(signaux: List[SignalActif], tranche: Optional[Tranche]) -> Dict[str, float]:
    """Applique dans l'ordre : (1) décote de famille, (2) RAH-310 (atténuation
    malus T3/T4, hors risques absolus), (3) BONUS_TRANCHE_MULT / MALUS_TRANCHE_MULT.
    Retourne les sommes brutes et finales pour bonus (catalogue B) et malus (catalogue M)."""
    decote = appliquer_decote_famille(signaux)

    # B = bonus catalogue ; G>0 = pépites GRU ; G<0 traité en malus (pièges)
    bonus_brut = sum(
        v for s, v in zip(signaux, decote)
        if s.catalog == "B" or (s.catalog == "G" and v > 0)
    )
    malus_brut = sum(
        v for s, v in zip(signaux, decote)
        if s.catalog == "M" or (s.catalog == "G" and v < 0)
    )

    # RAH-310 : atténuation 50% des malus en T3/T4, hors exclusions
    # Pièges GRU (G négatifs) : même atténuation T3/T4 que M (sauf exclusions id)
    malus_attenue = 0.0
    for s, v in zip(signaux, decote):
        if s.catalog == "M" or (s.catalog == "G" and v < 0):
            pass
        else:
            continue
        v_conf = v * _confiance_m_mult(s)
        if tranche in (Tranche.T3, Tranche.T4A, Tranche.T4B) and s.id not in _MALUS_EXCLUS_ATTENUATION:
            malus_attenue += v_conf * 0.50
        else:
            malus_attenue += v_conf

    bmult = bonus_tranche_mult(tranche)
    mmult = malus_tranche_mult(tranche)

    malus_final = malus_attenue * mmult
    # v1.29.16 — plafond absolu du malus catalogue M, TOUTES tranches.
    # v1.29.20 — T3/T4 : plafond plus souple (−10) pour ne pas éliminer
    # des outsiders viables déjà plafonnés (leçon Argentan #5/#6).
    CAP_MALUS_M_ABS = 12.0
    if tranche in (Tranche.T3, Tranche.T4A, Tranche.T4B):
        CAP_MALUS_M_ABS = 10.0
    if malus_final < -CAP_MALUS_M_ABS:
        malus_final = -CAP_MALUS_M_ABS

    bonus_mult = _env_mult("VANTAGE_BONUS_B_MULT", 0.90)
    bonus_repeat_mult = _env_mult("VANTAGE_BONUS_B_REPEAT_MULT", 0.75)
    primaires: Dict[str, int] = {}
    for idx, s in enumerate(signaux):
        if s.catalog == "B" and s.famille:
            cur = primaires.get(s.famille)
            if cur is None or abs(signaux[cur].valeur_brute) < abs(s.valeur_brute):
                primaires[s.famille] = idx
    bonus_b_sum = 0.0
    for idx, (s, v) in enumerate(zip(signaux, decote)):
        if s.catalog == "B":
            repeat = bool(s.famille and primaires.get(s.famille) != idx)
            bonus_b_sum += v * bonus_mult * (bonus_repeat_mult if repeat else 1.0)
        elif s.catalog == "G" and v > 0:
            bonus_b_sum += v  # GRU positif conservé, hors recalibrage du catalogue B
    return {
        "bonus_brut": bonus_brut,
        "malus_brut": malus_brut,
        "bonus_final": bonus_b_sum * bmult,
        "malus_final": malus_final,
    }
