"""Utilitaires communs au moteur déterministe (Partie 1, Partie 3)."""
from __future__ import annotations
from typing import List, Optional, Tuple
from statistics import mean, pvariance

from app.models import Cheval, Discipline, StyleMPA


def clamp(lo: float, hi: float, x: float) -> float:
    return max(lo, min(hi, x))


def disc_bucket(disc) -> str:
    """TROT | PLAT | OBSTACLE | UNKNOWN."""
    if disc is None:
        return "UNKNOWN"
    s = disc.value if hasattr(disc, "value") else str(disc)
    s = s.upper().replace(" ", "_")
    if "ATTEL" in s or "MONT" in s or s == "TROT":
        return "TROT"
    if "PLAT" in s or "GALOP" in s:
        return "PLAT"
    if "HAIE" in s or "STEEP" in s or "OBST" in s or "CROSS" in s:
        return "OBSTACLE"
    return "UNKNOWN"
def terrain_category(penetrometre: Optional[float]) -> Tuple[Optional[str], float]:
    if penetrometre is None:
        return None, 1.00
    # Garde défensive ajoutée le 08/09/2026 suite à un vrai plantage en
    # production (pénétromètre reçu en chaîne de caractères depuis l'API
    # PMU officielle pour une course Haies à Auteuil, cf. pmu_api.py) :
    # même si l'appelant a un bug de conversion, cette fonction ne doit
    # plus jamais planter tout le pipeline pour une seule course sur une
    # valeur mal typée -- traité comme "donnée absente" plutôt qu'un crash.
    try:
        p = float(penetrometre)
    except (TypeError, ValueError):
        return None, 1.00
    if p < 2.0:
        return "TRES_LEGER", 1.08
    if p < 3.5:
        return "LEGER", 1.04
    if p < 5.0:
        return "STANDARD", 1.00
    if p < 6.5:
        return "LOURD", 0.95
    return "TRES_LOURD", 0.88


# ---------------------------------------------------------------------------
# Partie 1.6 -- Style MPA (méthode complète P_SCORE + repli musique)
# ---------------------------------------------------------------------------
def _style_from_musique(musique: Optional[str]) -> Tuple[Optional[StyleMPA], float, List[str]]:
    if not musique:
        return None, 0.0, ["MUSIQUE_ABSENTE"]
    positions = [int(c) for c in musique if c.isdigit()]
    if not positions:
        return None, 0.0, ["MUSIQUE_ILLISIBLE"]
    nb_meneur = sum(1 for p in positions if p <= 4)
    nb_attend = sum(1 for p in positions if p >= 9)
    nb_chasse = len(positions) - nb_meneur - nb_attend
    counts = {"MENEUR": nb_meneur, "ATTENTISTE": nb_attend, "CHASSEUR": nb_chasse}
    best = max(counts.values())
    winners = [k for k, v in counts.items() if v == best]
    flags = ["PSCORE_LEGACY"]
    if len(winners) > 1:
        return StyleMPA.POLYVALENT, 0.30, flags
    label = winners[0]
    if label == "MENEUR":
        # repli binaire ne distingue pas FORT/MODÉRÉ -> on choisit MODÉRÉ (prudent)
        return StyleMPA.MENEUR_MODERE, 0.50, flags
    if label == "ATTENTISTE":
        return StyleMPA.ATTENTISTE, 0.50, flags
    return StyleMPA.CHASSEUR, 0.50, flags


def derive_style_mpa(cheval: Cheval) -> Tuple[Optional[StyleMPA], float, float, List[str]]:
    """Retourne (style, confiance, p_avant, flags). Utilise P_SCORE complet si les
    tableaux position_mi_course_hist / nb_partants sont fournis (>=3 points),
    sinon repli sur la classification par musique (Partie 1.6)."""
    pos_hist = cheval.position_mi_course_hist
    if pos_hist and len(pos_hist) >= 3 and cheval.notes is None:
        # NB: nb_partants_historique n'est pas modélisé séparément dans ce MVP ;
        # on retombe sur la méthode musique si l'appelant n'a pas fourni p_avant.
        pass
    if cheval.p_avant is not None:
        p_avant = cheval.p_avant
        # dérivation du label depuis p_avant fourni par la couche de collecte
        if p_avant >= 0.60:
            return StyleMPA.MENEUR_FORT, 0.70, p_avant, []
        if p_avant >= 0.40:
            return StyleMPA.MENEUR_MODERE, 0.55, p_avant, []
        return StyleMPA.CHASSEUR if p_avant >= 0.30 else StyleMPA.ATTENTISTE, 0.55, p_avant, []
    style, conf, flags = _style_from_musique(cheval.musique)
    p_avant = 0.60 if style == StyleMPA.MENEUR_FORT else (0.50 if style == StyleMPA.MENEUR_MODERE else 0.10)
    return style, conf, p_avant, flags


