"""
synthesis.py -- Module Q (COMPOSITE), Module R (SOV/IQL/Harville/ORDRE),
Module T (IFT). Opère sur l'ensemble du champ (nécessaire pour NRC, la
classification provisoire Harville, et harville_fiable au niveau course).
"""
from __future__ import annotations
from typing import List, Dict, Optional
from statistics import mean

from app.models import (Cheval, RaceContext, ModuleBreakdown, SynthesisResult,
                         Discipline, Signature, TypeCourse)
from app.engine.common import clamp, disc_bucket
from app.engine.tranches import classify_tranche
from app.engine import modules_ap as M

# (pch_norm, tocard_score, csf_norm, h2h_norm) — validé empiriquement 13/09/2026
# sur 40 courses ≥14 : baisser PCH / monter tocard dégrade hits+rang1.
# Le levier utile est le blend marché dans ORDRE (race_pipeline), pas ces poids.
_COMPOSITE_WEIGHTS = {
    ("PLAT", "LOCK"): (0.50, 0.15, 0.25, 0.10),
    ("PLAT", "STANDARD"): (0.50, 0.20, 0.20, 0.10),
    ("PLAT", "CHAOS"): (0.44, 0.28, 0.18, 0.10),
    ("PLAT", "MIXTE_LOCK"): (0.48, 0.22, 0.20, 0.10),
    ("TROT", "LOCK"): (0.58, 0.18, 0.14, 0.10),
    ("TROT", "STANDARD"): (0.53, 0.22, 0.15, 0.10),
    ("TROT", "CHAOS"): (0.46, 0.28, 0.16, 0.10),
    ("TROT", "MIXTE_LOCK"): (0.50, 0.24, 0.16, 0.10),
    ("OBSTACLE", "LOCK"): (0.46, 0.25, 0.19, 0.10),
    ("OBSTACLE", "STANDARD"): (0.42, 0.28, 0.20, 0.10),
    ("OBSTACLE", "CHAOS"): (0.36, 0.35, 0.19, 0.10),
    ("OBSTACLE", "MIXTE_LOCK"): (0.40, 0.30, 0.20, 0.10),
}


def _tocard_mult(tranche) -> float:
    """v1.29.72 : baisse du poids du score tocard pour T3 et T4 UNIQUEMENT (recalibrage, jamais nul : plancher ×0,25).
    Le même multiplicateur s’applique aux composantes de classement consommées par le composite et GMO-V.
    VANTAGE_TOCARD_MULT_T34 (défaut actif 0,75 ; palier secondaire 0,50). T1 et T2 inchangés : en T2 le score est inversé
    (AUC intra-tranche 0,33), en T1 il est neutre ; décision propriétaire du 18/11/2026 : l'appliquer sur T3 et T4 seulement.
    Ancien nom VANTAGE_TOCARD_MULT_T123 toujours lu (alias) pour la valeur du multiplicateur."""
    import os
    brut = os.environ.get("VANTAGE_TOCARD_MULT_T34")
    if brut is None:
        brut = os.environ.get("VANTAGE_TOCARD_MULT_T123", "0.75")      # alias de l'ancien nom
    try:
        m = float(brut)
    except ValueError:
        m = 0.75                                                        # valeur invalide : défaut actif
    m = max(0.25, min(1.0, m))
    t = str(getattr(tranche, "value", tranche) or "").upper()
    return m if (m != 1.0 and t in ("T3", "T4", "T4A", "T4B")) else 1.0


def compute_composite(breakdown: ModuleBreakdown, discipline: Discipline, signature: Signature, tranche=None) -> float:
    bucket = disc_bucket(discipline)
    w_pch, w_tocard, w_csf, w_h2h = _COMPOSITE_WEIGHTS.get(
        (bucket, signature.value), _COMPOSITE_WEIGHTS[(bucket, "STANDARD")])
    w_tocard = w_tocard * _tocard_mult(tranche)
    composite = (w_pch * breakdown.pch_norm + w_tocard * breakdown.tocard_score
                 + w_csf * breakdown.csf_norm + w_h2h * breakdown.h2h_norm)
    return clamp(0.0, 1.0, composite)


