"""
pch_final.py -- Assemble les 33 postes du Bloc 5 (instructions v1.22.2-test)
en un PCH_FINAL par cheval.

Postes 1-16 : Modules A-P (100% déterministe, app/engine/modules_ap.py)
Postes 17-29,31,32 : patch v1.20-v1.22 (Couche LLM, app/llm/qualitative.py)
    -> les signaux de catalogue (B01-B56, M01-M43, GRU PÉPITE/PIÈGE, SSFO,
       GAMMA, RAH-279/281/294/297/304/306/308) passent par la décote de
       famille (Partie 3ter) puis BONUS_TRANCHE_MULT/MALUS_TRANCHE_MULT
       (Partie 3bis) -- voir engine/tranches.py.
    -> FORME_LINEAIRE, D46-D22, D02-B59, M48-B42, M04 (correction poste 21),
       D45, RAH-186, M33, RAH-200 et les modules discipline-spécifiques
       (TROT/PLAT/OBS-0x) sont ajoutés directement (déjà finaux, hors
       modulation générique -- cf Partie 3bis "EXCEPTION RAH-309"). M30 est
       injecté comme signal catalogue ordinaire (poste 31, cf.
       bloc5_ajustes.py) et bénéficie donc automatiquement de la décote de
       famille + RAH-310 + tranche, comme M04 de base.
Poste 30 (CSF) : n'entre PAS dans la somme PCH_FINAL -- alimente uniquement
    COMPOSITE (Bloc 7 / Module Q). Voir engine/synthesis.py.
Poste 33 : PCH_FINAL = clamp(0, 220, somme des postes 1-29 + 31 + 32).
"""
from __future__ import annotations
import math
from typing import List, Tuple, Sequence

from app.models import Cheval, RaceContext, ModuleBreakdown, QualitativeSignals, Tranche
from app.engine import modules_ap as M
from app.engine.common import clamp
from app.engine.tranches import (
    classify_tranche, sommer_bonus_malus, SignalActif,
    is_t4, is_t3, outsider_penalty_mult,
)
from app.engine.csf import compute_csf_signaux
from app.engine.ghost_d import compute_ghost_d

GAMMA_CAP = 8.0



# ---------------------------------------------------------------------------
# Tocards score v2 (P1–P3, 29/09/2026)
#   tocard = clamp( soft_cap(ΣD_dédup) * m_bande
#                 + 0.15 * LS_FINAL
#                 + 0.10 * PDQ_det
#                 + 0.06 * SDR_det
#                 + 0.08 * 1_OVERBET_bool )
# soft_cap = sqrt ; m_T3=1.08, m_T4A=1.00, m_T4B=0.90
# ---------------------------------------------------------------------------

_GHOST_D_FAMILIES = {
    "TANDEM": {"D10", "D38", "D39"},
    "FORME": {"D01", "D02", "D05"},
    "PRESSE": {"D22", "D35"},
    "DRIVER": {"D03", "D20", "D43"},
    "H2H": {"D15", "D19"},
    "POIDS_VALEUR": {"D31", "D32", "D33"},
    "RETOUR": {"D08", "D21"},
    "DRAW": {"D30"},
    "TERRAIN_HIPPO": {"D06", "D07", "D26"},
    "VALEUR_HANDICAP": {"D28", "D29", "D34", "D36", "D37"},
}


def _ghost_d_family(gid: str) -> str:
    for fam, ids in _GHOST_D_FAMILIES.items():
        if gid in ids:
            return fam
    return f"SOLO_{gid}"


def _dedup_ghost_d_contributions(contrib: list) -> float:
    """Par famille sémantique, ne conserve que le max (anti double-compte)."""
    best: dict = {}
    solo = 0.0
    for flag, val in contrib or []:
        if not flag.startswith("D"):
            continue
        gid = flag.split("_")[0]
        if gid in ("D41", "D40", "D46"):
            # D41 = combo déjà non linéaire ; D40 hors 1re passe
            if gid == "D41":
                solo += float(val)
            continue
        fam = _ghost_d_family(gid)
        v = float(val)
        if fam.startswith("SOLO_"):
            solo += v
        else:
            best[fam] = max(best.get(fam, 0.0), v)
    return sum(best.values()) + solo


def _soft_cap_sigma_d(sigma: float) -> float:
    """Rendements décroissants : sqrt(Σ) plafonne l'empilement de petits flags."""
    if sigma <= 0:
        return 0.0
    return math.sqrt(sigma)


def _tocard_band_mult(cote: float | None) -> tuple[float, str]:
    if cote is None or cote <= 0:
        return 1.0, "NA"
    if cote < 15:
        return 1.0, "T1T2"
    if cote < 35:
        return 1.08, "T3"
    if cote < 100:
        return 1.00, "T4A"
    return 0.90, "T4B"


def _pdq_deterministe(cheval) -> float:
    """PDQ v1.29.36 : score forme Top6 pondéré sur 5 dernières (0–1)."""
    try:
        from app.scraping.musique import score_forme_recente_top6
        return float(score_forme_recente_top6(getattr(cheval, "musique", None) or "", n=5).get("score_0_1") or 0.0)
    except Exception:
        try:
            from app.scraping.musique import parse_musique
            perfs = parse_musique(cheval.musique or "")[:5]
        except Exception:
            return 0.0
        if not perfs:
            return 0.0
        tops = sum(1 for p in perfs if getattr(p, "rang", None) is not None and p.rang <= 6)
        return max(0.0, min(1.0, tops / len(perfs)))


