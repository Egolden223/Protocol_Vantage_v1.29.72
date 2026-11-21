"""
discipline_router.py — Multiplicateur sélection par famille (v1.29.33)

Stats Quinté+ 2014-2026 (MediaPronos) — favori dans Top5 :
  Trot attelé 71,6 % | Plat 59,4 % | Haies 59,0 % | Steeple 53,7 %
"""
from __future__ import annotations
from typing import Optional, Tuple

from app.models import HorseScore, RaceContext, Tranche, Discipline


def _norm_disc(disc) -> str:
    if disc is None:
        return "UNKNOWN"
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
    if "STEEP" in s or "OBST" in s or "CROSS" in s:
        return "STEEPLE"
    return "UNKNOWN"


def selection_mult(
    hs: HorseScore,
    race: RaceContext,
    *,
    forme_profil_disc: str = "MORTE",
) -> Tuple[float, str]:
    """Multiplicateur 0.95–1.05. Un flag par cheval."""
    fam = _norm_disc(getattr(race, "discipline", None))
    tr = hs.synthesis.tranche if hs.synthesis else None
    pch = getattr(hs.breakdown, "pch_final", None) if hs.breakdown else None
    cote = hs.cheval.cote_avant_course or hs.cheval.cote_matin

    mult = 1.00
    tag = "DISC_NEUTRE"

    if fam in ("TROT_ATTELE", "TROT_MONTE", "TROT"):
        if forme_profil_disc in ("FORTE", "REGULIERE"):
            mult = 1.03
            tag = "DISC_TROT_FORME"
        elif forme_profil_disc == "MORTE" and tr in (Tranche.T1, Tranche.T2):
            mult = 0.98
            tag = "DISC_TROT_FAV_MORTE"
        # Monté : légèrement moins d’aléas faute → densifier forme
        if fam == "TROT_MONTE" and forme_profil_disc == "FORTE":
            mult = 1.04
            tag = "DISC_MONTE_FORME"

    elif fam == "PLAT":
        poids = hs.cheval.poids_actuel_kg
        if poids is None and tr in (Tranche.T1, Tranche.T2):
            mult = 0.98
            tag = "DISC_PLAT_POIDS_ABSENT"
        elif forme_profil_disc in ("FORTE", "REGULIERE"):
            mult = 1.02
            tag = "DISC_PLAT_FORME"

    elif fam == "HAIES":
        if forme_profil_disc in ("FORTE", "REGULIERE"):
            mult = 1.03
            tag = "DISC_HAIES_FORME"
        elif forme_profil_disc == "MORTE":
            mult = 0.97
            tag = "DISC_HAIES_MORTE"
        if tr == Tranche.T1 and forme_profil_disc == "MORTE" and cote and cote < 5:
            mult = min(mult, 0.96)
            tag = "DISC_HAIES_FAV_SANS_FORME"

    elif fam == "STEEPLE":
        # Steeple : marché moins fiable, forme + expérience critiques
        if forme_profil_disc in ("FORTE", "REGULIERE"):
            mult = 1.05
            tag = "DISC_STEEPLE_FORME"
        elif forme_profil_disc == "MORTE":
            mult = 0.96
            tag = "DISC_STEEPLE_MORTE"
        if tr == Tranche.T1 and forme_profil_disc == "MORTE" and cote and cote < 5:
            mult = min(mult, 0.95)
            tag = "DISC_STEEPLE_FAV_SANS_FORME"

    elif fam == "UNKNOWN":
        tag = "DISC_UNKNOWN_NEUTRE"

    if pch is not None and pch >= 210 and mult > 1.0:
        mult = 1.0 + (mult - 1.0) * 0.5
        tag = tag + "_CAP_PCH"

    return mult, tag