def compute_sov_v2(cheval: Cheval, tranche) -> tuple[float, List[str]]:
    """SOV v2 enrichi 12/09/2026 :
    - mouvement principal cote_matin → cote_avant_course (timeline multi-horaires)
    - consensus multi-bookmakers (PMU / ZETURF / BETCLIC) si divergence forte
    - plafond smart money T1/T2 inchangé (RAH)
    """
    flags: List[str] = []
    if cheval.cote_matin is None or cheval.cote_avant_course is None:
        if cheval.cote_matin is None:
            flags.append("SOV_0_POINT")
            return 0.0, flags
        flags.append("SOV_V2_REPLI")
        return 0.0, flags

    if cheval.cote_matin <= 0:
        flags.append("SOV_COTE_INVALIDE")
        return 0.0, flags

    delta_final = (cheval.cote_matin - cheval.cote_avant_course) / cheval.cote_matin
    sov = clamp(-0.10, 0.15, 0.4 * delta_final)

    # Bonus/malus consensus multi-bookmakers (levier 2)
    # Si plusieurs BM divergent fortement, le mouvement majoritaire renforce SOV.
    bms = cheval.cotes_bookmakers or {}
    if len(bms) >= 2:
        vals = list(bms.values())
        spread = (max(vals) - min(vals)) / max(min(vals), 0.01)
        if spread >= 0.25:
            # Divergence >25% entre bookmakers = signal d'incertitude marché
            # On atténue légèrement le SOV (moins de confiance dans le mouvement)
            sov *= 0.85
            flags.append("SOV_DIVERGENCE_BOOKMAKERS")
        elif spread <= 0.08 and abs(delta_final) >= 0.10:
            # Consensus fort + mouvement net = smart money confirmé
            sov = clamp(-0.10, 0.15, sov * 1.15)
            flags.append("SOV_CONSENSUS_MULTI_BM")

    # Timeline riche (>=3 points) : si le mouvement est monotone dans le
    # sens du delta final, on confirme ; si zigzag, on atténue.
    timeline = cheval.cotes_timeline or []
    if len(timeline) >= 3:
        cotes_seq = [t["cote"] for t in timeline if t.get("cote")]
        if len(cotes_seq) >= 3:
            mono_down = all(cotes_seq[i] >= cotes_seq[i+1] for i in range(len(cotes_seq)-1))
            mono_up = all(cotes_seq[i] <= cotes_seq[i+1] for i in range(len(cotes_seq)-1))
            if mono_down and delta_final > 0:
                sov = clamp(-0.10, 0.15, sov * 1.10)
                flags.append("SOV_TIMELINE_MONOTONE_BAISSE")
            elif mono_up and delta_final < 0:
                sov = clamp(-0.10, 0.15, sov * 1.10)
                flags.append("SOV_TIMELINE_MONOTONE_HAUSSE")
            elif not mono_down and not mono_up:
                sov *= 0.90
                flags.append("SOV_TIMELINE_ZIGZAG")

    if sov > 0 and tranche is not None and tranche.value in ("T1", "T2"):
        if sov > 0.05:
            flags.append("SOV_SMART_MONEY_PLAFONNE")
        sov = min(sov, 0.05)
    return sov, flags