def _sdr_deterministe(cheval) -> float:
    """SDR : stabilité (peu d'incidents + rangs peu dispersés) 0–1."""
    try:
        from app.scraping.musique import parse_musique
        perfs = parse_musique(cheval.musique or "")[:6]
    except Exception:
        return 0.0
    if len(perfs) < 2:
        return 0.0
    n = len(perfs)
    incidents = sum(1 for p in perfs if getattr(p, "incident", None))
    ranks = [p.rang for p in perfs if getattr(p, "rang", None) is not None]
    clean = 1.0 - (incidents / n)
    if len(ranks) < 2:
        return max(0.0, min(1.0, clean * 0.5))
    mean_r = sum(ranks) / len(ranks)
    var = sum((r - mean_r) ** 2 for r in ranks) / len(ranks)
    # var typique 0–40 ; map soft
    stab = max(0.0, 1.0 - var / 40.0)
    return max(0.0, min(1.0, 0.55 * clean + 0.45 * stab))



# Priorité 7 — seuils calibrés (walk-forward, 29/09/2026)
T2_VALUE_SEUIL_FORT = 0.55
T2_VALUE_SEUIL_UTILE = 0.40
T2_VALUE_SEUIL_FAIBLE = 0.30
TOCARD_TIER_FORT = 0.40
TOCARD_TIER_UTILE = 0.30
TOCARD_TIER_FAIBLE = 0.20


def compute_t2_value_score(cheval, race, champ, bd, qual,
                           champ_breakdowns: Sequence[ModuleBreakdown] | None = None) -> tuple[float, list]:
    """Module Outsiders-Value T2 (cote 9–15) — boost des meilleurs semi-favoris.

    Objectif : identifier les T2 sous-évalués par le marché relatif à la
    force réelle (PCH/forme/driver/edge), sans utiliser tocard (T3/T4).

    Score 0–1 composite :
      0.30 * force_rel (rang PCH dans le champ, inversé)
      0.25 * forme (PDQ musique Top5)
      0.20 * edge_marche (rang score vs rang cote — sous-cote)
      0.15 * driver_elite
      0.10 * presse_moderee (ICP pas excessif)
    """
    flags = []
    from app.engine.tranches import classify_tranche
    cote = None
    try:
        cote = float(
            cheval.cote_avant_course
            if cheval.cote_avant_course is not None
            else cheval.cote_matin
        )
    except (TypeError, ValueError):
        cote = None
    tr = classify_tranche(
        cheval.cote_matin,
        getattr(cheval, "cote_avant_course", None) or cheval.cote_matin,
    )
    tr_v = tr.value if tr is not None else None
    if tr_v != "T2":
        return 0.0, ["T2_VALUE_SKIP_HORS_T2"]

    # Les rangs sont calculés dans une passe après le PCH de tous les partants
    # (pas de récursion ni de comparaison à une échelle absolue arbitraire).
    force, edge = 0.5, 0.5
    if champ_breakdowns is not None and len(champ_breakdowns) == len(champ) and champ:
        idx = next((i for i, c in enumerate(champ)
                    if c is cheval or getattr(c, "numero", None) == getattr(cheval, "numero", None)), None)
        if idx is not None:
            pch_scores = [float(getattr(x, "pch_final", x) or 0.0) for x in champ_breakdowns]
            def _rangs(values, reverse=False):
                order = sorted(range(len(values)), key=lambda i: ((-values[i]) if reverse else values[i], i))
                ranks = [0] * len(values)
                for rank, j in enumerate(order, 1):
                    ranks[j] = rank
                return ranks
            cote_values = []
            for c in champ:
                try:
                    raw = getattr(c, "cote_avant_course", None)
                    raw = raw if raw is not None else getattr(c, "cote_matin", None)
                    value = float(raw) if raw is not None else None
                    cote_values.append(value if value is not None and value > 1.0 else float("inf"))
                except (TypeError, ValueError):
                    cote_values.append(float("inf"))
            rank_pch = _rangs(pch_scores, reverse=True)
            rank_market = _rangs(cote_values)
            denom = max(1, len(champ) - 1)
            force = (len(champ) - rank_pch[idx]) / denom
            # 0.5 = parité PCH/marché; >0.5 = PCH mieux classé que le marché.
            edge = max(0.0, min(1.0, 0.5 + 0.5 * (rank_market[idx] - rank_pch[idx]) / denom))
            flags.extend(["T2_VALUE_FORCE_RANG_PCH", "T2_VALUE_EDGE_PCH_VS_MARCHE"])
            flags.append(f"T2_VALUE_RANKS_force={force:.3f}_edge={edge:.3f}")
    else:
        flags.append("T2_VALUE_RELATIVE_RANGS_INDISPONIBLES")

    # forme PDQ
    forme = _pdq_deterministe(cheval)

    # Dérive de cote pré-course : bonus limité, en complément du rang relatif.
    if cote is not None:
        cm = cheval.cote_matin
        ca = cheval.cote_avant_course
        try:
            if cm and ca and float(cm) > 0 and float(ca) / float(cm) <= 0.90:
                edge = min(1.0, edge + 0.15)
                flags.append("T2_VALUE_DRIFT_IN")
        except (TypeError, ValueError):
            pass

    # driver elite
    drv = 0.0
    ds = cheval.driver_stats
    if ds and getattr(ds, "classement_national", None) is not None:
        if ds.classement_national <= 10:
            drv = 1.0
        elif ds.classement_national <= 25:
            drv = 0.6
        elif ds.classement_national <= 50:
            drv = 0.3
    elif cheval.changement_driver:
        drv = 0.35
        flags.append("T2_VALUE_CHG_DRIVER")

    # presse : ICP faible-moyen = pas surjoué
    icp = cheval.icp_global
    presse = 0.5
    if icp is not None:
        if icp <= 2:
            presse = 0.9
        elif icp <= 4:
            presse = 0.6
        else:
            presse = 0.25  # très cité = moins de « value »

    # bonus modules positifs déjà dans bd
    mod_bonus = 0.0
    try:
        if float(getattr(bd, "module_dist_adapt", 0) or 0) >= 8:
            mod_bonus += 0.05
        if float(getattr(bd, "module_terrain_dyn", 0) or 0) >= 8:
            mod_bonus += 0.05
        if float(getattr(bd, "tandem_final", 0) or 0) >= 5:
            mod_bonus += 0.05
    except Exception:
        pass

    score = (
        0.30 * force
        + 0.25 * forme
        + 0.20 * edge
        + 0.15 * drv
        + 0.10 * presse
        + mod_bonus
    )
    score = max(0.0, min(1.0, score))
    if score >= T2_VALUE_SEUIL_FORT:
        flags.append("T2_VALUE_FORT")
    elif score >= T2_VALUE_SEUIL_UTILE:
        flags.append("T2_VALUE_UTILE")
    elif score >= T2_VALUE_SEUIL_FAIBLE:
        flags.append("T2_VALUE_FAIBLE")
    else:
        flags.append("T2_VALUE_BRUIT")
    return round(score, 4), flags