def champ_mean(values: List[Optional[float]]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return mean(vals)


def champ_variance(values: List[Optional[float]]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    return pvariance(vals)


def attenuer_valeur_pmu_trot(chevaux, discipline, mode_execution) -> dict:
    """v1.29.68 — FUITE DE RÉSULTAT dans la valeur PMU du trot (rang de valeur_pmu ↔ arrivée complète : ρ = −0,91 sur 56 courses ;
    prime de fuite ≈ +0,23 capture/course). Dans une course DÉJÀ COURUE (mode REJEU, ou chrono du jour / réductions kilométriques
    présents), la valeur PMU est ramenée à ZÉRO, c.-à-d. traitée comme absente : SRI et NRC retombent sur leur repli par les gains
    (flags SRI_VALEUR_PMU_MANQUANTE / NRC_PROXY_GAINS), M09 et M22 ne se déclenchent pas, les classements par valeur l'ignorent.
    Les COURSES À VENIR (pré-course, sans chrono du jour) sont traitées normalement : aucune modification.
    VANTAGE_TROT_VALEUR_MULT : 0 (défaut) = neutralisation complète ; 0<m<1 = valeur ramenée vers la moyenne du champ
    (v' = moyenne + m·(v − moyenne), rangs conservés) ; 1 = désactivé."""
    import os
    info = {"actif": False, "mode": None, "mult": None, "n": 0, "raison": None,
            "valeurs_par_partant": []}
    try:
        if disc_bucket(discipline) != "TROT":
            return info
        audit = []
        for c in chevaux:
            field_audit = getattr(c, "_vantage_pmu_field_audit", {}) or {}
            vp = field_audit.get("valeur_pmu", {}) if isinstance(field_audit, dict) else {}
            audit.append({
                "numero": getattr(c, "numero", None),
                "valeur_initiale": getattr(c, "valeur_pmu", None),
                "source": vp.get("source", "source_non_attribuee"),
                "champ_source": vp.get("source_field"),
                "valeur_brute_source": vp.get("raw_value"),
                "horodatage_observation_utc": vp.get("observed_at_utc"),
                "horodatage_collecte_utc": vp.get("collected_at_utc"),
                "action": "inchangée",
            })
        info["valeurs_par_partant"] = audit
        def _finaliser_audit(action):
            for row, cheval in zip(audit, chevaux):
                row["valeur_consommee"] = getattr(cheval, "valeur_pmu", None)
                row["action"] = action
        try:
            m = float(os.environ.get("VANTAGE_TROT_VALEUR_MULT", "0"))
        except ValueError:
            m = 0.0
        m = max(0.0, min(1.0, m))
        if m >= 1.0:
            _finaliser_audit("neutralisation_desactivee")
            return info
        rk = any((getattr(c, "_reduction_km_pmu", None) or 0) > 0 for c in chevaux)
        if mode_execution != "REJEU" and not rk:
            _finaliser_audit("course_a_venir_inchangee")
            return info                                   # course à venir : traitement normal
        vals = [float(c.valeur_pmu) for c in chevaux if c.valeur_pmu is not None]
        if not vals:
            _finaliser_audit("valeur_absente")
            return info
        raison = "REJEU" if mode_execution == "REJEU" else "chrono_du_jour_present"
        if m <= 0.0:
            for c in chevaux:
                if c.valeur_pmu is not None:
                    c.valeur_pmu = None
            info.update({"actif": True, "mode": "zero", "mult": 0.0, "n": len(vals), "raison": raison})
            action = "neutralisee_zero"
        elif len(vals) >= 3:
            moy = sum(vals) / len(vals)
            for c in chevaux:
                if c.valeur_pmu is not None:
                    c.valeur_pmu = round(moy + m * (float(c.valeur_pmu) - moy), 3)
            info.update({"actif": True, "mode": "attenue", "mult": m, "n": len(vals), "raison": raison})
            action = "attenuee_vers_moyenne"
        else:
            action = "inchangée_insuffisamment_de_valeurs"
        _finaliser_audit(action)
    except Exception:  # noqa: BLE001  (ne jamais bloquer l'analyse)
        info["actif"] = False
    return info