def compute_iql_v2(cheval: Cheval) -> tuple[float, str]:
    if not cheval.allocations_last3 or len(cheval.allocations_last3) < 1:
        return 1.0, "NEUTRE"
    allocs = cheval.allocations_last3[-3:]
    ratios = []
    for a in allocs:
        montant = a.get("montant", 0.0)
        alloc_course = a.get("allocation_course", 1.0) or 1.0
        ratios.append(montant / max(alloc_course, 1.0))

    if len(ratios) == 3:
        brut = 0.25 * ratios[0] + 0.35 * ratios[1] + 0.40 * ratios[2]
        source = "GAINS3"
    elif len(ratios) == 2:
        brut = 0.45 * ratios[0] + 0.55 * ratios[1]
        source = "GAINS2"
    else:
        brut = ratios[0]
        source = "GAINS2"  # 1 seule dispo -- traité comme repli simple

    alloc_actuelle = cheval.allocation_course_actuelle
    if alloc_actuelle and allocs:
        montants_courses = [a.get("allocation_course", 1.0) or 1.0 for a in allocs]
        ref = alloc_actuelle / max(mean(montants_courses), 1.0)
    else:
        ref = 1.0
    val = brut / max(ref, 1.0)
    return clamp(0.50, 1.50, val), source


def harville_bonus_for(cote: Optional[float], position_attendue: int) -> float:
    if cote is None or position_attendue not in (2, 3, 4, 5) or cote <= 8:
        return 0.0
    gamma, delta = 0.81, 0.65
    prob_brut = (1 / cote)
    exp_pos = gamma if position_attendue == 2 else delta
    prob_corr = (prob_brut ** exp_pos) / (prob_brut ** exp_pos + (1 - prob_brut) ** exp_pos)
    d = prob_corr - prob_brut
    if d > 0.03 and cote > 12:
        return 0.08
    if d > 0.01 and cote > 8:
        return 0.04
    return 0.0


def harville_fiable_course(ift_values: List[float], nb_valeur_morte: int, nb_overbet_media: int,
                           nb_killlist: int, nb_partants: int) -> bool:
    ift_moyen = mean(ift_values) if ift_values else 0.0
    return (ift_moyen >= 75 and nb_valeur_morte <= 3 and nb_overbet_media <= 1
            and (nb_killlist / max(nb_partants, 1)) <= 0.15)


def stab_mult(stab_score: float) -> float:
    return 1.0 + clamp(-0.20, 0.0, stab_score / 100)


def all_mult(all_score: Optional[float]) -> float:
    if all_score is None:
        return 1.00
    if all_score < 0.70:
        return 0.95
    if all_score > 1.50:
        return 1.03
    return 1.00


def ordre_final_malus_enghien(ordre_base: float, hippodrome: str, numero_autostart: Optional[int]) -> float:
    """Conservé pour compatibilité ; le biais multi-hippo passe par GRU."""
    if hippodrome.upper() == "ENGHIEN" and numero_autostart is not None and numero_autostart >= 9:
        return ordre_base * (1 - 0.08 * (numero_autostart - 8) / 8)
    return ordre_base


def ordre_final_with_gru(ordre_base: float, race, cheval) -> float:
    """Applique le biais numéro GRU (Enghien, Vincennes, Cagnes, Vichy, Parilly, Longchamp…)."""
    try:
        from app.engine.gru_signals import ordre_final_gru_numero
        return ordre_final_gru_numero(ordre_base, race, cheval)
    except Exception:
        return ordre_final_malus_enghien(
            ordre_base,
            getattr(race, "hippodrome", "") or "",
            getattr(cheval, "numero_autostart", None),
        )


_IFT_PENALITES_MANQUANTES = {
    "RK_ABSENT_TROT": 4, "MODULE_POIDS_ABSENT_PLAT_HCAP": 3, "MODULE_RECUL_ABSENT_TROT_HCAP": 2,
    "VALEUR_PMU_CALCULEE": 2, "VALEUR_PMU_ESTIMEE": 4, "CHRONO_200M_ABSENT": 2,
    "CRE_PROXY_RK_ACTIF": 1, "PENETROMETRE_ABSENT": 2, "NP_TARDIF": 2,
    "HISTORIQUE_TERRAIN_ABSENT": 2, "HISTORIQUE_DISTANCES_ABSENT": 1, "DAI_ABSENT": 1,
    "ICP_SOURCES_INSUFFISANTES": 1, "IQL_NEUTRE": 1, "ALL_SCORE_ABSENT": 1,
    "GRU_INCONNU": 3,
}