def apply_t2_value_scores(chevaux: Sequence[Cheval], race: RaceContext,
                          breakdowns: Sequence[ModuleBreakdown],
                          qualitatifs: Sequence[QualitativeSignals]) -> None:
    """Passe champ T2 après calcul de tous les PCH; met à jour score, flags et signal sans modifier PCH_FINAL."""
    pch = [float(getattr(bd, "pch_final", 0.0) or 0.0) for bd in breakdowns]
    for cheval, bd, qual in zip(chevaux, breakdowns, qualitatifs):
        score, flags = compute_t2_value_score(cheval, race, chevaux, bd, qual, pch)
        bd.t2_value_score = float(score)
        bd.flags.extend(f for f in flags if f not in bd.flags)
        if score >= T2_VALUE_SEUIL_UTILE and not any(s.get("id") == "T2_VALUE" for s in bd.signaux_actifs if isinstance(s, dict)):
            bd.signaux_actifs.append({
                "id": "T2_VALUE", "valeur_brute": float(score), "catalog": "B", "famille": "VALUE",
                "is_gamma": False, "justification": "outsider_value_t2_relative_pch_marche",
                "confiance": "STRICT" if score >= T2_VALUE_SEUIL_FORT else "DEGRADE",
                "label": "Value T2 (semi-favori sous-évalué)",
            })


def _rah242_secondary_cap(bd) -> dict[str, float]:
    """Plafonne les contributions secondaires positives (dont GRU et tactique) par les primaires."""
    primary = sum(max(0.0, float(getattr(bd, name, 0.0) or 0.0)) for name in (
        "sri_v2", "iff_v2", "nrc", "bsh_v3v4", "bsc_v3", "stab_pch", "module_poids",
        "module_recul", "module_terrain_dyn", "module_dist_adapt", "mpa_champ", "cre_total", "tandem_final",
    ))
    secondary = sum(max(0.0, float(getattr(bd, name, 0.0) or 0.0)) for name in (
        "tact_pch", "bonus_b_sum_module", "forme_lineaire_pch", "d46_d22_pch", "d02_b59_pch",
        "m48_b42_pch", "m04_pch", "d45_pch", "rah186_pch", "m33_pch", "rah200_pch",
        "discipline_specifique_pch", "gamma_pch", "gru_dist2_pch", "gru_pepite_piege_pch", "rah270_ai_pch",
    ))
    allowed = min(secondary, primary)
    return {"primary_positive": primary, "secondary_raw": secondary,
            "secondary_allowed": allowed, "correction": allowed - secondary}


def _merge_active_signals(signaux_catalogue, signaux_actifs):
    """Conserve les signaux hors catalogue, dont GRU, sans dupliquer les IDs catalogue."""
    catalog_ids = {s.id for s in (signaux_catalogue or [])}
    extras = [s for s in (signaux_actifs or [])
              if (s.get("id") if isinstance(s, dict) else getattr(s, "id", None)) not in catalog_ids]
    catalog = [s.model_dump() if hasattr(s, "model_dump") else s for s in (signaux_catalogue or [])]
    return catalog + extras


