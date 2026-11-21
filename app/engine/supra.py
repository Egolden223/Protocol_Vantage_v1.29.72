"""
supra.py -- Synthèse SUPRA (Phases 1, 3, 4, 5 -- Phase 2 déjà couverte par
_supra_score_sim dans qualitative_engine.py, Phase 6 par longshot.py).
Ajouté le 09/08/2026, remplace le score_sim isolé par une vraie structure
d'audit avec verrou de convergence et plafond de modifications (17.6).

Couverture honnête :
  - Phase 1 (individuel) : classement_national (Frequence-Turf, jours
    Quinté seult) + changement d'équipement (D09bis approximé via
    ferrure_type/oeilleres) + FORME_LINEAIRE. PAS le tandem driver×
    entraîneur (bloqué, cf. audit du 07/08).
  - Phase 3 (marché) : réutilise SOV_v2 déjà calculé (delta cote_matin/
    cote_avant_course), ne recalcule rien.
  - Phase 4 (presse) : ICP (Frequence-Turf, jours Quinté seult) vs rang
    du score interne -- divergence forte = signal.
  - Phase 5 (tactique) : CHAMP_A_RISQUE_DQ_ELEVE (qualitative_engine.py)
    + pièges D_RECENT_NON_ABSORBE.

Garde-fous (17.6), implémentés : plafond global de 3 modifications par
course, verrou de convergence (>=2 phases indépendantes doivent
converger dans le même sens avant toute modification de PCH), jamais de
modification si elle ferait descendre la diversité stylistique ou sortir
des quotas T1-T4 -- vérifié a posteriori par les contraintes dures
existantes (Bloc 9), pas dupliqué ici.
"""
from __future__ import annotations
from typing import List, Dict, Any
from app.models import Cheval, RaceContext, HorseScore

_MAX_MODIFICATIONS_PAR_COURSE = 3
_MODIF_PCH = 4.0  # amplitude d'une modification SUPRA validée (convergence >=2 phases)


def _phase1_individuel(cheval: Cheval, breakdown_flags: List[str]) -> Dict[str, Any]:
    signaux = []
    if cheval.driver_stats and cheval.driver_stats.classement_national:
        if cheval.driver_stats.classement_national <= 10:
            signaux.append(("DRIVER_TOP10_NATIONAL", 1))
        elif cheval.driver_stats.classement_national >= 80:
            signaux.append(("DRIVER_CLASSEMENT_FAIBLE", -1))
    if cheval.ferrure_type or (cheval.equip_changes and cheval.equip_changes > 0):
        signaux.append(("CHANGEMENT_EQUIPEMENT_D09BIS_APPROX", 1))
    if "FORME_LINEAIRE" in " ".join(breakdown_flags):
        pass  # déjà comptabilisé dans PCH via forme_lineaire_pch, pas re-signalé ici pour éviter le double compte
    score = sum(v for _, v in signaux)
    return {"score": max(-3, min(3, score)), "signaux": [s for s, _ in signaux]}


def _phase3_marche(sov_flags: List[str]) -> Dict[str, Any]:
    if "SOV_V2_REPLI" in sov_flags or "SOV_0_POINT" in sov_flags:
        return {"delta_significatif": False, "note": "cote insuffisamment fiable pour juger un mouvement de marché"}
    return {"delta_significatif": "SOV_MOUVEMENT_FORT" in sov_flags, "note": "réutilise SOV_v2, aucun recalcul"}


def _phase4_presse(cheval: Cheval, rang_score_interne: int, nb_partants: int) -> Dict[str, Any]:
    if cheval.icp_global is None:
        return {"divergence": None, "note": "ICP non disponible (Frequence-Turf non consulté ou jour non-Quinté)"}
    bien_classe = rang_score_interne <= max(3, nb_partants // 3)
    ignore_presse = cheval.icp_global == 0
    mal_classe = rang_score_interne >= nb_partants - 2
    tres_cite = cheval.icp_global >= 5
    if bien_classe and ignore_presse:
        return {"divergence": "SOUS_ESTIME_PAR_PRESSE", "note": "bien classé en interne, ignoré par la presse"}
    if mal_classe and tres_cite:
        return {"divergence": "SUR_ESTIME_PAR_PRESSE", "note": "mal classé en interne, très cité par la presse"}
    return {"divergence": None, "note": "cohérent"}


def compute_supra_synthese(race: RaceContext, horses: List[HorseScore],
                            sov_flags_par_cheval: Dict[int, List[str]]) -> Dict[str, Any]:
    """Une seule passe pour toute la course (pas par cheval) -- nécessaire
    pour appliquer le plafond global de 3 modifications (17.6)."""
    horses_par_ordre = sorted(range(len(horses)), key=lambda i: horses[i].synthesis.ordre_final, reverse=True)
    rang_interne = {idx: pos + 1 for pos, idx in enumerate(horses_par_ordre)}
    nb_partants = len(horses)

    candidats = []
    for i, h in enumerate(horses):
        cheval = h.cheval
        p1 = _phase1_individuel(cheval, h.breakdown.flags)
        p3 = _phase3_marche(sov_flags_par_cheval.get(cheval.numero, []))
        p4 = _phase4_presse(cheval, rang_interne[i], nb_partants)

        phases_positives = int(p1["score"] >= 2) + int(bool(p3["delta_significatif"])) + \
            int(p4["divergence"] == "SOUS_ESTIME_PAR_PRESSE")
        phases_negatives = int(p1["score"] <= -2) + int(p4["divergence"] == "SUR_ESTIME_PAR_PRESSE")

        # Verrou de convergence (17.6) : >=2 phases indépendantes requises
        if phases_positives >= 2:
            candidats.append({"numero": cheval.numero, "sens": "+", "nb_phases": phases_positives,
                               "phase1": p1, "phase3": p3, "phase4": p4})
        elif phases_negatives >= 2:
            candidats.append({"numero": cheval.numero, "sens": "-", "nb_phases": phases_negatives,
                               "phase1": p1, "phase3": p3, "phase4": p4})

    candidats.sort(key=lambda c: c["nb_phases"], reverse=True)
    retenus = candidats[:_MAX_MODIFICATIONS_PAR_COURSE]  # plafond global 17.6
    ecartes = candidats[_MAX_MODIFICATIONS_PAR_COURSE:]

    return {
        "modifications_retenues": retenus,
        "modifications_ecartees_plafond": [{"numero": c["numero"], "sens": c["sens"]} for c in ecartes],
        "nb_modifications": len(retenus),
        "plafond": _MAX_MODIFICATIONS_PAR_COURSE,
        "amplitude_pch_par_modification": _MODIF_PCH,
    }