def compute_ift(cheval: Cheval, breakdown: ModuleBreakdown, race: RaceContext,
                 sov_flags: List[str], iql_source: str, position_ordre_score: int = None) -> tuple[float, str]:
    """position_ordre_score : rang 1-indexé de ce cheval par ORDRE_SCORE
    interne (position_attendue dans race_pipeline.py), utilisé pour
    RAH-269 -- ajouté le 08/08/2026, absent jusque-là. Optionnel pour ne
    pas casser les appels existants qui ne l'ont pas encore (ex. la passe
    préliminaire harville_fiable, où ce rang n'a pas encore de sens)."""
    penalites_absence = 0.0   # doublées en zone frontière RAH-269 (5e-12e)
    penalites_qualite = 0.0   # jamais doublées (donnée présente mais faible, pas absente)
    flags = set(breakdown.flags)

    bucket = disc_bucket(race.discipline)
    if bucket == "TROT" and cheval.rk_derniere_sec is None:
        penalites_absence += 4
    if bucket == "PLAT" and race.type_course == TypeCourse.HANDICAP and cheval.poids_actuel_kg is None:
        penalites_absence += 3
    if bucket == "TROT" and race.type_course == TypeCourse.HANDICAP and cheval.recul_m is None:
        penalites_absence += 2

    if "SOV_0_POINT" in sov_flags:
        penalites_qualite += 8
    elif "SOV_V2_REPLI" in sov_flags:
        tranche = classify_tranche(cheval.cote_matin, getattr(cheval, "cote_avant_course", None) or cheval.cote_matin)
        penalites_qualite += 6 if tranche and tranche.value in ("T1", "T2") else 3

    if cheval.chrono_200m is None:
        penalites_absence += 2
        if "CRE_PROXY_v3" in flags:
            penalites_qualite += 1
    if race.penetrometre is None:
        penalites_absence += 2
    # Correctif 14/09/2026 : pénalités historique allégées (fiches souvent
    # absentes hors enrichissement) — évite de degrader tout le champ IFT
    # quand Turfoo/ZT n'ont pas répondu, ce qui biaisait le ranking.
    if not cheval.historique_terrain:
        penalites_absence += 1  # était 2
    if not cheval.historique_distance:
        penalites_absence += 0  # était 1 — informatif, pas bloquant IFT
    # ICP < 3 : seulement si au moins une source presse a répondu (sinon
    # pénaliser tout le champ de la même façon n'aide pas le Top5).
    if cheval.icp_global is not None and cheval.icp_global < 3:
        penalites_qualite += 1
    if iql_source == "NEUTRE":
        penalites_absence += 1
    if cheval.all_score is None:
        penalites_absence += 1

    if position_ordre_score is not None and 5 <= position_ordre_score <= 12:
        penalites_absence *= 2
        if penalites_absence and "RAH269_ZONE_FRONTIERE_PENALITE_DOUBLEE" not in breakdown.flags:
            breakdown.flags.append("RAH269_ZONE_FRONTIERE_PENALITE_DOUBLEE")

    nb_manquants = sum([
        cheval.driver_stats is None,
        cheval.trainer_stats is None,
        race.penetrometre is None,
        cheval.poids_actuel_kg is None and bucket == "PLAT",
        not cheval.historique_distance,
    ])
    if nb_manquants >= 5:
        penalites_qualite += 4
    elif nb_manquants >= 3:
        penalites_qualite += 2

    ift = clamp(0, 100, 100 - penalites_absence - penalites_qualite)
    label = "EXCELLENT" if ift >= 85 else "BON" if ift >= 70 else "ALERTE" if ift >= 55 else "INSUFFISANT"
    return ift, label