def compute_tocard_score_v2(
    ghost_d_somme_raw: float,
    ghost_d_contrib: list,
    ls_final: float,
    cheval,
    overbet_bool: bool = False,
) -> tuple[float, dict]:
    """Formule tocard P1–P3. Retourne (score, meta audit)."""
    sigma_dedup = _dedup_ghost_d_contributions(ghost_d_contrib)
    # sécurité : si pas de contrib, repli somme brute
    if not ghost_d_contrib and ghost_d_somme_raw > 0:
        sigma_dedup = float(ghost_d_somme_raw)
    soft = _soft_cap_sigma_d(sigma_dedup)
    cote = None
    try:
        cote = float(
            cheval.cote_avant_course
            if cheval.cote_avant_course is not None
            else cheval.cote_matin
        )
    except (TypeError, ValueError):
        cote = None
    m_band, band = _tocard_band_mult(cote)
    # Tocards score : uniquement T3/T4 (cote ≥ 15). T1/T2 → 0 (hors périmètre).
    if band == "T1T2":
        meta = {
            "sigma_d_raw": round(float(ghost_d_somme_raw or 0.0), 4),
            "sigma_d_dedup": 0.0,
            "soft_cap_sqrt": 0.0,
            "band": "T1T2",
            "band_mult": 0.0,
            "ls_final": 0.0,
            "pdq": 0.0,
            "sdr": 0.0,
            "overbet_bool": False,
            "tocard": 0.0,
            "tier": "NA_T1T2",
            "skipped": True,
            "reason": "tocard_reserve_t3_t4",
        }
        return 0.0, meta
    pdq = _pdq_deterministe(cheval)
    sdr = _sdr_deterministe(cheval)
    ls = max(0.0, min(1.0, float(ls_final or 0.0)))
    raw = (
        soft * m_band
        + 0.15 * ls
        + 0.10 * pdq
        + 0.06 * sdr
        + (0.08 if overbet_bool else 0.0)
    )
    score = max(0.0, min(1.0, raw))
    meta = {
        "sigma_d_raw": round(float(ghost_d_somme_raw or 0.0), 4),
        "sigma_d_dedup": round(sigma_dedup, 4),
        "soft_cap_sqrt": round(soft, 4),
        "band": band,
        "band_mult": m_band,
        "ls_final": round(ls, 4),
        "pdq": round(pdq, 4),
        "sdr": round(sdr, 4),
        "overbet_bool": bool(overbet_bool),
        "tocard": round(score, 4),
        "skipped": False,
        # Échelle décisionnelle (P3) — T3/T4 only
        "tier": (
            "FORT" if score >= TOCARD_TIER_FORT
            else "UTILE" if score >= TOCARD_TIER_UTILE
            else "FAIBLE" if score >= TOCARD_TIER_FAIBLE
            else "BRUIT"
        ),
    }
    return score, meta


def compute_module_breakdown(cheval: Cheval, race: RaceContext, champ: List[Cheval],
                              qual: QualitativeSignals) -> ModuleBreakdown:
    bd = ModuleBreakdown()
    all_flags: List[str] = []

    sri, f = M.module_a_sri(cheval, race.discipline); bd.sri_v2 = sri; all_flags += f
    iff, f = M.module_b_iff(cheval, race.discipline); bd.iff_v2 = iff; all_flags += f
    nrc, f = M.module_c_nrc(cheval, champ); bd.nrc = nrc; all_flags += f
    bsh, f = M.module_d_bsh(cheval, race.discipline, race); bd.bsh_v3v4 = bsh; all_flags += f
    bsc, f = M.module_e_bsc(cheval, race.discipline); bd.bsc_v3 = bsc; all_flags += f

    champ_cotes = [c.cote_matin for c in champ]
    stab, f = M.module_f_stab(cheval, race.discipline, champ_cotes); bd.stab_pch = stab; all_flags += f

    tact, f = M.module_g_tact(cheval, race); bd.tact_score = tact; all_flags += f
    # A1 (30/09/2026) : injection PCH bornée (en plus du tact_mult sur ordre_final)
    from app.engine.common import clamp as _clamp
    bd.tact_pch = _clamp(-15.0, 15.0, float(tact) * 0.35)  # scale soft anti double-compte mult
    if abs(bd.tact_pch) >= 0.5:
        all_flags.append(f"TACT_PCH_{bd.tact_pch:+.1f}")
    poids, f = M.module_h_poids(cheval, race, champ); bd.module_poids = poids; all_flags += f
    recul, f = M.module_i_recul(cheval, race); bd.module_recul = recul; all_flags += f
    terrain, f = M.module_j_terrain(cheval, race); bd.module_terrain_dyn = terrain; all_flags += f
    dist_adapt, f = M.module_k_dist_adapt(cheval, race); bd.module_dist_adapt = dist_adapt; all_flags += f
    mpa, f = M.module_l_mpa_champ(cheval, race); bd.mpa_champ = mpa; all_flags += f
    cre, f = M.module_m_cre(cheval, race, champ); bd.cre_total = cre; all_flags += f
    h2h, f = M.module_n_h2h(cheval, champ); bd.h2h_norm = h2h; all_flags += f
    tandem, f = M.module_p_tandem(cheval); bd.tandem_final = tandem; all_flags += f
    # OVERBET (Module O) est calculé en 2e passe -- voir apply_overbet_second_pass()

    # --- RAH-310bis / RAH-310ter (2026-09-19) : atténuation des pénalités
    # modules primaires A-P (scores négatifs uniquement).
    #   T4a/T4b → ×0.50 (moitié)
    #   T3      → ×0.75 (−25 %)
    # Objectif : éviter de sur-pénaliser les outsiders (ex. gagnant @48
    # sous-évalué par MPA_CHAMP + IFF). Les bonus restent intacts.
    # Les malus catalogue B/M restent gérés par RAH-310 dans sommer_bonus_malus.
    tranche = classify_tranche(cheval.cote_matin, getattr(cheval, "cote_avant_course", None) or cheval.cote_matin)
    _pen_mult = outsider_penalty_mult(tranche)
    if _pen_mult < 1.0:
        _module_attrs = (
            "sri_v2", "iff_v2", "nrc", "bsh_v3v4", "bsc_v3", "stab_pch",
            "module_poids", "module_recul", "module_terrain_dyn", "module_dist_adapt",
            "mpa_champ", "cre_total", "tandem_final",
        )
        _attenuated = []
        for attr in _module_attrs:
            val = getattr(bd, attr, None)
            if val is not None and val < 0:
                setattr(bd, attr, val * _pen_mult)
                _attenuated.append(attr)
        if _attenuated:
            if is_t4(tranche):
                all_flags.append("T4_PENALITES_ATTENUEES_50")
            elif is_t3(tranche):
                all_flags.append("T3_PENALITES_ATTENUEES_25")
            all_flags.append(f"OUTSIDER_ATTRS:{','.join(_attenuated)}")

    # --- Signaux de catalogue (Couche LLM) : décote famille + tranche ---
    signaux = [SignalActif(s.id, s.valeur_brute, s.catalog, s.famille, s.confiance) for s in qual.signaux_catalogue]

    gamma_signaux = [s for s, orig in zip(signaux, qual.signaux_catalogue) if orig.is_gamma]
    non_gamma_signaux = [s for s, orig in zip(signaux, qual.signaux_catalogue) if not orig.is_gamma]

    sums_non_gamma = sommer_bonus_malus(non_gamma_signaux, tranche)
    sums_gamma = sommer_bonus_malus(gamma_signaux, tranche) if gamma_signaux else \
        {"bonus_final": 0.0, "malus_final": 0.0, "bonus_brut": 0.0, "malus_brut": 0.0}
    gamma_net = clamp(-GAMMA_CAP, GAMMA_CAP, sums_gamma["bonus_final"] + sums_gamma["malus_final"])
    bd.gamma_pch = gamma_net
    gru_dist2, gru_dist2_flags = M.module_gru_dist2(cheval, race)
    bd.gru_dist2_pch = gru_dist2
    all_flags += gru_dist2_flags
    bd.bonus_b_sum_brut = sums_non_gamma["bonus_brut"] + sums_gamma["bonus_brut"]
    bd.malus_m_sum_brut = sums_non_gamma["malus_brut"] + sums_gamma["malus_brut"]
    bd.bonus_b_sum_module = sums_non_gamma["bonus_final"]
    bd.malus_m_sum_module = sums_non_gamma["malus_final"]
    if any(s.catalog == "M" and s.confiance in ("DEGRADE", "MINIMAL") for s in signaux):
        all_flags.append("MALUS_M_PONDERE_PAR_CONFIANCE_V69")
    if bd.bonus_b_sum_module > 0:
        all_flags.append("BONUS_B_RECALIBRE_V69")

    # v1.29.34 — T1/T2 + commentaire absent : le catalogue M frappe à
    # plein sans contre-signal IFF textuel (Chantilly ANSSIO M−12 → hors
    # ticket alors que gagnant). Atténue 35% le malus module, hors T3/T4
    # déjà couverts par RAH-310.
    _flags_pre = list(dict.fromkeys(all_flags + qual.flags))
    _comm_absent = (
        "COMMENTAIRE_ABSENT" in _flags_pre
        or not getattr(cheval, "commentaire_derniere_course", None)
    )
    if (
        _comm_absent
        and tranche is not None
        and getattr(tranche, "value", "") in ("T1", "T2")
        and bd.malus_m_sum_module < -4.0
    ):
        bd.malus_m_sum_module *= 0.65
        all_flags.append("MALUS_M_ATTENUE_T12_SANS_COMMENTAIRE")

    bd.forme_lineaire_pch = clamp(-20, 20, qual.forme_lineaire_pch)
    bd.d46_d22_pch = qual.d46_d22_pch
    bd.d02_b59_pch = qual.d02_b59_pch
    bd.m48_b42_pch = qual.m48_b42_pch
    bd.m04_pch = qual.m04_pch
    bd.d45_pch = clamp(-10, 10, qual.d45_pch)
    bd.rah186_pch = qual.rah186_pch
    bd.m33_pch = qual.m33_pch
    bd.rah200_pch = qual.rah200_pch
    bd.discipline_specifique_pch = qual.discipline_specifique_pch
    # Priorité 5 — GRU pépite assouplie (injection PCH bornée)
    try:
        from app.engine.gru_signals import compute_gru_pepite
        from app.engine.gru_catalog import get_gru_entry
        _entry = None
        try:
            _entry = get_gru_entry(getattr(race, "hippodrome", None) or "")
        except Exception:
            _entry = None
        pep_s, pep_f = compute_gru_pepite(cheval, race, _entry if isinstance(_entry, dict) else None)
        try:
            from app.engine.gru_signals import compute_gru_piege
            pie_s, pie_f = compute_gru_piege(cheval, race, _entry if isinstance(_entry, dict) else None)
        except Exception:
            pie_s, pie_f = 0.0, []
        # Net PCH : pépite (+) + piège (−)
        bd.gru_pepite_piege_pch = float(pep_s) + float(pie_s)
        bd.flags.extend(pep_f)
        bd.flags.extend(pie_f)
        if pep_s >= 4.0:
            bd.signaux_actifs.append({
                "id": "GRU_PEPITE",
                "valeur_brute": float(pep_s),
                "catalog": "G",
                "famille": "L",
                "is_gamma": False,
                "justification": "|".join(pep_f[:4]),
                "confiance": "STRICT" if pep_s >= 5.5 else "DEGRADE",
                "label": "GRU pépite outsider hippo",
            })
        if pie_s <= -3.0:
            bd.signaux_actifs.append({
                "id": "GRU_PIEGE",
                "valeur_brute": float(pie_s),
                "catalog": "G",
                "famille": "L",
                "is_gamma": False,
                "justification": "|".join(pie_f[:4]),
                "confiance": "DEGRADE",
                "label": "GRU piège numéro/AS/favori",
            })
    except Exception as _e_pep:
        bd.gru_pepite_piege_pch = 0.0
        bd.flags.append("GRU_PEPITE_ERROR")

    # RAH-270 IA (v1.29.14, optionnel) -- lecture pure, AUCUN appel réseau
    # ici : le signal a déjà été calculé en amont, une fois par course, par
    # app/engine/ai_rhythm.py (orchestrator.py, étape dédiée). Clamp
    # défensif redondant avec celui de supervisor.py -- on ne fait jamais
    # confiance à une seule couche de bornage pour un signal IA.
    if cheval.rah270_ai_signal is not None:
        bd.rah270_ai_pch = clamp(-3.0, 3.0, cheval.rah270_ai_signal)
        if abs(bd.rah270_ai_pch) > 0.01:
            all_flags.append(f"RAH270_AI_SIGNAL:{bd.rah270_ai_pch:+.1f}")

    bd.signaux_actifs = _merge_active_signals(qual.signaux_catalogue, bd.signaux_actifs)
    bd.flags = list(dict.fromkeys(all_flags + qual.flags))  # dédoublonné, ordre conservé

    # --- Postes manquants (Étape 4.22) : pénalité si >=3 ou >=5 blocs absents ---
    blocs_absents = 0
    if cheval.driver_stats is None or not cheval.driver_stats.fenetres:
        blocs_absents += 1  # D (BSH)
    if cheval.trainer_stats is None or not cheval.trainer_stats.fenetres:
        blocs_absents += 1  # E (BSC)
    if "PENETROMETRE_ABSENT" in all_flags:
        blocs_absents += 1  # F (terrain)
    if cheval.poids_actuel_kg is None and race.discipline.value == "PLAT" and race.type_course.value == "HANDICAP":
        blocs_absents += 1  # H (poids)
    if "HISTORIQUE_DISTANCE_ABSENT" in all_flags:
        blocs_absents += 1  # M (distance)

    pch_avant_penalite = (
        bd.sri_v2 + bd.iff_v2 + bd.nrc + bd.bsh_v3v4 + bd.bsc_v3 + bd.stab_pch
        + getattr(bd, "tact_pch", 0.0)
        + bd.module_poids + bd.module_recul + bd.module_terrain_dyn + bd.module_dist_adapt
        + bd.mpa_champ + bd.cre_total + bd.tandem_final
        + bd.bonus_b_sum_module + bd.malus_m_sum_module
        + bd.forme_lineaire_pch + bd.d46_d22_pch + bd.d02_b59_pch + bd.m48_b42_pch
        + bd.m04_pch + bd.d45_pch + bd.rah186_pch + bd.m33_pch + bd.rah200_pch
        + bd.discipline_specifique_pch + bd.gamma_pch + bd.gru_dist2_pch
        + bd.gru_pepite_piege_pch
        + bd.rah270_ai_pch
    )

    # --- RAH-242 (porté depuis hardened_complete le 11/09/2026) : le total
    # des bonus SECONDAIRES (catalogue B/M + patches, postes 17-32) ne peut
    # pas dépasser le total des bonus PRIMAIRES positifs (Modules A-P,
    # postes 1-16, 100% déterministe) -- classification reprise de la
    # distinction déjà actée dans ce projet (cf. README "Architecture" et
    # commentaire d'en-tête de ce fichier), pas une taxonomie inventée pour
    # l'occasion. Un cheval sans profil de performance solide (peu ou pas
    # de bonus primaire) ne doit pas être porté uniquement par
    # l'empilement de bonus qualitatifs/catalogue.
    _rah242 = _rah242_secondary_cap(bd)
    bd.rah242_primary_positive = _rah242["primary_positive"]
    bd.rah242_secondary_raw = _rah242["secondary_raw"]
    bd.rah242_secondary_allowed = _rah242["secondary_allowed"]
    rah242_correction = _rah242["correction"]  # <=0
    if rah242_correction < 0:
        pch_avant_penalite += rah242_correction
        bd.rah242_secondary_correction = rah242_correction
        bd.flags.append("RAH242_SECONDARY_CAPPED")

    if blocs_absents >= 5:
        pch_avant_penalite *= 0.80
        bd.flags.append("PCH_PENALITE_5_BLOCS_MANQUANTS")
    elif blocs_absents >= 3:
        pch_avant_penalite *= 0.90
        bd.flags.append("PCH_PENALITE_3_BLOCS_MANQUANTS")

    bd.pch_final = clamp(0, 220, pch_avant_penalite)
    bd.pch_norm = bd.pch_final / 220.0

    # CSF (poste 30) -- N'ENTRE PAS dans PCH_FINAL, alimente COMPOSITE uniquement.
    # SF-01 à SF-24 réellement évalués depuis le 02/09/2026 (cf. csf.py) --
    # remplace l'ancienne approximation à 2 signaux de qualitative_engine.py,
    # qui reste dans qual.csf_signaux mais n'est plus utilisée ici.
    qual.csf_signaux = compute_csf_signaux(
        cheval, race, len(champ), [s.id for s in qual.signaux_catalogue],
        bd.iff_v2, bd.bsc_v3, bd.bsh_v3v4, bd.module_recul, bd.module_terrain_dyn, bd.module_dist_adapt)
    coeff_synergie = {1: 0.50, 2: 0.65, 3: 0.80, 4: 0.85, 5: 0.92}
    familles_actives = {s.famille for s in qual.csf_signaux if s.famille}
    n_familles = max(1, len(familles_actives)) if familles_actives else 1
    mult_syn = coeff_synergie.get(min(n_familles, 5), 0.92 if n_familles > 5 else 0.50)
    somme_sf = sum(s.valeur for s in qual.csf_signaux)
    bd.bonus_csf = min(50.0, somme_sf * mult_syn)
    bd.csf_norm = bd.bonus_csf / 50.0

    # Ghost D catalogue formel 42/42 (GHOST_D_CATALOG) — alimente tocard_score.
    nb_sf_positifs = sum(1 for s in qual.csf_signaux if s.valeur > 0)
    # Ghost D catalogue formel 42/42 (app.engine.ghost_d.GHOST_D_CATALOG)
    ghost_d_somme, ghost_d_flags, ghost_d_contrib = compute_ghost_d(
        cheval, race, champ, cheval.icp_global, bd.iff_v2, bd.module_terrain_dyn, bd.mpa_champ,
        bd.module_poids, bd.module_recul, bd.module_dist_adapt, bd.tandem_final, bd.flags, nb_sf_positifs,
        [s.id for s in qual.signaux_catalogue],
        h2h_norm=float(bd.h2h_norm or 0.0),
    )
    qual.tocard_somme_d = ghost_d_somme
    bd.flags.extend(ghost_d_flags)
    # Exposition audit / GMO / P5P6 : id catalogue + valeur réelle tocard
    for gf, gval in ghost_d_contrib:
        if not gf.startswith("D") or gf.startswith("D46"):
            continue
        gid = gf.split("_")[0]
        if any(s.get("id") == gid for s in bd.signaux_actifs):
            # cumuler si même ID déjà présent (variantes)
            for s in bd.signaux_actifs:
                if s.get("id") == gid:
                    s["valeur_brute"] = float(s.get("valeur_brute") or 0.0) + float(gval)
                    s["justification"] = f"{s.get('justification', '')}|{gf}".strip("|")
                    break
            continue
        bd.signaux_actifs.append({
            "id": gid,
            "valeur_brute": float(gval),
            "catalog": "B",
            "famille": "D",
            "is_gamma": False,
            "justification": gf,
            "confiance": "STRICT" if "STRICT" in gf else "DEGRADE",
            "label": __import__("app.engine.ghost_d", fromlist=["GHOST_D_CATALOG"]).GHOST_D_CATALOG.get(gid, gid),
        })

    # tocard_score v2 (P1–P3) : soft_cap(ΣD_dédup)*m_bande + 0.15*LS + 0.10*PDQ + 0.06*SDR + overbet
    ls_max = 0.0
    if getattr(qual, "ls_final_par_famille", None):
        try:
            ls_max = max(qual.ls_final_par_famille.values()) if qual.ls_final_par_famille else 0.0
        except Exception:
            ls_max = 0.0
    tocard, tocard_meta = compute_tocard_score_v2(
        ghost_d_somme_raw=ghost_d_somme,
        ghost_d_contrib=ghost_d_contrib,
        ls_final=ls_max,
        cheval=cheval,
        overbet_bool=bool(getattr(qual, "tocard_overbet_souscote", False)),
    )
    # Alimenter PDQ/SDR déterministes (transparence audit / LLM)
    qual.tocard_pdq = float(tocard_meta["pdq"])
    qual.tocard_sdr = float(tocard_meta["sdr"])
    bd.tocard_score = tocard
    if tocard_meta.get("skipped"):
        bd.flags.append("TOCARD_V2:SKIP_T1T2|tocard=0")
    else:
        bd.flags.append(
            f"TOCARD_V2:{tocard_meta['tier']}"
            f"|band={tocard_meta['band']}"
            f"|Σd={tocard_meta['sigma_d_dedup']:.2f}"
            f"|√={tocard_meta['soft_cap_sqrt']:.2f}"
            f"|ls={tocard_meta['ls_final']:.2f}"
            f"|pdq={tocard_meta['pdq']:.2f}"
            f"|sdr={tocard_meta['sdr']:.2f}"
        )
        if tocard_meta["tier"] in ("UTILE", "FORT"):
            bd.flags.append(f"TOCARD_TIER_{tocard_meta['tier']}")

    return bd


def apply_overbet_second_pass(cheval: Cheval, breakdown: ModuleBreakdown,
                               ordre_score_initial: float, nb_partants: int,
                               allocation_eur) -> None:
    """Module O -- appliqué APRÈS le premier calcul d'ORDRE_SCORE (anti-
    circularité, séquence Étape A-D). Modifie breakdown en place."""
    delta_pch, delta_tocard, flags, ecart = M.module_o_overbet(cheval, ordre_score_initial, nb_partants, allocation_eur)
    breakdown.overbet_pch_delta = delta_pch
    breakdown.overbet_ecart = ecart
    breakdown.pch_final = clamp(0, 220, breakdown.pch_final + delta_pch)
    breakdown.pch_norm = breakdown.pch_final / 220.0
    # Tocards reste à 0 sur T1/T2 même après OVERBET
    if float(breakdown.tocard_score or 0) > 0 or delta_tocard:
        # n'appliquer delta tocard que si déjà dans le périmètre T3/T4
        from app.engine.tranches import classify_tranche
        tr = classify_tranche(cheval.cote_matin, getattr(cheval, "cote_avant_course", None) or cheval.cote_matin)
        tr_v = tr.value if tr is not None else ""
        if tr_v not in ("T1", "T2"):
            breakdown.tocard_score = clamp(0.0, 1.0, breakdown.tocard_score + delta_tocard)
        else:
            breakdown.tocard_score = 0.0
            breakdown.flags.append("OVERBET_TOCARD_SKIP_T1T2")
    breakdown.flags.extend(flags)

    # --- Ghost D40 (Partie 4.4) -- nécessite l'écart OVERBET, connu
    # seulement à cette 2e passe (contrairement aux autres signaux D,
    # calculés en 1re passe dans compute_module_breakdown). Seuil FIXE
    # -0.15 du texte source, distinct du seuil dynamique interne au
    # module (0.10/0.15 selon allocation) qui pose OVERBET_SOUSCOTE.
    cote = cheval.cote_avant_course or cheval.cote_matin
    try:
        cote_f = float(cote) if cote is not None else None
    except (TypeError, ValueError):
        cote_f = None
    # D40 / boost tocard : strictement T3/T4 (cote ≥ 15)
    if ecart is not None and ecart <= -0.15 and cote_f is not None and cote_f >= 15:
        breakdown.tocard_score = clamp(0.0, 1.0, breakdown.tocard_score + 0.10)
        breakdown.flags.append("D40")
        if not any(s.get("id") == "D40" for s in breakdown.signaux_actifs):
            breakdown.signaux_actifs.append({
                "id": "D40", "valeur_brute": 0.10, "catalog": "B",
                "famille": "D", "is_gamma": False,
                "justification": "OVERBET sous-cote <= -0.15", "confiance": "STRICT",
            })


def apply_rah163_ferrure_sov_guard(cheval: Cheval, breakdown: ModuleBreakdown, sov_v2: float) -> None:
    """RAH-163 (porté depuis la lignée hardened, 11/09/2026) -- garde-fou
    anti-double-comptage entre le malus ferrure de STAB (poste S4a, module_f_stab)
    et SOV_v2 (mouvement de marché, engine/synthesis.py::compute_sov_v2).

    Un changement de ferrure peut à la fois (a) déclencher le malus fixe S4a
    dans STAB et (b) provoquer lui-même le mouvement de cote qui alimente
    SOV_v2 -- le même événement serait alors compté deux fois. Appelée
    seulement après que SOV_v2 est connu (2e passe, comme OVERBET), donc
    APRÈS compute_module_breakdown() dans race_pipeline.py.

    Ne nécessite aucune nouvelle donnée scrapée (cheval.ferrure_changes existe
    déjà, cf. app/scraping/turfoo.py) -- contrairement à RAH-235/237/246,
    qui restent bloquées faute de source réelle.
    """
    fc = cheval.ferrure_changes or 0
    if fc < 1 or sov_v2 == 0.0:
        return  # NOT_APPLICABLE (pas de changement de ferrure, ou SOV neutre -- pas de recoupement)

    s4a = -12.0 if fc >= 2 else -5.0
    reduction = abs(s4a) * 0.30  # même taux que la source (réduction de 30%)
    breakdown.stab_pch = clamp(-20.0, 0.0, breakdown.stab_pch + reduction)
    breakdown.rah163_ferrure_reduction = reduction
    breakdown.flags.append("RAH163_REDUCTION_30")
