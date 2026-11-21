"""
gmo_v.py -- Module GMO-V (Partie 17.8, Bloc 8 des instructions v1.22.2-test)

Opérationnalisation de la "méthode des branches dominantes" : le
protocole demande une approximation de P(Top5 ⊆ S) par développement
récursif des chevaux de plus forte probabilité. Nous l'implémentons
comme un calcul EXACT sous un modèle de Plackett-Luce (tirage séquentiel
pondéré par p_i, sans remise) -- un choix statistique standard pour ce
type de problème et strictement plus rigoureux que l'approximation
manuelle décrite dans le texte source, tout en restant fidèle à son
principe ("développement récursif", "masse résiduelle").
"""
from __future__ import annotations
from typing import List, Dict, Tuple, Optional, FrozenSet
from functools import lru_cache

from app.models import HorseScore, RaceContext, QualitativeSignals, Tranche
from app.engine.common import clamp



# =============================================================================
# Couche HYBRIDE v1.29.30 (P1–P6) — capture Top5 sans refonte totale
# =============================================================================
# P1: contraintes quota/marché dans le greedy + repair sous garde Σq
# P2: score q_i ≈ P(i∈Top5) dans le gain greedy
# P3: marché allégé dans p + ICP une seule fois (pas double p_boost)
# P4: p_boost plafonné (≤4 leviers effectifs via clamp produit)
# P5: axes Force / Edge / Upside pour orienter T12 vs T34
# P6: poids calibrables (env ou défauts) pour micro-apprentissage walk-forward
# =============================================================================

import os as _os_hybrid

def discipline_internal_mix(discipline) -> Dict[str, int]:
    """Cibles internes ticket 8 (validées 01/10/2026, stats Open-pmu 142 courses).

    Structure type :
      attelé  : 3 T1 + 2 T2 + 2 T3 + 1 T4
      plat/haies : 2 T1 + 2 T2 + 2 T3 + 1 T4  (min 1 T4 obligatoire)
      steeple/défaut : proche plat, min 1 T4

    Bornes bande T12/T34 restent [3,5]/[3,5].
    """
    from app.engine.common import disc_bucket
    try:
        bucket = disc_bucket(discipline)
    except Exception:
        bucket = "PLAT"
    if bucket == "TROT":
        return {"t1_max": 3, "t1_target": 3, "t2_min": 1, "t2_target": 2,
                "t3_target": 2, "t4_min": 1, "t4_max": 2, "t4_target": 1}
    # PLAT / OBSTACLE (haies, steeple)
    return {"t1_max": 3, "t1_target": 2, "t2_min": 1, "t2_target": 2,
            "t3_target": 2, "t4_min": 1, "t4_max": 2, "t4_target": 1}


def _hybrid_weights(discipline: Optional[str] = None) -> Dict[str, float]:
    """Poids calibrables (P6) + biais discipline (stats Quinté 2014-2026).

    Favori dans Top5 : trot ~72 %, plat ~59 %, obstacle ~54-59 %
    → plus de poids marché au trot ; plus d'upside/tocard en obstacle.
    """
    def _f(key: str, default: float, lo: float, hi: float) -> float:
        raw = _os_hybrid.environ.get(key)
        if raw is None or raw == "":
            return default
        try:
            return max(lo, min(hi, float(raw)))
        except ValueError:
            return default
    disc = (discipline or "").upper()
    # défauts
    q_mkt, q_toc, mmin = 0.25, 0.10, 2.0
    if "TROT" in disc or "ATTEL" in disc or "MONT" in disc:
        q_mkt, q_toc, mmin = 0.32, 0.08, 2.0   # favoris plus fiables Top5
    elif "HAIE" in disc or "STEEPLE" in disc or "OBSTACLE" in disc:
        q_mkt, q_toc, mmin = 0.18, 0.18, 1.0   # marché moins fiable
    elif "PLAT" in disc:
        q_mkt, q_toc, mmin = 0.22, 0.14, 2.0
    return {
        "w_pl": _f("HYBRID_W_PL", 0.42, 0.25, 0.60),
        "w_q": _f("HYBRID_W_Q", 0.38, 0.20, 0.50),
        "w_pb": _f("HYBRID_W_PB", 0.20, 0.10, 0.35),
        "q_ordre": _f("HYBRID_Q_ORDRE", 0.40, 0.25, 0.60),
        "q_market": _f("HYBRID_Q_MARKET", q_mkt, 0.10, 0.45),
        "q_op": _f("HYBRID_Q_OP", 0.18, 0.05, 0.35),
        "q_tocard": _f("HYBRID_Q_TOCARD", q_toc, 0.00, 0.30),
        "q_mid_outsider": _f("HYBRID_Q_MID", 0.12, 0.0, 0.25),  # sweet spot 8-20
        "repair_eps": _f("HYBRID_REPAIR_EPS", 0.02, 0.0, 0.10),
        "market_min": _f("HYBRID_MARKET_MIN", mmin, 1.0, 3.0),
    }


def _z_norm(vals: List[float]) -> List[float]:
    """Normalisation min-max dans le champ (0..1). Constant → 0.5."""
    if not vals:
        return []
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-12:
        return [0.5] * len(vals)
    return [(v - lo) / (hi - lo) for v in vals]


def _harville_top5_mass(win_p: List[float], k: int = 5) -> List[float]:
    """Approx P(i in Top-k) via heuristique type Harville/Bradley-Terry.

    P(place-ish) ∝ p_i * (1 + sum_{j≠i} p_j/(1-p_j) normalisé) — version légère
    stable pour N=12-18 sans énumération C(N,5).
    """
    n = len(win_p)
    if n == 0:
        return []
    s = sum(win_p) or 1.0
    p = [max(1e-9, x / s) for x in win_p]
    # Masse "survivre" approximée : favoris ont plus de chances d'être dans le top k
    # Formule empirique calibrée : q_i ∝ p_i^α avec α<1 pour aplatir vers Top5
    alpha = 0.72 if n >= 14 else 0.80
    raw = [x ** alpha for x in p]
    # Mid-field lift: cotes implicites 8-20 (p entre ~0.04 et 0.11)
    for i, pi in enumerate(p):
        if 0.04 <= pi <= 0.12:
            raw[i] *= 1.12
        elif pi < 0.02:  # extrêmes
            raw[i] *= 0.85
    t = sum(raw) or 1.0
    return [x / t for x in raw]


def compute_q_top5(
    horses: List[HorseScore],
    op_scores: Optional[List[float]] = None,
    weights: Optional[Dict[str, float]] = None,
    win_p: Optional[List[float]] = None,
) -> List[float]:
    """P2+ — Proxy P(i ∈ Top5) : ordre + marché + op + tocard + Harville + mid-outsider."""
    w = weights or _hybrid_weights()
    n = len(horses)
    ordre = [max(0.0, float(h.synthesis.ordre_final or 0.0)) for h in horses]
    market = []
    cotes = []
    for h in horses:
        cote = h.cheval.cote_avant_course or h.cheval.cote_matin
        cotes.append(float(cote) if cote is not None else None)
        if cote is not None and float(cote) > 1.01:
            market.append(max(0.02, min(0.85, 1.35 / (float(cote) ** 0.85))))
        else:
            market.append(0.0)
    op = list(op_scores) if op_scores and len(op_scores) == n else [0.0] * n
    tocard = []
    mid = []
    for i, h in enumerate(horses):
        ts = float(h.breakdown.tocard_score or 0.0) if h.breakdown else 0.0
        tr = h.synthesis.tranche if h.synthesis else None
        from app.engine.synthesis import _tocard_mult
        ts *= _tocard_mult(tr)
        if tr is not None and tr.value in ("T3", "T4a", "T4b", "T4A", "T4B"):
            tocard.append(ts)
        else:
            tocard.append(ts * 0.35)
        # Sweet spot outsider 8-20 (stats Quinté : value / présence Top5)
        c = cotes[i]
        if c is not None and 8.0 <= c <= 20.0:
            mid.append(1.0)
        elif c is not None and 20.0 < c <= 35.0:
            mid.append(0.45)
        else:
            mid.append(0.0)
    zo, zm, zop, zt, zmid = (
        _z_norm(ordre), _z_norm(market), _z_norm(op), _z_norm(tocard), _z_norm(mid)
    )
    q_w = w.get("q_mid_outsider", 0.10)
    # renormaliser les 4 premiers poids pour laisser place au mid
    base_sum = w["q_ordre"] + w["q_market"] + w["q_op"] + w["q_tocard"] + q_w
    q = []
    for i in range(n):
        q.append(
            (w["q_ordre"] * zo[i]
             + w["q_market"] * zm[i]
             + w["q_op"] * zop[i]
             + w["q_tocard"] * zt[i]
             + q_w * zmid[i]) / max(base_sum, 1e-9)
        )
    # Blend Harville si win_p fourni
    if win_p is not None and len(win_p) == n:
        hv = _harville_top5_mass(win_p, k=5)
        q = [0.70 * q[i] + 0.30 * hv[i] for i in range(n)]
    s = sum(q) or 1.0
    return [x / s for x in q]


def compute_axes(
    horses: List[HorseScore],
    q_top5: List[float],
) -> Dict[str, List[float]]:
    """P5 — Force / Edge / Upside (normalisés 0..1)."""
    n = len(horses)
    force = _z_norm([max(0.0, float(h.synthesis.ordre_final or 0.0)) for h in horses])
    # Edge: ordre relatif vs rang de cote (positif = sous-cote / value)
    by_cote = sorted(
        range(n),
        key=lambda i: (
            (horses[i].cheval.cote_avant_course or horses[i].cheval.cote_matin) is None,
            float(horses[i].cheval.cote_avant_course or horses[i].cheval.cote_matin or 999),
        ),
    )
    rank_cote = {idx: r for r, idx in enumerate(by_cote)}
    by_ordre = sorted(range(n), key=lambda i: -float(horses[i].synthesis.ordre_final or 0.0))
    rank_ordre = {idx: r for r, idx in enumerate(by_ordre)}
    edge_raw = []
    for i in range(n):
        # rang cote bas (favori) vs rang ordre: si ordre meilleur que cote → edge+
        edge_raw.append(float(rank_cote[i] - rank_ordre[i]))
    edge = _z_norm(edge_raw)
    upside = []
    for i, h in enumerate(horses):
        ts = float(h.breakdown.tocard_score or 0.0) if h.breakdown else 0.0
        tr = h.synthesis.tranche if h.synthesis else None
        from app.engine.synthesis import _tocard_mult
        ts *= _tocard_mult(tr)
        sig = 1.0 if (h.breakdown and h.breakdown.signaux_actifs) else 0.0
        upside.append(0.70 * ts + 0.30 * sig + 0.15 * q_top5[i])
    upside = _z_norm(upside)
    return {"force": force, "edge": edge, "upside": upside}


def hybrid_candidate_score(
    idx: int,
    tranche_val: Optional[str],
    q_i: float,
    p_boost_i: float,
    axes: Dict[str, List[float]],
) -> float:
    """Score d'orientation T12 (force+edge) vs T34 (upside) pour départager."""
    f = axes["force"][idx]
    e = axes["edge"][idx]
    u = axes["upside"][idx]
    if tranche_val in ("T1", "T2"):
        return 0.50 * q_i + 0.30 * f + 0.20 * e + 0.10 * p_boost_i
    if tranche_val in ("T3", "T4a", "T4b", "T4A", "T4B"):
        return 0.40 * q_i + 0.40 * u + 0.20 * p_boost_i
    return 0.50 * q_i + 0.30 * p_boost_i + 0.20 * f




def normalized_win_probabilities(
    horses: List[HorseScore],
    market_blend: float = 0.30,
    operational_probs: Optional[List[float]] = None,
    use_top5_market_prior: bool = True,
) -> List[float]:
    """p_i = une seule couche marché + optionnel modèle opérationnel.

    Correctif 14/09/2026 (double dose marché) :
    - PROXY = 50% op + 50% composite (SANS marché) si operational_probs fourni
    - Puis UNE application de market_blend (prior Top5 1.35/cote^0.85)
    Évite le triple comptage marché (ORDRE + PROXY + blend champ).
    """
    composites = [max(0.0, h.synthesis.composite) for h in horses]
    c_total = sum(composites) or 1.0
    c_norm = [c / c_total for c in composites]

    market = []
    for h in horses:
        cote = h.cheval.cote_avant_course or h.cheval.cote_matin
        if cote is not None and cote > 1.01:
            if use_top5_market_prior:
                market.append(max(0.02, min(0.85, 1.35 / (float(cote) ** 0.85))))
            else:
                market.append(1.0 / float(cote))
        else:
            market.append(0.0)
    m_total = sum(market)
    m_norm = [m / m_total for m in market] if m_total > 1e-12 else [0.0] * len(horses)

    # PROXY sans marché : op + composite uniquement
    base = c_norm
    if operational_probs is not None and len(operational_probs) == len(horses):
        op = [max(0.0, float(x)) for x in operational_probs]
        op_t = sum(op) or 1.0
        op_n = [x / op_t for x in op]
        base = [0.50 * o + 0.50 * c for o, c in zip(op_n, c_norm)]
        bt = sum(base) or 1.0
        base = [b / bt for b in base]

    # Une seule couche marché (calibrée par taille de champ)
    if m_total > 1e-12 and market_blend > 0:
        alpha = clamp(0.0, 0.50, market_blend)
        mixed = [(1 - alpha) * b + alpha * m for b, m in zip(base, m_norm)]
        t = sum(mixed) or 1.0
        return [x / t for x in mixed]
    return base


def apply_longshot_adjustment(p: List[float], ls_final: List[float]) -> List[float]:
    """Ajustement Longshot (T3/T4) :
    - LS_FINAL >= 0.50 → boost plein (T4 / multi-familles)
    - LS_FINAL >= 0.35 → boost réduit (T3 utiles)
    puis renormalisation."""
    adjusted = []
    for pi, ls in zip(p, ls_final):
        if ls is not None and ls >= 0.50:
            adjusted.append(pi * (1 + min(0.5, ls * 0.5)))
        elif ls is not None and ls >= 0.35:
            adjusted.append(pi * (1 + min(0.25, ls * 0.30)))
        else:
            adjusted.append(pi)
    total = sum(adjusted) or 1.0
    return [a / total for a in adjusted]


def _prob_top5_subset(p: Tuple[float, ...], subset_idx: FrozenSet[int], all_idx: Tuple[int, ...],
                       k: int = 5) -> float:
    """P(les k premières places d'un tirage séquentiel pondéré par p,
    sans remise, appartiennent toutes à subset_idx), calculé exactement
    par récursion sur le poids total restant."""

    @lru_cache(maxsize=None)
    def rec(remaining: FrozenSet[int], k_left: int, w_total_key: float) -> float:
        if k_left == 0:
            return 1.0
        in_subset = [i for i in remaining if i in subset_idx]
        if not in_subset:
            return 0.0
        w_total = sum(p[i] for i in remaining)
        if w_total <= 1e-12:
            return 0.0
        total = 0.0
        for i in in_subset:
            w_i = p[i]
            prob_i_next = w_i / w_total
            total += prob_i_next * rec(remaining - {i}, k_left - 1, round(w_total - w_i, 10))
        return total

    result = rec(frozenset(all_idx), k, 1.0)
    rec.cache_clear()
    return result


def prob_top5_in_set(p: List[float], candidate_indices: List[int], all_indices: List[int]) -> float:
    if len(candidate_indices) < 5:
        return 0.0
    # v1.29.41 : une seule DP exacte par course (pl_inclusion), résultat identique à
    # la récursion historique (vérifié par test) mais ~100x plus rapide.
    if len(all_indices) == len(p) and sorted(all_indices) == list(range(len(p))):
        from app.engine.pl_inclusion import coverage
        return coverage(p, candidate_indices)
    return _prob_top5_subset(tuple(p), frozenset(candidate_indices), tuple(all_indices))


def style_bucket(style) -> str:
    if style is None:
        return "INCONNU"
    v = style.value if hasattr(style, "value") else str(style)
    if v.startswith("MENEUR"):
        return "MENEUR"
    return v


def _champ_size(horses: List[HorseScore]) -> int:
    return len(horses)


def _cote_of(h: HorseScore) -> Optional[float]:
    c = h.cheval.cote_avant_course if h.cheval.cote_avant_course is not None else h.cheval.cote_matin
    return float(c) if c is not None else None


def pool_thresholds(n_partants: int) -> tuple:
    """Calibration 13/09/2026 (+reinforcement grand champ)."""
    if n_partants >= 16:
        return 0.18, 0.12, 0.22  # encore plus ouvert dès 16
    if n_partants >= 14:
        return 0.20, 0.15, 0.25
    return 0.25, 0.20, 0.30


def market_blend_for_field(n_partants: int, discipline: Optional[str] = None) -> float:
    """Blend marché adaptatif — v1.29.30 HYBRIDE (P3) : allégé car contrainte
    marché soft (≥2/3) s'applique en sélection. <14 → 12% | 14-15 → 16% | >=16 → 18%.
    Trot >=14 : +2 pts (cap 0.22)."""
    if n_partants >= 16:
        base = 0.18
    elif n_partants >= 14:
        base = 0.16
    else:
        base = 0.12
    disc = (discipline or "").upper()
    if n_partants >= 14 and ("TROT" in disc):
        base = min(0.22, base + 0.02)
    # v1.29.41 : poids marché calibrable depuis les audits (scripts/calibrer_depuis_audits.py)
    _ov = _os_hybrid.environ.get("VANTAGE_MARKET_BLEND")
    if _ov:
        try:
            return max(0.0, min(0.50, float(_ov)))
        except ValueError:
            pass
    return base


def fav_ordre_cap(n_partants: int) -> int:
    if n_partants >= 16:
        return 14
    if n_partants >= 14:
        return 12
    return 10



def softmax_temperature(n_partants: int, discipline: Optional[str] = None) -> float:
    """τ > 1 aplatit les p_i. Trot: moins d'aplatissement (favoris Top5 ~72%).
    Obstacle: plus d'aplatissement (favoris moins fiables)."""
    if n_partants >= 16:
        base = 1.18
    elif n_partants >= 14:
        base = 1.08
    else:
        base = 1.00
    disc = (discipline or "").upper()
    if "TROT" in disc or "ATTEL" in disc or "MONT" in disc:
        base = max(1.0, base - 0.06)  # densifier favoris
    elif "HAIE" in disc or "STEEPLE" in disc:
        base = base + 0.08
    return base


def apply_temperature(p: List[float], tau: float) -> List[float]:
    """p'_i ∝ p_i^(1/τ). τ=1 → identité."""
    if abs(tau - 1.0) < 1e-9 or not p:
        return list(p)
    inv = 1.0 / max(0.05, tau)
    powered = [max(1e-15, float(x)) ** inv for x in p]
    s = sum(powered) or 1.0
    return [x / s for x in powered]


def apply_icp_blend(p: List[float], horses: List[HorseScore], weight: float = 0.05) -> List[float]:
    """Blend conditionnel presse ICP dans p_i (w=0 si aucun ICP renseigné)."""
    icp_raw = []
    any_icp = False
    for h in horses:
        v = h.cheval.icp_pondere if h.cheval.icp_pondere is not None else h.cheval.icp_global
        if v is not None:
            any_icp = True
            icp_raw.append(max(0.0, float(v)))
        else:
            icp_raw.append(0.0)
    if not any_icp or weight <= 0:
        return list(p)
    s = sum(icp_raw)
    if s <= 1e-12:
        return list(p)
    icp_n = [x / s for x in icp_raw]
    w = clamp(0.0, 0.15, weight)
    mixed = [(1 - w) * a + w * b for a, b in zip(p, icp_n)]
    t = sum(mixed) or 1.0
    return [x / t for x in mixed]


def hill_climb_top5(
    p: List[float],
    S: List[int],
    pool: List[int],
    all_indices: List[int],
    protected: FrozenSet[int],
    max_rounds: int = 20,
) -> Tuple[List[int], int, float]:
    """Échanges 1-pour-1 maximisant P_PL(Top5 ⊂ S) sous |S|=8.

    Ne retire jamais un indice `protected` (top marché / favori unanime).
    Retourne (S', n_swaps, p_top5_final).
    """
    if len(S) < 5:
        return list(S), 0, prob_top5_in_set(p, S, all_indices)
    current = list(S)
    best = prob_top5_in_set(p, current, all_indices)
    swaps = 0
    for _ in range(max_rounds):
        improved = False
        for out_i in list(current):
            if out_i in protected:
                continue
            for in_i in pool:
                if in_i in current:
                    continue
                trial = [in_i if x == out_i else x for x in current]
                sc = prob_top5_in_set(p, trial, all_indices)
                if sc > best + 1e-12:
                    best = sc
                    current = trial
                    swaps += 1
                    improved = True
                    break
            if improved:
                break
        if not improved:
            break
    return current, swaps, best


def _by_cote_indices(horses: List[HorseScore]) -> List[int]:
    return sorted(
        range(len(horses)),
        key=lambda i: (_cote_of(horses[i]) is None, _cote_of(horses[i]) or 999.0),
    )


def build_pool_elargi(horses: List[HorseScore], qualitatifs: List[QualitativeSignals],
                      trace: list | None = None) -> List[int]:
    """Étape 11.a -- Pool Élargi (12-14 chevaux), seuils champ-dépendants.
    Dès 14 partants : top-2 cotes toujours dans le pool.
    """
    n = _champ_size(horses)
    th_ordre, th_tocard, th_p5p6 = pool_thresholds(n)
    eligible = []
    reasons: Dict[int, List[str]] = {i: [] for i in range(len(horses))}
    for i, (h, q) in enumerate(zip(horses, qualitatifs)):
        if h.synthesis.ordre_final >= th_ordre:
            reasons[i].append("ordre_final")
        if h.breakdown.tocard_score >= th_tocard:
            reasons[i].append("tocard_score")
        if h.breakdown.p5p6_score >= th_p5p6:
            reasons[i].append("p5p6_score")
        if q.supra_omission_candidate:
            reasons[i].append("supra_omission")
        if q.bonus_ssfo >= 5:
            reasons[i].append("bonus_ssfo")
        ok = bool(reasons[i])
        # Mid-cote (8-25) avec ORDRE correct : élargit le pool sur grands champs
        cote = _cote_of(h)
        if not ok and n >= 14 and cote is not None and 8.0 <= cote <= 25.0:
            if h.synthesis.ordre_final >= th_ordre - 0.05:
                ok = True
                reasons[i].append("mid_cote_ordre")
        if ok:
            eligible.append(i)
    eligible.sort(key=lambda i: horses[i].synthesis.ordre_final, reverse=True)
    if len(eligible) < 8:
        rest = sorted([i for i in range(len(horses)) if i not in eligible],
                      key=lambda i: horses[i].synthesis.ordre_final, reverse=True)
        fallback = rest[: max(0, 8 - len(eligible))]
        eligible += fallback
        for i in fallback:
            reasons[i].append("fallback_pool_min_8")
    # Top-2 marché toujours dans le pool si N≥14 (sinon favori T1 seul)
    by_cote = _by_cote_indices(horses)
    n_market = 2 if n >= 14 else 1
    try:
        from app.engine.gru_signals import gru_pepite_score_of, gru_piege_score_of, _gp
        th_skip = _gp("VANTAGE_GRU_PIEGE_SKIP_MF", 6.0)          # v1.29.64 maîtrisé (proposé 5.0)
        th_pep = _gp("VANTAGE_GRU_POOL_PEPITE_TH", 8.0)          # v1.29.64 maîtrisé (proposé 5.5 / 6.5 : admettait 82 % des outsiders)
        max_pep = int(_gp("VANTAGE_GRU_POOL_MAX_ENTRIES", 2))
    except Exception:       # noqa: BLE001
        gru_pepite_score_of = gru_piege_score_of = None; th_skip, th_pep, max_pep = 99.0, 99.0, 0
    market_forced = []
    for rang_m, fav_i in enumerate(by_cote[:n_market]):
        cote = _cote_of(horses[fav_i])
        if cote is not None and cote <= 12.0 and fav_i not in eligible:
            # favori à piège GRU fort : plus injecté de force, SAUF le favori n°1 du marché
            if gru_piege_score_of is not None and rang_m > 0 and gru_piege_score_of(horses[fav_i]) >= th_skip:
                horses[fav_i].breakdown.flags.append("GRU_PIEGE_SKIP_MARKET_FORCE")
                reasons[fav_i].append("marche_force_ignore_gru_piege")
                continue
            eligible.append(fav_i)
            market_forced.append(fav_i)
            reasons[fav_i].append(f"marche_force_top{rang_m + 1}")
    # Droit d'entrée « pépite » : au plus `max_pep` outsiders (cote ≥ 12) au score GRU maximal, jamais au-delà de 14 places
    pool = eligible[:14]
    # Le commentaire historique promettait les favoris du marché dans le pool;
    # les réinsérer après le cap évite qu’ils soient ajoutés en dernière place
    # puis immédiatement coupés lorsque 14 chevaux étaient déjà éligibles.
    for fav_i in market_forced:
        if fav_i in pool:
            continue
        remplaçables = [i for i in pool if i not in market_forced]
        if remplaçables:
            eject = min(remplaçables, key=lambda i: horses[i].synthesis.ordre_final)
            pool.remove(eject)
            reasons[eject].append("evince_cap_pool_pour_marche")
            pool.append(fav_i)
            horses[fav_i].breakdown.flags.append("POOL_MARKET_FAVORI_RESERVE")
    for i in eligible:
        if i not in pool:
            reasons[i].append("cap_pool_14")
    if gru_pepite_score_of is not None and max_pep > 0:
        cands = [i for i in range(len(horses)) if i not in pool and (_cote_of(horses[i]) or 0.0) >= 12.0
                 and gru_pepite_score_of(horses[i]) >= th_pep]
        cands.sort(key=lambda i: (-gru_pepite_score_of(horses[i]), -horses[i].synthesis.ordre_final))
        entrees = cands[:max_pep]
        for i in entrees:
            remplaçables = [j for j in pool if j not in market_forced]
            if len(pool) >= 14 and not remplaçables:
                reasons[i].append("gru_pepite_refuse_pool_protege")
                continue
            if len(pool) >= 14 and remplaçables:
                eject = min(remplaçables, key=lambda j: horses[j].synthesis.ordre_final)
                pool.remove(eject)
                reasons[eject].append("evince_cap_pool_pour_gru_pepite")
            pool.append(i)
            reasons[i].append("gru_pepite")
            horses[i].breakdown.flags.append("GRU_POOL_PEPITE")
    if trace is not None:
        admitted = set(pool)
        trace.extend({
            "numero": horses[i].cheval.numero,
            "admis_pool_final": i in admitted,
            "motifs": reasons[i] or ["aucun_critere_admission"],
            "exclusion": ("cap_pool_14" if "cap_pool_14" in reasons[i] else
                          ("gru_pepite_refuse_pool_protege" if "gru_pepite_refuse_pool_protege" in reasons[i] else
                           ("hors_criteres" if not any(r.startswith("marche_force") for r in reasons[i]) else
                            "non_admis_apres_regle_marche"))) if i not in admitted else None,
        } for i in range(len(horses)))
    return pool


def compute_potential_score(idx: int, horses: List[HorseScore], qualitatifs: List[QualitativeSignals]) -> float:
    """Score de potentiel outsider enrichi le 12/09/2026 : ajoute SSFO
    et P5P6 (déjà calculés en amont) pour mieux booster les T3/T4 qui
    ont une vraie densité de signaux faibles plutôt que seulement SUPRA
    + tocard + Ghost."""
    q = qualitatifs[idx]
    h = horses[idx]
    score_sim = q.supra_score_sim or 0.0
    score_sim_norm = min(1.0, score_sim / 0.70)
    tocard_norm = min(1.0, h.breakdown.tocard_score / 0.35)
    # v1.29.72 : multiplicateur appliqué UNE seule fois (le bloc était recopié trois fois : ×0,75³ au lieu de ×0,75)
    tr = h.synthesis.tranche if h.synthesis else None
    from app.engine.synthesis import _tocard_mult
    tocard_norm *= _tocard_mult(tr)
    # Ghost D (compute_ghost_d) est journalisé en FLAGS ("D01_STRICT", "D41"…)
    # et non dans signaux_actifs (réservé au catalogue B/M/GAMMA). Compter
    # les deux sources pour ne pas perdre la convergence réelle (bug de
    # branchement corrigé le 12/09/2026).
    flags = h.breakdown.flags or []
    d46_actif = 1.0 if (
        any(s.get("id") == "D46" for s in h.breakdown.signaux_actifs)
        or any(f.startswith("D46") for f in flags)
    ) else 0.0
    ghost_from_catalog = sum(
        1 for s in h.breakdown.signaux_actifs
        if str(s.get("id", "")).startswith("D") and s.get("id") != "D46"
    )
    ghost_from_flags = sum(
        1 for f in flags
        if f.startswith("D") and not f.startswith("D46")
        and f not in ("DISQUALIFIE",)  # incident musique, pas Ghost D
        and not f.startswith("DQ")
    )
    # Dédoublonnage approximatif : on prend le max des deux sources
    nb_ghost = max(ghost_from_catalog, ghost_from_flags)
    d_convergence = 1.0 if nb_ghost >= 3 else 0.0
    ssfo_norm = min(1.0, (q.bonus_ssfo or 0.0) / 6.0)          # 6 ≈ seuil "bon" SSFO
    p5p6_norm = min(1.0, (h.breakdown.p5p6_score or 0.0) / 0.50)
    # Match style × rythme (MODULE_L / levier 3) : mpa_champ ∈ [-20, 20]
    # → normalisé 0..1 autour de 0 (match positif = boost outsider)
    mpa = h.breakdown.mpa_champ or 0.0
    scenario_norm = max(0.0, min(1.0, (mpa + 5.0) / 25.0))  # -5→0, +20→1
    # Pondération recalibrée 12/09 : SUPRA 25%, tocard 20%, Ghost 12%,
    # SSFO 13%, P5P6 13%, scénario style×rythme 12%, D46 5%
    return (0.25 * score_sim_norm + 0.20 * tocard_norm + 0.12 * d_convergence
            + 0.05 * d46_actif + 0.13 * ssfo_norm + 0.13 * p5p6_norm
            + 0.12 * scenario_norm)


def compute_p_boost(idx: int, horses: List[HorseScore], qualitatifs: List[QualitativeSignals],
                     p_top5: List[float], n_partants: int = 0) -> float:
    tranche = horses[idx].synthesis.tranche
    base = p_top5[idx]
    if tranche in (Tranche.T3, Tranche.T4A, Tranche.T4B):
        potential = compute_potential_score(idx, horses, qualitatifs)
        # Grand champ : seuil potentiel plus bas pour densifier les outsiders
        th = 0.32 if n_partants >= 14 else 0.40
        mult = 0.35 if n_partants >= 14 else 0.30
        if potential >= th:
            return base * (1 + mult * potential)
    # T2 Value : boost des meilleurs semi-favoris (module t2_value_score)
    if tranche == Tranche.T2:
        bd = horses[idx].breakdown
        t2v = float(getattr(bd, "t2_value_score", 0.0) or 0.0) if bd else 0.0
        if t2v >= 0.55:
            return base * (1.0 + 0.18 * t2v)  # jusqu'à ~+18%
        if t2v >= 0.40:
            return base * (1.0 + 0.12 * t2v)
        if t2v >= 0.30:
            return base * (1.0 + 0.06 * t2v)
    # Mid-cote non classé T3/T4 : petit boost si grand champ
    if n_partants >= 14:
        cote = _cote_of(horses[idx])
        if cote is not None and 8.0 <= cote <= 20.0 and tranche not in (Tranche.T2,):
            return base * 1.08
    return base


def run_gmo_v(race: RaceContext, horses: List[HorseScore],
              qualitatifs: List[QualitativeSignals]) -> Dict:
    from app.models import Signature
    # cap_style retiré v1.29.10 (diversité stylistique NON_APPLICABLE)

    all_indices = list(range(len(horses)))
    n_partants = len(horses)
    disc = getattr(race.discipline, "value", None) or str(getattr(race, "discipline", "") or "")
    pool_trace: List[Dict] = []
    pool = build_pool_elargi(horses, qualitatifs, trace=pool_trace)
    flags: List[str] = []

    # Modèle opérationnel v1.1-TOP5 (scores pour PROXY_BLENDED + p_boost)
    from app.engine.operational_model import apply_operational_model, score_horse
    from app.engine.musique_features import score_musique_composite, forme_boost_mult, forme_boost_mult_disc
    op_manifest = apply_operational_model(horses, weight=0.25)
    op_probs = op_manifest["model_probabilities"]

    blend = market_blend_for_field(n_partants, discipline=disc)
    p_raw = normalized_win_probabilities(
        horses,
        market_blend=blend,
        operational_probs=op_probs,
        use_top5_market_prior=True,
    )
    ls_final = [max(qualitatifs[i].ls_final_par_famille.values(), default=0.0) for i in all_indices]
    p = apply_longshot_adjustment(p_raw, ls_final)

    # --- Recommandations probabilistes 14/09/2026 ---
    # 1) Température τ(N) : aplatit p_i sur grands champs (plus de masse Top5)
    tau = softmax_temperature(n_partants, discipline=disc)
    p = apply_temperature(p, tau)
    # 2) Blend ICP conditionnel (w=0 si aucune presse)
    p = apply_icp_blend(p, horses, weight=0.05)  # P3: une seule dose ICP

    p_boost = [compute_p_boost(i, horses, qualitatifs, p, n_partants=n_partants) for i in all_indices]
    # Classement relatif des T2 : top-2 value du champ reçoivent un surplus
    t2_idx = [
        i for i in all_indices
        if horses[i].synthesis.tranche == Tranche.T2
        and horses[i].breakdown
        and float(getattr(horses[i].breakdown, "t2_value_score", 0) or 0) >= 0.40
    ]
    if len(t2_idx) >= 1:
        t2_idx_sorted = sorted(
            t2_idx,
            key=lambda i: float(horses[i].breakdown.t2_value_score or 0),
            reverse=True,
        )
        for rank, i in enumerate(t2_idx_sorted[:2]):
            bonus = 1.10 if rank == 0 else 1.06
            p_boost[i] *= bonus
            flags.append(
                f"T2_VALUE_TOP{rank+1}_n{horses[i].cheval.numero}"
                f"_v{float(horses[i].breakdown.t2_value_score):.2f}"
            )
    # Soft boost musique + score opérationnel + ICP presse (Fréquence-Turf)
    forme_flags_by_idx: Dict[int, str] = {}
    _PBOOST_UNITS_FIX = _os_hybrid.environ.get("VANTAGE_PBOOST_UNITS_FIX", "1") != "0"
    _op_sum = sum(max(0.0, float(x)) for x in op_manifest["op_scores"]) or 1.0
    _mus_sum = sum(
        score_musique_composite(getattr(h.cheval, "musique", None), getattr(h.cheval, "deferre", None))
        for h in horses
    ) or 1.0
    if _PBOOST_UNITS_FIX:
        flags.append("PBOOST_UNITS_FIX_ACTIF")
    for i in range(len(horses)):
        mus_str = getattr(horses[i].cheval, "musique", None)
        mus = score_musique_composite(mus_str, getattr(horses[i].cheval, "deferre", None))
        op_s = op_manifest["op_scores"][i]
        if _PBOOST_UNITS_FIX:
            # v1.29.41 : p_boost est une PROBABILITÉ (somme ~1) alors que op_s et mus sont
            # des scores 0..1 : l'ancien mélange additif donnait ratio = 0.7 + (0.2*op+0.1*mus)/p,
            # soit >> 1.12 pour presque tous les chevaux -> TOUS saturaient le plafond +12 %
            # et les multiplicateurs suivants (forme, dérive, T2 value, favori unanime,
            # Turf.bzh...) étaient annulés. On mélange maintenant des PARTS (même échelle).
            p_boost[i] = 0.70 * p_boost[i] + 0.20 * (op_s / _op_sum) + 0.10 * (mus / _mus_sum)
        else:
            p_boost[i] = 0.70 * p_boost[i] + 0.20 * op_s + 0.10 * mus
        # ICP (Bloc K) : soutien presse → léger boost capture Top5
        icp = horses[i].cheval.icp_global
        icp_p = horses[i].cheval.icp_pondere
        # P3 v1.29.30: ICP déjà dans apply_icp_blend(p) — pas de double dose sur p_boost
        # Favori unanime: levier forme uniquement (plus bas, borné)
        if horses[i].cheval.favori_unanime:
            p_boost[i] *= 1.03
        # v1.29.20 -- anti-saturation PCH plafond (Argentan : plusieurs 220)
        # Favoris de marché au plafond PCH : léger frein pour différencier
        # et laisser de la place aux semi-outsiders dans le ranking relatif.
        pch = getattr(horses[i].breakdown, "pch_final", None) if horses[i].breakdown else None
        cote_i = horses[i].cheval.cote_avant_course or horses[i].cheval.cote_matin
        if pch is not None and pch >= 210 and cote_i is not None and cote_i < 10.0:
            p_boost[i] *= 0.94
            flags.append(f"PCH_SATURATION_DAMP_n{horses[i].cheval.numero}")
        # v1.29.21 -- un seul "outsider signal boost" (Turf.bzh OU drift),
        # jamais produit des deux (anti-résonance).
        outsider_boost_applied = False
        try:
            sig_ids = {
                (s.get("id") if isinstance(s, dict) else getattr(s, "id", None))
                for s in (qualitatifs[i].signaux_catalogue or [])
            }
            tr = horses[i].synthesis.tranche if horses[i].synthesis else None
            is_t34 = tr in (Tranche.T3, Tranche.T4A, Tranche.T4B)
            if is_t34 and (("B61" in sig_ids) or ("B63" in sig_ids)):
                p_boost[i] *= 1.12
                outsider_boost_applied = True
                flags.append(f"TURFBZH_OUTSIDER_BOOST_n{horses[i].cheval.numero}")
        except Exception:
            sig_ids = set()
            tr = horses[i].synthesis.tranche if horses[i].synthesis else None
            is_t34 = tr in (Tranche.T3, Tranche.T4A, Tranche.T4B) if tr else False

        # SOV / drift (matin → avant) : léger, seulement si pas déjà Turf.bzh
        try:
            from app.engine.synthesis import compute_sov_v2
            sov_val, _sov_flags = compute_sov_v2(horses[i].cheval, tr)
        except Exception:
            sov_val = 0.0
        if not outsider_boost_applied and is_t34 and sov_val >= 0.04:
            p_boost[i] *= 1.05
            flags.append(f"DRIFT_VALUE_BOOST_n{horses[i].cheval.numero}")
        elif tr in (Tranche.T1, Tranche.T2) and sov_val <= -0.08:
            # Favori qui allonge : frein léger (distinct du plafond PCH)
            p_boost[i] *= 0.97
            flags.append(f"DRIFT_FAV_ALLONGE_n{horses[i].cheval.numero}")

        # v1.29.21 -- forme Top5 filtrée par discipline de la course
        tr = horses[i].synthesis.tranche if horses[i].synthesis else None
        tr_val = tr.value if tr is not None else None
        from app.engine.musique_features import (
            forme_boost_mult_disc,
            profil_forme_recente_disc,
        )
        fmult, flabel = forme_boost_mult_disc(mus_str, tr_val, race.discipline)
        p_boost[i] *= fmult
        forme_flags_by_idx[i] = flabel
        profil_disc = profil_forme_recente_disc(mus_str, race.discipline)

        # Router discipline : un seul mult soft (0.96–1.04), anti-stack PCH
        from app.engine.discipline_router import selection_mult
        dmult, dtag = selection_mult(horses[i], race, forme_profil_disc=profil_disc)
        if abs(dmult - 1.0) > 1e-6:
            p_boost[i] *= dmult
            flags.append(f"{dtag}_n{horses[i].cheval.numero}")

        # Favori unanime sans forme (même discipline)
        if (horses[i].cheval.favori_unanime and tr_val == "T1"
                and profil_disc == "MORTE"):
            p_boost[i] *= 0.93
            forme_flags_by_idx[i] = "FAVORI_UNANIME_SURCOTE_SANS_FORME"
            flags.append(f"FAVORI_UNANIME_SURCOTE_SANS_FORME_n{horses[i].cheval.numero}")


    # --- HYBRIDE v1.29.30: q_i, axes, clamp p_boost (P2/P4/P5) ---
    hw = _hybrid_weights(disc)
    flags.append(
        f"HYBRID_WEIGHTS_wpl={hw['w_pl']:.2f}_wq={hw['w_q']:.2f}_wpb={hw['w_pb']:.2f}"
        f"_mktmin={int(hw['market_min'])}"
    )
    # P4 + priorité 6 (29/09/2026) : clamp plus serré anti-empilement mults
    n_clamp_hi = n_clamp_lo = 0
    if _PBOOST_UNITS_FIX:
        # v1.29.41 : p_boost cumule des multiplicateurs > 1 (T3/T4, T2 value, mid-cote...) donc
        # sa somme dérivait (~1.2) alors que p somme à 1 : le ratio p_boost/p était biaisé de +20 %
        # pour TOUS les chevaux. On renormalise avant de comparer, sinon le plafond ±12 %
        # ne mesure plus l'effet relatif des signaux.
        _spb = sum(p_boost) or 1.0
        p_boost = [x / _spb for x in p_boost]
    _p_boost_preclamp = list(p_boost)
    for i in range(len(horses)):
        base_p = p[i] if p[i] > 1e-15 else 1e-15
        ratio = p_boost[i] / base_p
        if ratio > 1.12:
            n_clamp_hi += 1
        if ratio < 0.88:
            n_clamp_lo += 1
        ratio = max(0.88, min(1.12, ratio))
        p_boost[i] = base_p * ratio
    if _PBOOST_UNITS_FIX:
        _spb2 = sum(p_boost) or 1.0
        p_boost = [x / _spb2 for x in p_boost]
    if n_clamp_hi or n_clamp_lo:
        flags.append(f"P_BOOST_CLAMP_112_hi{n_clamp_hi}_lo{n_clamp_lo}")
    q_top5 = compute_q_top5(horses, op_scores=op_manifest.get("op_scores"), weights=hw, win_p=p)
    axes = compute_axes(horses, q_top5)
    flags.append("HYBRID_Q_TOP5_READY")
    # top-3 marché brut (cotes) pour contrainte greedy
    _by_c = _by_cote_indices(horses)
    top3_market_cotes = _by_c[:3]

    S: List[int] = []
    log: List[Dict] = []
    from app.engine.pl_inclusion import inclusion_probs, expected_hits, best_expected_subset
    _pi_model = inclusion_probs(p)          # P(i ∈ Top5) sous le modèle PL final
    _GAIN_NORMALIZED = _os_hybrid.environ.get("GMO_GAIN_NORMALIZED", "0") == "1"
    if _GAIN_NORMALIZED:
        flags.append("GMO_GAIN_NORMALIZED_ACTIF")

    def counts(sel: List[int], key_fn) -> Dict[str, int]:
        d: Dict[str, int] = {}
        for i in sel:
            k = key_fn(i)
            d[k] = d.get(k, 0) + 1
        return d

    def style_key(i):
        return style_bucket(horses[i].cheval.style_mpa)

    def ecurie_key(i):
        return horses[i].cheval.entraineur or f"__inconnu_{i}"

    def tranche_key(i):
        t = horses[i].synthesis.tranche
        return t.value if t else "HORS_TRANCHE"

    for step in range(8):
        candidats = [i for i in pool if i not in S]
        if not candidats:
            break
        gains = []
        if _GAIN_NORMALIZED:
            # v1.29.41 (opt-in GMO_GAIN_NORMALIZED=1) : les 3 termes sont ramenés à la même
            # échelle (z-score sur les candidats). Avant : ΔP(Top5⊂S) valait 0 pour les 4
            # premiers choix et ~1e-3 ensuite, face à q_top5 ~O(1) : l'objectif Plackett-Luce
            # n'influençait pratiquement jamais la sélection (27/30 courses identiques sans lui).
            _zpi = _z_norm([_pi_model[y] for y in candidats])
            _zq = _z_norm([q_top5[y] for y in candidats])
            _zb = _z_norm([p_boost[y] for y in candidats])
            _znorm = {y: (_zpi[k], _zq[k], _zb[k]) for k, y in enumerate(candidats)}
        for y in candidats:
            if _GAIN_NORMALIZED:
                a_, b_, c_ = _znorm[y]
                gain = hw["w_pl"] * a_ + hw["w_q"] * b_ + hw["w_pb"] * c_
                tr_y = horses[y].synthesis.tranche
                trv = tr_y.value if tr_y is not None else None
                gain += 0.05 * hybrid_candidate_score(y, trv, q_top5[y], p_boost[y], axes)
                gains.append((gain, y))
                continue
            delta = prob_top5_in_set(p, S + [y], all_indices) - prob_top5_in_set(p, S, all_indices)
            # P2 v1.29.30: gain hybride ΔP_PL + q_i + p_boost
            gain = hw["w_pl"] * delta + hw["w_q"] * q_top5[y] + hw["w_pb"] * p_boost[y]
            tr_y = horses[y].synthesis.tranche
            trv = tr_y.value if tr_y is not None else None
            gain += 0.05 * hybrid_candidate_score(y, trv, q_top5[y], p_boost[y], axes)
            gains.append((gain, y))
        gains.sort(key=lambda t: t[0], reverse=True)

        # v1.29.10 : style retiré (RAH-07 NON_APPLICABLE). Reste écurie ≤2
        # (anti-concentration écurie) + sous-tranche ≤4 soft, relâchable.
        # Le volume 4+4 par BANDE est géré en post (qualité intra-tranche).
        for relax_level in range(3):  # 0 strict → 1 tranche → 2 écurie
            chosen = None
            for gain, y in gains:
                trial = S + [y]
                ecurie_c = counts(trial, ecurie_key)
                tranche_c = counts(trial, tranche_key)
                ecurie_ok = relax_level >= 2 or all(v <= 2 for v in ecurie_c.values())
                # sous-tranche soft ≤4
                tranche_ok = relax_level >= 1 or all(v <= 4 for v in tranche_c.values())
                # P1 v1.29.30: bandes T12/T34 — ne pas rendre [3,5] impossible
                n_t12 = sum(1 for i in trial if (horses[i].synthesis.tranche and horses[i].synthesis.tranche.value in ("T1", "T2")))
                n_t34 = sum(1 for i in trial if (horses[i].synthesis.tranche and horses[i].synthesis.tranche.value in ("T3", "T4a", "T4b", "T4A", "T4B")))
                steps_left = 7 - step  # après ajout, il restera steps_left places
                # Si ticket presque plein, forcer trajectoire vers [3,5]
                band_ok = True
                if relax_level < 2 and step >= 5:
                    final_t12_min, final_t12_max = n_t12, n_t12 + steps_left
                    final_t34_min, final_t34_max = n_t34, n_t34 + steps_left
                    # doit pouvoir encore atteindre au moins 3 de chaque côté
                    if final_t12_max < 3 or final_t34_max < 3:
                        band_ok = False
                    if final_t12_min > 5 or final_t34_min > 5:
                        band_ok = False
                # P1 marché soft: aux dernières places, exiger progression vers market_min
                market_ok = True
                if relax_level < 2 and step >= 5:
                    n_mkt = sum(1 for i in trial if i in top3_market_cotes)
                    need = int(hw["market_min"])
                    if n_mkt + steps_left < need:
                        market_ok = False
                if ecurie_ok and tranche_ok and band_ok and market_ok:
                    chosen = (gain, y)
                    break
            if chosen:
                if relax_level > 0:
                    flags.append(
                        f"FLAG_CONTRAINTE_LEVEE_niveau_{relax_level}"
                        f"_cheval_{horses[chosen[1]].cheval.numero}"
                    )
                gain, y = chosen
                S.append(y)
                log.append({
                    "ordre_ajout": step + 1,
                    "numero": horses[y].cheval.numero,
                    "nom": horses[y].cheval.nom,
                    "gain_marginal": round(gain, 4),
                    "tranche": tranche_key(y),
                    "relax_level": relax_level,
                })
                break

    # --- Post-contraintes marché + diversité (calibration 13/09/2026) ---
    ordre_ranked = sorted(range(len(horses)), key=lambda i: -horses[i].synthesis.ordre_final)
    top3_ordre = set(ordre_ranked[:3])
    by_cote = _by_cote_indices(horses)
    cap_ord = fav_ordre_cap(n_partants)

    # v1.29.19 (port Grok, retravaillé) -- validation interne, utilisée
    # partout où un favori de marché prétend au verrouillage/à l'injection
    # forcée (Golden 22/09 : jamais le marché seul). Plus riche que le
    # simple "rang médian p_boost" de v1.29.18 : un favori peut aussi se
    # valider par un excellent ordre_final, ou (favori unanime) par un
    # p_boost proche de la médiane plutôt que strictement au-dessus.
    by_boost_early = sorted(all_indices, key=lambda i: p_boost[i], reverse=True)
    # v1.29.20 -- quartile resserré (max 3 ou ~15%) : le top-25% (v1.29.15-19)
    # sur-protégeait le noyau et bloquait des T3/T4 viables (leçon Argentan).
    n_q = max(3, min(4, (n_partants + 5) // 6))
    top_quartile_early = set(by_boost_early[:n_q])
    median_boost = sorted(p_boost)[len(p_boost) // 2] if p_boost else 0.0

    def _internal_validated(i: int) -> bool:
        """True si le cheval est validé par l'évaluation interne (p_boost /
        ordre / unanime) -- jamais sur la seule cote.
        v1.29.20 : top-3 p_boost / top-3 ordre suffisent (plus le large quartile)."""
        if i in by_boost_early[:3] or i in top3_ordre:
            return True
        if horses[i].cheval.favori_unanime and p_boost[i] >= median_boost * 0.85:
            return True
        if p_boost[i] >= median_boost and horses[i].synthesis.ordre_final >= 0.18:
            return True
        return False

    # v1.29.19 (port Grok) -- éligibilité T3/T4 enrichie : tocard_score OU
    # forme régulière/forte (régularité Top5 récente) OU signaux actifs OU
    # (T4 + profil outsider documenté par le catalogue GRU de l'hippodrome).
    # Remplace/étend RAH-266 (v1.29.17, T4 seul, tocard>=0.20 uniquement) --
    # Golden (22/09) a explicitement demandé "les T3/T4" (pas seulement T4).
    TOCARD_MIN_T3 = 0.22
    TOCARD_MIN_T4 = 0.25
    TOCARD_MIN_T3_REGULIER = 0.18  # assoupli si forme régulière/forte

    def _forme_reguliere_ou_forte(i: int) -> bool:
        from app.engine.musique_features import profil_forme_recente
        mus = getattr(horses[i].cheval, "musique", None)
        return profil_forme_recente(mus) in ("FORTE", "REGULIERE")

    def _gru_extreme_ok(i: int) -> bool:
        """T4 extrême viable si le catalogue GRU le documente pour cet hippodrome."""
        try:
            from app.engine.gru_catalog import get_gru_entry
            entry = get_gru_entry(getattr(race, "hippodrome", "") or "")
            if not entry:
                return False
            op = entry.get("outsider_profile") or {}
            return bool(op.get("extreme_longshot_ok"))
        except Exception:
            return False

    def _tocard_ok(i: int) -> bool:
        """T3/T4 éligibles si tocard>=seuil OU forme régulière OU signaux OU
        (T4 + GRU extreme). Voies alternatives (OR) pour ne jamais bloquer
        le quota [3,5] à sec sur ce seul critère."""
        t = horses[i].synthesis.tranche
        ts = horses[i].breakdown.tocard_score if horses[i].breakdown else 0.0
        has_signaux = bool(horses[i].breakdown and horses[i].breakdown.signaux_actifs)
        forme_ok = _forme_reguliere_ou_forte(i)
        if t == Tranche.T3:
            if ts >= TOCARD_MIN_T3 or has_signaux or forme_ok:
                return True
            if ts >= TOCARD_MIN_T3_REGULIER and forme_ok:
                return True
            return False
        if t in (Tranche.T4A, Tranche.T4B):
            if ts >= TOCARD_MIN_T4 or has_signaux:
                return True
            if forme_ok and _gru_extreme_ok(i):
                return True
            if has_signaux and _gru_extreme_ok(i):
                return True
            return False
        return True  # T1/T2 non concernés

    def _inject(idx: int, note: str) -> None:
        nonlocal S
        if idx in S or idx not in pool:
            return
        rank = ordre_ranked.index(idx) + 1 if idx in ordre_ranked else 99
        if rank > cap_ord and note.startswith("MARKET"):
            # 2e favori : un peu plus souple sur grand champ
            if not (n_partants >= 14 and rank <= cap_ord + 2):
                return
        eject_candidates = [i for i in S if i not in top3_ordre]
        if not eject_candidates:
            return
        eject = min(eject_candidates, key=lambda i: p_boost[i])
        S = [idx if i == eject else i for i in S]
        flags.append(
            f"{note}_INJECTE_num{horses[idx].cheval.numero}"
            f"_ejecte_num{horses[eject].cheval.numero}"
        )
        log.append({
            "ordre_ajout": "post",
            "numero": horses[idx].cheval.numero,
            "nom": horses[idx].cheval.nom,
            "gain_marginal": None,
            "tranche": tranche_key(idx),
            "relax_level": -1,
            "note": note,
        })

    # Top-1 toujours (T1 / cote≤5), top-2 si N≥14
    n_market_force = 2 if n_partants >= 14 else 1
    for rank_m, fav_i in enumerate(by_cote[:n_market_force]):
        cote_fav = _cote_of(horses[fav_i])
        tranche_fav = horses[fav_i].synthesis.tranche
        is_market = (
            (tranche_fav is not None and tranche_fav.value in ("T1", "T2"))
            or (cote_fav is not None and cote_fav <= (5.0 if rank_m == 0 else 8.0))
        )
        if is_market and fav_i not in S:
            _inject(fav_i, "MARKET_TOP" + str(rank_m + 1))

    # Diversité outsiders T3/T4 : au moins 2 sur N≥14
    if n_partants >= 14 and len(S) >= 8:
        def _is_outsider(i: int) -> bool:
            t = horses[i].synthesis.tranche
            if t in (Tranche.T3, Tranche.T4A, Tranche.T4B):
                return True
            c = _cote_of(horses[i])
            return c is not None and c >= 8.0

        n_out = sum(1 for i in S if _is_outsider(i))
        need = 2 - n_out
        if need > 0:
            candidates = [
                i for i in pool
                if i not in S and _is_outsider(i) and _tocard_ok(i)
            ]
            candidates.sort(key=lambda i: p_boost[i], reverse=True)
            for idx in candidates[:need]:
                eject_candidates = [
                    i for i in S
                    if i not in top3_ordre and i not in top_quartile_early and not _is_outsider(i)
                ]
                # ne pas éjecter top-2 marché
                protected = set(by_cote[:2])
                eject_candidates = [i for i in eject_candidates if i not in protected]
                if not eject_candidates:
                    break
                eject = min(eject_candidates, key=lambda i: p_boost[i])
                S = [idx if i == eject else i for i in S]
                flags.append(
                    f"OUTSIDER_DIVERSITE_INJECTE_num{horses[idx].cheval.numero}"
                    f"_ejecte_num{horses[eject].cheval.numero}"
                )
                log.append({
                    "ordre_ajout": "post",
                    "numero": horses[idx].cheval.numero,
                    "nom": horses[idx].cheval.nom,
                    "gain_marginal": None,
                    "tranche": tranche_key(idx),
                    "relax_level": -1,
                    "note": "diversite_outsider_T3T4_tocard_ok",
                })

    # --- 17.5(d) CHAMP_A_RISQUE_DQ_ELEVE -- ajouté le 09/08/2026 ---
    if getattr(race, "_champ_a_risque_dq_eleve", False):
        stab_clean = ["STAB_DQ_SERIE_CRITIQUE" not in horses[i].breakdown.flags
                      and "TEMPERAMENT_RISQUE_DOCUMENTE" not in horses[i].breakdown.flags for i in S]
        if not any(stab_clean):
            flags.append("CHAMP_A_RISQUE_DQ_ELEVE_SANS_RESERVE_PROPRE")  # informatif -- aucun des 8 n'a un profil STAB propre

    # 3) Hill-climb : échanges 1-pour-1 maximisant P_PL(Top5 ⊂ S)
    # v1.29.9 : protéger TOUJOURS les 3 cotes les plus courtes (+ favori unanime)
    # sinon le hill-climb peut sortir un T1 marché avant les forçages qualité.
    # v1.29.19 (port Grok, retravaillé) -- noyau INTERNE d'abord : top-quartile
    # p_boost + top-3 ordre_final + favori unanime VALIDÉ + (filet de
    # sécurité) top-1 cote SEULEMENT s'il est validé en interne. Un favori
    # de cote que notre évaluation interne juge médiocre reste éjectable
    # comme n'importe quel autre cheval -- "éviter d'être guidé
    # principalement par le marché" (Golden 22/09).
    protected = set(top_quartile_early) | set(top3_ordre)
    non_valides = []
    for i, h in enumerate(horses):
        if h.cheval.favori_unanime:
            if _internal_validated(i):
                protected.add(i)
            else:
                non_valides.append(i)
    if by_cote and _internal_validated(by_cote[0]):
        protected.add(by_cote[0])
    elif by_cote:
        non_valides.append(by_cote[0])
    if non_valides:
        flags.append(
            "MARCHE_FAVORI_NON_VALIDE_INTERNE_hillclimb="
            + ",".join(f"n{horses[i].cheval.numero}" for i in non_valides)
        )
    S_before = list(S)
    S, n_swaps, p_hc = hill_climb_top5(
        p, S, pool, all_indices, frozenset(protected), max_rounds=16,
    )
    # P2/P1: passe hybride — n'accepter un swap PL que s'il ne dégrade pas Σq trop
    if n_swaps:
        flags.append(f"HILLCLIMB_TOP5_SWAPS_{n_swaps}")
    sum_q = lambda sel: sum(q_top5[i] for i in sel)
    q_before = sum_q(S_before)
    q_after = sum_q(S)
    if q_after + 1e-12 < q_before - hw["repair_eps"]:
        # rollback hill-climb if destroyed Top5 mass proxy
        flags.append(f"HILLCLIMB_ROLLBACK_SIGMA_Q_{q_after:.4f}_lt_{q_before:.4f}")
        S = list(S_before)
        n_swaps = 0
        p_hc = prob_top5_in_set(p, S, all_indices)
    else:
        # micro-swaps guidés par q (max 6) sans casser PL trop fort
        pl_floor = p_hc * 0.985
        extra = 0
        for _ in range(6):
            improved = False
            for out_i in list(S):
                if out_i in protected:
                    continue
                for in_i in pool:
                    if in_i in S:
                        continue
                    trial = [in_i if x == out_i else x for x in S]
                    if sum_q(trial) <= sum_q(S) + 1e-12:
                        continue
                    pl_t = prob_top5_in_set(p, trial, all_indices)
                    if pl_t >= pl_floor:
                        S = trial
                        p_hc = pl_t
                        extra += 1
                        improved = True
                        break
                if improved:
                    break
            if not improved:
                break
        if extra:
            flags.append(f"HYBRID_Q_SWAPS_{extra}")
        log.append({
            "ordre_ajout": "post",
            "note": "hillclimb_pl_top5",
            "swaps": n_swaps,
            "selection_avant": [horses[i].cheval.numero for i in S_before],
            "selection_apres": [horses[i].cheval.numero for i in S],
            "p_top5_apres": p_hc,
        })

    # =========================================================================
    # =========================================================================
    # POST-SÉLECTION (21/09/2026 v1.29.9) — qualité INTRA-TRANCHE
    #
    # Le quota 4 T1/T2 + 4 T3/T4 reste (un Quinté 100% favoris ou 100%
    # outsiders est rare et mal payé). Ce qui compte : CHOISIR les bons
    # chevaux DANS chaque bande (ex. 2T1+2T2 ou 1T1+3T2 — libre).
    #
    # HIÉRARCHIE OFFICIELLE v1.29.10 (protocole) :
    #   0) Noyau intouchable : top-3 marché + top-3 p_boost + favori unanime
    #   1) Couverture marché (≥2 des 3 cotes les plus courtes)
    #   2) Quota 4+4 qualité intra-bande (sans casser le noyau)
    #   3) RAH-90 plafond ICP (sans casser le noyau ; tolère 3 si tous top-marché)
    #   4) Réparation quota finale
    # Si 2/3 impossibles sans casser 0 → WARN checklist, pas sacrifice qualité.
    # =========================================================================

    def _is_t12(i: int) -> bool:
        t = horses[i].synthesis.tranche
        if t is not None and t.value in ("T1", "T2"):
            return True
        c = _cote_of(horses[i])
        return c is not None and c < 15.0

    def _is_t34(i: int) -> bool:
        t = horses[i].synthesis.tranche
        if t is not None and t.value in ("T3", "T4a", "T4b"):
            return True
        c = _cote_of(horses[i])
        return c is not None and c >= 15.0

    def _tr_val(i: int) -> str:
        t = horses[i].synthesis.tranche
        if t is not None:
            return t.value
        c = _cote_of(horses[i])
        if c is None:
            return "T3"
        if c < 9:
            return "T1"
        if c < 15:
            return "T2"
        if c < 35:
            return "T3"
        return "T4b"

    def _is_t1(i: int) -> bool:
        return _tr_val(i) == "T1"

    def _is_t2(i: int) -> bool:
        return _tr_val(i) == "T2"

    def _is_t3(i: int) -> bool:
        return _tr_val(i) in ("T3",)

    def _is_t4(i: int) -> bool:
        return _tr_val(i) in ("T4a", "T4b", "T4A", "T4B")

    _mix = discipline_internal_mix(getattr(race, "discipline", None))

    def _repair_internal_mix(S_local: list, note: str) -> list:
        """Mix interne T1/T2/T3/T4 (01/10/2026) — après quotas bande [3,5].
        max T1, min T2 si candidats, min T4 (plat/haies/attelé)."""
        for _pass in range(6):
            t1 = [i for i in S_local if _is_t1(i)]
            t2 = [i for i in S_local if _is_t2(i)]
            t3 = [i for i in S_local if _is_t3(i)]
            t4 = [i for i in S_local if _is_t4(i)]
            changed = False

            # Max T1
            if len(t1) > _mix["t1_max"]:
                cands = [i for i in pool if i not in S_local and not _is_t1(i)]
                if not cands:
                    cands = [i for i in all_indices if i not in S_local and not _is_t1(i)]
                # préférer injecter T2 manquant, sinon T3/T4
                if len(t2) < _mix["t2_min"]:
                    pref = [i for i in cands if _is_t2(i)] or cands
                elif len(t4) < _mix["t4_min"]:
                    pref = [i for i in cands if _is_t4(i)] or cands
                else:
                    pref = cands
                if pref and t1:
                    inj = _best_inject(pref)
                    ej = _worst_eject(t1)
                    if not (ej in core_protected and inj not in core_protected):
                        S_local = [inj if x == ej else x for x in S_local]
                        flags.append(
                            f"MIX_MAX_T1_{note}_in{horses[inj].cheval.numero}_out{horses[ej].cheval.numero}"
                        )
                        changed = True

            # Min T2
            t1 = [i for i in S_local if _is_t1(i)]
            t2 = [i for i in S_local if _is_t2(i)]
            if len(t2) < _mix["t2_min"]:
                cands = [i for i in pool if i not in S_local and _is_t2(i)]
                if not cands:
                    cands = [i for i in all_indices if i not in S_local and _is_t2(i)]
                if cands:
                    # éjecter T1 excédentaire d'abord, sinon pire T1, sinon pire T12 hors T2
                    if len(t1) > _mix["t1_target"]:
                        eject_pool = t1
                    else:
                        eject_pool = [i for i in S_local if _is_t1(i) or (_is_t3(i) and len(t3) > 1)]
                        if not eject_pool:
                            eject_pool = [i for i in S_local if not _is_t2(i) and not _is_t4(i)]
                    if eject_pool:
                        inj = _best_inject(cands)
                        ej = _worst_eject(eject_pool)
                        if not (ej in core_protected and inj not in core_protected):
                            trial = [inj if x == ej else x for x in S_local]
                            # respecter bande [3,5]
                            n12 = sum(1 for i in trial if _is_t12(i))
                            n34 = sum(1 for i in trial if _is_t34(i))
                            if 3 <= n12 <= 5 and 3 <= n34 <= 5:
                                S_local = trial
                                flags.append(
                                    f"MIX_MIN_T2_{note}_in{horses[inj].cheval.numero}_out{horses[ej].cheval.numero}"
                                )
                                changed = True

            # Min T4 (plat/haies/attelé)
            t4 = [i for i in S_local if _is_t4(i)]
            if len(t4) < _mix["t4_min"]:
                cands = [i for i in pool if i not in S_local and _is_t4(i)]
                if not cands:
                    cands = [i for i in all_indices if i not in S_local and _is_t4(i)]
                if cands:
                    # éjecter T1 au-delà target, sinon T3 en trop
                    t1 = [i for i in S_local if _is_t1(i)]
                    t3 = [i for i in S_local if _is_t3(i)]
                    if len(t1) > _mix["t1_target"]:
                        eject_pool = t1
                    elif len(t3) > 1:
                        eject_pool = t3
                    else:
                        eject_pool = [i for i in S_local if _is_t12(i) and not _is_t2(i)]
                    if eject_pool:
                        inj = _best_inject(cands)
                        ej = _worst_eject(eject_pool)
                        if not (ej in core_protected and inj not in core_protected):
                            trial = [inj if x == ej else x for x in S_local]
                            n12 = sum(1 for i in trial if _is_t12(i))
                            n34 = sum(1 for i in trial if _is_t34(i))
                            n4 = sum(1 for i in trial if _is_t4(i))
                            if 3 <= n12 <= 5 and 3 <= n34 <= 5 and n4 <= _mix["t4_max"]:
                                S_local = trial
                                flags.append(
                                    f"MIX_MIN_T4_{note}_in{horses[inj].cheval.numero}_out{horses[ej].cheval.numero}"
                                )
                                changed = True

            if not changed:
                break
        # résumé mix
        t1 = sum(1 for i in S_local if _is_t1(i))
        t2 = sum(1 for i in S_local if _is_t2(i))
        t3 = sum(1 for i in S_local if _is_t3(i))
        t4 = sum(1 for i in S_local if _is_t4(i))
        flags.append(f"MIX_INTERNE_{note}=T1:{t1}/T2:{t2}/T3:{t3}/T4:{t4}_targets={_mix}")
        return S_local

    def _cote_ref(i: int) -> float:
        c = horses[i].cheval.cote_avant_course
        if c is None:
            c = horses[i].cheval.cote_matin
        return float(c) if c is not None and c > 0 else 999.0

    def _icp(i: int) -> float:
        v = horses[i].cheval.icp_global
        if v is None:
            v = horses[i].cheval.icp_pondere
        return float(v) if v is not None else 0.0

    # Noyau protégé : top-3 marché VALIDÉS EN INTERNE + top-3 p_boost
    # v1.29.16 (port Grok) : + quartile supérieur PCH/p_boost (min 4) —
    # interdit d'éjecter un cheval top-qualité pour "remplir" le 4+4
    # (leçon audits walk-forward : T2 à fort PCH éjecté à tort).
    # v1.29.18 (Golden 22/09) : un favori marché n'intègre le noyau QUE s'il
    # est aussi validé en interne (même règle que pour le hill-climb
    # ci-dessus) -- jamais un verrouillage sur la seule cote.
    by_cote_all = sorted(all_indices, key=_cote_ref)
    top_market_brut = by_cote_all[:3]
    top_market = [i for i in top_market_brut if _internal_validated(i)]
    top_market_exclus = [i for i in top_market_brut if i not in top_market]
    if top_market_exclus:
        flags.append(
            "MARCHE_FAVORI_NON_VALIDE_INTERNE_noyau="
            + ",".join(f"n{horses[i].cheval.numero}" for i in top_market_exclus)
            + " (exclu du noyau protégé -- cote seule insuffisante pour verrouiller)"
        )
    by_boost = by_boost_early
    top_quality = by_boost[:3]
    top_quartile = top_quartile_early
    # v1.29.20 -- noyau = marché validé + top-3 qualité + protected uniquement.
    # Le quartile n'est plus dans core_protected (évite rigidité Argentan) ;
    # il reste un filet secondaire dans _worst_eject uniquement.
    # v1.29.29 — NOYAU ABANDONNÉ (top-3 marché + top-3 score + favori unanime)
    # Sélection pilotée par p_boost + quotas T12/T34 [3,5] uniquement.
    core_protected: set = set()
    flags.append("NOYAU_DESACTIVE_v12929")
    flags.append(
        "CORE_PROTECT_VIDE"
        + (f"|ref_market={','.join(f'n{horses[i].cheval.numero}' for i in top_market)}" if top_market else "")
    )

    def _rah266_eligible(i: int) -> bool:
        """RAH-266 (v1.29.19, étendu port Grok) : délègue à _tocard_ok, qui
        couvre désormais T3 ET T4 (tocard_score, forme régulière/forte,
        signaux actifs, ou T4+GRU extrême documenté) -- Golden (22/09) a
        explicitement demandé "les T3/T4", pas seulement T4."""
        return _tocard_ok(i)

    def _best_inject(cands: list) -> int:
        """v1.29.30: meilleur score hybride (q + axes) parmi RAH-266 éligibles."""
        eligible = [i for i in cands if _rah266_eligible(i)]
        pool_c = eligible if eligible else cands
        def _sc(i):
            tr = horses[i].synthesis.tranche
            trv = tr.value if tr is not None else None
            return hybrid_candidate_score(i, trv, q_top5[i], p_boost[i], axes)
        choix = max(pool_c, key=_sc)
        if not eligible and cands:
            flags.append(f"RAH266_INJECTION_NON_JUSTIFIEE_n{horses[choix].cheval.numero}")
        return choix

    def _worst_eject(cands: list) -> int:
        """v1.29.30 + v1.29.34: plus faible score hybride.
        Soft-protect T1/T2 parmi les 5 cotes les plus courtes (ne pas
        éjecter un semi-favori marché-cohérent pour un gain Σq marginal —
        leçon Chantilly ANSSIO)."""
        free = [i for i in cands if i not in core_protected]
        pool_e = free if free else [i for i in cands if i not in protected and i not in top_quartile]
        if not pool_e:
            pool_e = [i for i in cands if i not in protected]
        if not pool_e:
            pool_e = list(cands)
        # Soft-protect: T12 dans top-5 cotes — éjectables seulement si pool épuisé
        def _cote(i):
            c = horses[i].cheval.cote_avant_course or horses[i].cheval.cote_matin
            return float(c) if c is not None else 999.0
        by_cote = sorted(range(len(horses)), key=_cote)
        top5_market = set(by_cote[:5])
        soft = []
        hard = []
        for i in pool_e:
            tr = horses[i].synthesis.tranche
            trv = tr.value if tr is not None else ""
            if i in top5_market and trv in ("T1", "T2"):
                soft.append(i)
            else:
                hard.append(i)
        use = hard if hard else soft if soft else pool_e
        def _sc(i):
            tr = horses[i].synthesis.tranche
            trv = tr.value if tr is not None else None
            return hybrid_candidate_score(i, trv, q_top5[i], p_boost[i], axes)
        return min(use, key=_sc)

    QUOTA_MIN = 3
    QUOTA_MAX = 5

    def _repair_quota_flexible(S_local: list, note: str) -> list:
        """v1.29.18 (Golden 22/09) -- remplace le quota rigide 4+4 par une
        plage souple [3,5] de chaque côté (T1+T2 et T3+T4), ticket toujours
        à 8. Corrige déficit ET excès. Ne touche jamais le noyau protégé
        pour un déficit ; peut y toucher pour un excès si aucun cheval
        hors-noyau n'est disponible côté excédentaire (log explicite)."""
        for _ in range(8):
            t12 = [i for i in S_local if _is_t12(i)]
            t34 = [i for i in S_local if _is_t34(i)]
            if QUOTA_MIN <= len(t12) <= QUOTA_MAX and QUOTA_MIN <= len(t34) <= QUOTA_MAX:
                break
            if len(t34) < QUOTA_MIN:
                cands = [i for i in pool if i not in S_local and _is_t34(i)]
                if not cands:
                    cands = [i for i in all_indices if i not in S_local and _is_t34(i)]
                if not cands or not t12:
                    flags.append(f"QUOTA_REPAIR_FAIL_T34_{note}")
                    break
                inj = _best_inject(cands)
                ej = _worst_eject(t12)
                if ej in core_protected and inj not in core_protected:
                    flags.append(f"QUOTA_REPAIR_REFUS_EJECT_CORE_n{horses[ej].cheval.numero}_{note}")
                    break
                S_local = [inj if x == ej else x for x in S_local]
                flags.append(f"QUOTA_REPAIR_{note}_in{horses[inj].cheval.numero}_out{horses[ej].cheval.numero}")
            elif len(t12) < QUOTA_MIN:
                cands = [i for i in pool if i not in S_local and _is_t12(i)]
                if not cands:
                    cands = [i for i in all_indices if i not in S_local and _is_t12(i)]
                if not cands or not t34:
                    flags.append(f"QUOTA_REPAIR_FAIL_T12_{note}")
                    break
                inj = _best_inject(cands)
                ej = _worst_eject(t34)
                if ej in core_protected and inj not in core_protected:
                    flags.append(f"QUOTA_REPAIR_REFUS_EJECT_CORE_n{horses[ej].cheval.numero}_{note}")
                    break
                S_local = [inj if x == ej else x for x in S_local]
                flags.append(f"QUOTA_REPAIR_{note}_in{horses[inj].cheval.numero}_out{horses[ej].cheval.numero}")
            elif len(t12) > QUOTA_MAX:
                cands = [i for i in pool if i not in S_local and _is_t34(i)]
                if not cands:
                    cands = [i for i in all_indices if i not in S_local and _is_t34(i)]
                eject_cands = [i for i in t12 if i not in core_protected]
                if not cands or not eject_cands:
                    flags.append(f"QUOTA_EXCES_T12_NON_CORRIGE_{note}")
                    break
                inj = _best_inject(cands)
                ej = min(eject_cands, key=lambda i: p_boost[i])
                S_local = [inj if x == ej else x for x in S_local]
                flags.append(f"QUOTA_EXCES_T12_CORRIGE_{note}_in{horses[inj].cheval.numero}_out{horses[ej].cheval.numero}")
            elif len(t34) > QUOTA_MAX:
                cands = [i for i in pool if i not in S_local and _is_t12(i)]
                if not cands:
                    cands = [i for i in all_indices if i not in S_local and _is_t12(i)]
                eject_cands = [i for i in t34 if i not in core_protected]
                if not cands or not eject_cands:
                    flags.append(f"QUOTA_EXCES_T34_NON_CORRIGE_{note}")
                    break
                inj = _best_inject(cands)
                ej = min(eject_cands, key=lambda i: p_boost[i])
                S_local = [inj if x == ej else x for x in S_local]
                flags.append(f"QUOTA_EXCES_T34_CORRIGE_{note}_in{horses[inj].cheval.numero}_out{horses[ej].cheval.numero}")
        return S_local


    # ----- 1) Couverture favoris de marché (≥1/3, assoupli 22/09) -----
    # v1.29.18 (Golden) : "éviter d'être guidé principalement par le marché"
    # -- seuil abaissé de 2/3 à 1/3 (n'impose plus deux favoris de cote au
    # prix d'éjections systématiques ; garde une présence minimale du
    # marché sans le laisser dicter la composition). Le contrôle porte sur
    # top_market_brut (cote pure), pas top_market (déjà filtré interne et
    # réservé au noyau protégé) -- la couverture est une question de
    # représentation, pas de verrouillage.
    if len(S) >= 8 and len(all_indices) >= 3:
        n_in = sum(1 for i in top_market_brut if i in S)
        flags.append(
            "MARCHE_TOP3_COTES="
            + ",".join(f"{horses[i].cheval.numero}@{_cote_ref(i):.1f}" for i in top_market_brut)
            + f"_dans_ticket={n_in}/3"
        )
        # P1 v1.29.30: marché soft ≥ market_min (défaut 2/3) avec garde Σq
        _mkt_need = int(hw.get("market_min", 2))
        while n_in < _mkt_need:
            missing = [i for i in top_market_brut if i not in S]
            if not missing:
                break
            missing.sort(key=lambda i: q_top5[i], reverse=True)
            inject = missing[0]
            eject_cands = [i for i in S if i not in top_market_brut and i not in core_protected]
            if not eject_cands:
                eject_cands = [i for i in S if i not in top_market_brut]
            if not eject_cands:
                flags.append("MARCHE_COUVERTURE_BLOCAGE_PROTECTION")
                break
            eject = min(eject_cands, key=lambda i: q_top5[i])
            trial = [inject if x == eject else x for x in S]
            if sum(q_top5[i] for i in trial) + 1e-12 < sum(q_top5[i] for i in S) - hw["repair_eps"]:
                flags.append(
                    f"MARCHE_SWAP_REFUSE_SIGMA_Q_in{horses[inject].cheval.numero}_out{horses[eject].cheval.numero}"
                )
                # essayer un autre eject
                eject_cands2 = [i for i in eject_cands if i != eject]
                if not eject_cands2:
                    break
                eject = min(eject_cands2, key=lambda i: q_top5[i])
                trial = [inject if x == eject else x for x in S]
                if sum(q_top5[i] for i in trial) + 1e-12 < sum(q_top5[i] for i in S) - hw["repair_eps"]:
                    flags.append("MARCHE_COUVERTURE_ABORT_SIGMA_Q")
                    break
            S = trial
            flags.append(
                f"MARCHE_FORCE_in{horses[inject].cheval.numero}"
                f"_out{horses[eject].cheval.numero}"
                f"_cote{_cote_ref(inject):.1f}"
            )
            log.append({
                "ordre_ajout": "post",
                "numero": horses[inject].cheval.numero,
                "nom": horses[inject].cheval.nom,
                "tranche": tranche_key(inject),
                "note": "force_couverture_favoris_marche",
                "ejecte": horses[eject].cheval.numero,
            })
            n_in = sum(1 for i in top_market_brut if i in S)
        flags.append(f"MARCHE_COUVERTURE_FINALE={sum(1 for i in top_market_brut if i in S)}/3_need={int(hw.get('market_min', 2))}")

    # ----- 2) Quota [3,5] chaque côté — choix qualité dans chaque bande -----
    # v1.29.18 (Golden 22/09) : remplace le forçage rigide 4+4 par un appel
    # à _repair_quota_flexible (déficit ET excès, plage [3,5]) — la logique
    # de choix/éjection est désormais centralisée dans une seule fonction
    # au lieu d'être dupliquée ici avec un seuil figé à 4.
    if len(S) >= 8:
        S_pre_q = list(S)
        q_pre = sum(q_top5[i] for i in S_pre_q)
        S = _repair_quota_flexible(S, "PRINCIPAL")
        S = _repair_internal_mix(S, "PRINCIPAL")
        q_post = sum(q_top5[i] for i in S)
        if q_post + 1e-12 < q_pre - hw["repair_eps"]:
            # P1: si repair a trop dégradé Σq, retenter avec préférences q déjà dans inject/eject
            # (déjà le cas) — log uniquement; on garde S réparé pour respecter quota dur
            flags.append(f"QUOTA_REPAIR_SIGMA_Q_DELTA={q_post - q_pre:.4f}")
        t12 = [i for i in S if _is_t12(i)]
        t34 = [i for i in S if _is_t34(i)]
        flags.append(f"QUOTA_TRANCHE_FINAL_T12={len(t12)}_T34={len(t34)}")
        flags.append("HYBRID_SELECT_v12930")
        # Mix libre T1 vs T2 (et T3 vs T4) — purement informatif
        mix = {}
        for i in S:
            tr = horses[i].synthesis.tranche
            k = tr.value if tr is not None else "?"
            mix[k] = mix.get(k, 0) + 1
        flags.append("MIX_INTRA_TRANCHE=" + ",".join(f"{k}:{v}" for k, v in sorted(mix.items())))

        # ----- 2bis) Place réservée longshot (v1.29.34) -----
        # Si au moins un cheval hors ticket a tocard>=0.35 ET cote>=30 (T3/T4),
        # et qu'aucun du ticket ne satisfait ce profil, injecter le meilleur
        # en échange du T34 le plus faible (sans casser quota [3,5]).
        # Objectif structurel : convertir le signal longshot en place ticket
        # (Chantilly SPEEDY GREEN tocard 0.35 @51 non retenu).
        def _is_longshot_signal(i: int) -> bool:
            """T3/T4 : tocard fort @≥30 OU LS_FINAL famille @≥15 (bande T3+)."""
            bd = horses[i].breakdown
            ts = float(bd.tocard_score or 0.0) if bd else 0.0
            cote = horses[i].cheval.cote_avant_course or horses[i].cheval.cote_matin
            try:
                cote_f = float(cote) if cote is not None else 0.0
            except (TypeError, ValueError):
                cote_f = 0.0
            if not _is_t34(i) or cote_f < 15.0:
                return False
            # Voie tocard (Ghost D) — T4 typique
            if ts >= 0.35 and cote_f >= 30.0:
                return True
            # Voie familles F* — ouvre T3 (15–35) sans doublon exclusif tocard
            q = qualitatifs[i] if i < len(qualitatifs) else None
            ls_map = getattr(q, "ls_final_par_famille", None) or {}
            ls_max = max(ls_map.values()) if ls_map else 0.0
            if cote_f >= 15.0 and ls_max >= 0.45:
                return True
            if cote_f >= 35.0 and ls_max >= 0.35:
                return True
            return False

        has_ls_in_ticket = any(_is_longshot_signal(i) for i in S)
        ls_candidates = [i for i in range(len(horses)) if i not in S and _is_longshot_signal(i) and _rah266_eligible(i)]
        if not has_ls_in_ticket and ls_candidates and len(S) >= 8:
            # préférer le plus haut tocard puis p_boost
            inj = max(
                ls_candidates,
                key=lambda i: (
                    float(horses[i].breakdown.tocard_score or 0.0),
                    p_boost[i],
                    q_top5[i],
                ),
            )
            t34_now = [i for i in S if _is_t34(i)]
            if t34_now:
                ej = min(t34_now, key=lambda i: (p_boost[i], q_top5[i]))
                # ne pas éjecter si l'éjecté a aussi un fort tocard
                ej_ts = float(horses[ej].breakdown.tocard_score or 0.0) if horses[ej].breakdown else 0.0
                inj_ts = float(horses[inj].breakdown.tocard_score or 0.0)
                if inj_ts >= ej_ts - 0.02:
                    S = [inj if x == ej else x for x in S]
                    flags.append(
                        f"LONGSHOT_SLOT_in{horses[inj].cheval.numero}"
                        f"_out{horses[ej].cheval.numero}"
                        f"_tocard{inj_ts:.2f}"
                    )
                    log.append({
                        "ordre_ajout": "post",
                        "numero": horses[inj].cheval.numero,
                        "nom": horses[inj].cheval.nom,
                        "tranche": tranche_key(inj),
                        "note": "longshot_slot_t3t4_tocard_or_ls_final",
                        "ejecte": horses[ej].cheval.numero,
                    })
                else:
                    flags.append("LONGSHOT_SLOT_SKIP_EJ_MEILLEUR_TOCARD")
            else:
                flags.append("LONGSHOT_SLOT_SKIP_NO_T34")
        elif has_ls_in_ticket:
            flags.append("LONGSHOT_SLOT_DEJA_PRESENT")
        elif not ls_candidates:
            flags.append("LONGSHOT_SLOT_AUCUN_CANDIDAT")

    # ----- 3) RAH-90 : max 2 ICP>=6 ; tolère 3 si tous dans top-3 marché -----
    if len(S) >= 8:
        favs = [i for i in S if _icp(i) >= 6.0]
        top_m_set = set(top_market_brut)
        # Si tous les favoris ICP sont des cotes courtes → plafond assoupli à 3
        max_icp_fav = 3 if favs and all(i in top_m_set for i in favs) else 2
        if max_icp_fav == 3:
            flags.append("RAH90_PLAFOND_ASSOUPLI_3_TOUS_TOP_MARCHE")
        while len(favs) > max_icp_fav:
            eject_cands = [
                i for i in favs
                if i not in core_protected
            ]
            if not eject_cands:
                flags.append("RAH90_BLOCAGE_CORE_PROTECT")
                break
            # Parmi les favoris ICP éjectables : le plus faible p_boost
            eject = min(eject_cands, key=lambda i: p_boost[i])
            candidates = [
                i for i in pool
                if i not in S and _icp(i) < 6.0
            ]
            if not candidates:
                candidates = [i for i in all_indices if i not in S and _icp(i) < 6.0]
            if not candidates:
                flags.append("RAH90_POOL_VIDE_NON_FAVORI")
                break
            inject = _best_inject(candidates)
            S = [inject if x == eject else x for x in S]
            flags.append(
                f"RAH90_FORCE_out{horses[eject].cheval.numero}"
                f"_in{horses[inject].cheval.numero}"
                f"_icp{_icp(eject):.0f}"
            )
            log.append({
                "ordre_ajout": "post",
                "numero": horses[inject].cheval.numero,
                "nom": horses[inject].cheval.nom,
                "tranche": tranche_key(inject),
                "note": "force_rah90_plafond_icp",
                "ejecte": horses[eject].cheval.numero,
            })
            favs = [i for i in S if _icp(i) >= 6.0]
        flags.append(f"RAH90_ICP_FAVORIS_FIN={sum(1 for i in S if _icp(i) >= 6.0)}")

    # ----- 4) Réparation quota finale (après RAH-90 / marché) -----
    S = _repair_quota_flexible(S, "FINAL")
    S = _repair_internal_mix(S, "FINAL")
    t12 = [i for i in S if _is_t12(i)]
    t34 = [i for i in S if _is_t34(i)]
    flags.append(f"QUOTA_APRES_REPAIR_T12={len(t12)}_T34={len(t34)}")

    # ----- 5) RAH-266 sur le TICKET FINAL (v1.29.18, Golden 22/09) -----
    # Jusqu'ici RAH-266 n'était vérifié qu'au moment de l'injection forcée
    # (_best_inject, v1.29.17) -- un T4 non justifié pouvait entrer par la
    # sélection gloutonne ou le hill-climb sans jamais passer par
    # _best_inject. Garde-fou final : AUCUN T3/T4 dans le ticket sans
    # tocard_score>=0.20 ou signaux actifs ("les T3/T4 doivent avoir un
    # score minimum pour intégrer le ticket").
    for _ in range(4):
        ineligibles = [i for i in S if _is_t34(i) and not _rah266_eligible(i)]
        if not ineligibles:
            break
        cible = min(ineligibles, key=lambda i: p_boost[i])
        if cible in core_protected:
            flags.append(f"RAH266_TICKET_ECHEC_PROTEGE_n{horses[cible].cheval.numero}")
            break
        candidats_remplacement = [
            i for i in pool if i not in S and _is_t34(i) and _rah266_eligible(i)
        ]
        if not candidats_remplacement:
            candidats_remplacement = [
                i for i in all_indices if i not in S and _is_t34(i) and _rah266_eligible(i)
            ]
        if not candidats_remplacement:
            flags.append(f"RAH266_TICKET_ECHEC_AUCUN_REMPLACANT_n{horses[cible].cheval.numero}")
            break
        remplacant = _best_inject(candidats_remplacement)
        S = [remplacant if x == cible else x for x in S]
        flags.append(
            f"RAH266_TICKET_CORRIGE_in{horses[remplacant].cheval.numero}"
            f"_out{horses[cible].cheval.numero}"
        )
        log.append({
            "ordre_ajout": "post",
            "numero": horses[remplacant].cheval.numero,
            "nom": horses[remplacant].cheval.nom,
            "tranche": tranche_key(remplacant),
            "note": "rah266_correction_ticket_final",
            "ejecte": horses[cible].cheval.numero,
        })
    # Le remplacement ci-dessus peut avoir rouvert un léger déséquilibre
    # de quota -- une dernière passe légère le referme si besoin.
    S = _repair_quota_flexible(S, "APRES_RAH266")
    S = _repair_internal_mix(S, "APRES_RAH266")

    # ----- 6) Plafond T4b (100-300/1, extrêmes) -- note opérationnelle -----
    # v1.29.19 (22/09) : "limiter le nombre de T4b purs dans le ticket
    # (ex. max 1-2) pour ne pas diluer la masse Top5". Remplace l'excédent
    # par le meilleur T3/T4a/T4b éligible dispo, en restant dans le même
    # groupe T3+T4 (n'affecte donc pas le quota [3,5]).
    # v1.29.32 : tocards extrêmes rares dans Top5 (<8% si >40/1)
    disc_u = (disc or "").upper()
    MAX_T4B = 1 if ("TROT" in disc_u or n_partants <= 14) else 2
    for _ in range(4):
        t4b_in_S = [i for i in S if horses[i].synthesis.tranche == Tranche.T4B]
        if len(t4b_in_S) <= MAX_T4B:
            break
        excedent = [i for i in t4b_in_S if i not in core_protected]
        if not excedent:
            flags.append("T4B_EXCES_NON_CORRIGE_PROTEGE")
            break
        cible = min(excedent, key=lambda i: p_boost[i])
        candidats_remplacement = [
            i for i in pool
            if i not in S and _is_t34(i) and horses[i].synthesis.tranche != Tranche.T4B and _tocard_ok(i)
        ]
        if not candidats_remplacement:
            candidats_remplacement = [
                i for i in all_indices
                if i not in S and _is_t34(i) and horses[i].synthesis.tranche != Tranche.T4B and _tocard_ok(i)
            ]
        if not candidats_remplacement:
            flags.append("T4B_EXCES_NON_CORRIGE_AUCUN_REMPLACANT")
            break
        remplacant = _best_inject(candidats_remplacement)
        S = [remplacant if x == cible else x for x in S]
        flags.append(f"T4B_EXCES_CORRIGE_in{horses[remplacant].cheval.numero}_out{horses[cible].cheval.numero}")

    t12 = [i for i in S if _is_t12(i)]
    t34 = [i for i in S if _is_t34(i)]

    p_top5_final = prob_top5_in_set(p, S, all_indices)
    masse_residuelle = 1.0 - p_top5_final
    # Étape 1 (17.8) : "Résultat non certifié conforme si masse résiduelle
    # finale reste >15% -- déclaré comme indicatif".
    if masse_residuelle > 0.15:
        statut_couverture = "INDICATIF (masse résiduelle > 15%)"
    else:
        statut_couverture = "CERTIFIÉ"
    # v1.29.19 (port Grok, Golden 22/09) -- suppression de la différenciation
    # par bande de taille de champ (BANDE_CHAMP_PRIORITAIRE_TOP5 10-15,
    # HORS_KPI ≥17) : "on ne priorise pas des champs, on cible toutes les
    # courses à partir de 12 partants". Le seuil dur est appliqué en amont
    # (orchestrator.py, VANTAGE_MIN_PARTANTS) ; ces flags ici sont
    # informatifs/défensifs seulement (utile si cette fonction est jamais
    # appelée hors du pipeline standard).
    if n_partants >= 12:
        flags.append("CIBLE_CHAMP_GE12")
    else:
        flags.append("CHAMP_SOUS_12_PARTANTS")

    # v1.29.21 -- profils forme Top5 *même discipline* des 8 retenus
    from app.engine.musique_features import (
        profil_forme_recente_disc,
        nb_top5_recent_disc,
        profil_forme_recente,
    )
    forme_summary: Dict[str, int] = {}
    forme_by_idx: Dict[int, str] = {}
    for i in S:
        mus = getattr(horses[i].cheval, "musique", None)
        pf = profil_forme_recente_disc(mus, race.discipline)
        forme_by_idx[i] = pf
        forme_summary[pf] = forme_summary.get(pf, 0) + 1
        n5 = nb_top5_recent_disc(mus, race.discipline)
        if pf == "MORTE":
            flags.append(f"FORME_MORTE_n{horses[i].cheval.numero}")
        elif pf == "FORTE":
            flags.append(f"FORME_FORTE_n{horses[i].cheval.numero}_top5x{n5}")
    flags.append("FORME_TICKET=" + ",".join(f"{k}:{v}" for k, v in sorted(forme_summary.items())))

    # v1.29.21 -- rôles PIVOT/SEMI/VALUE/SAUVAGE (axe fonction, T1–T4 conservés)
    # roles définitivement retirés (v1.29.35)
    # forme pour tout le champ (rôles hors ticket aussi utiles audit)
    forme_all: Dict[int, str] = {}
    sov_all: Dict[int, float] = {}
    for i in all_indices:
        mus = getattr(horses[i].cheval, "musique", None)
        forme_all[i] = profil_forme_recente_disc(mus, race.discipline)
        try:
            from app.engine.synthesis import compute_sov_v2
            tr_i = horses[i].synthesis.tranche if horses[i].synthesis else None
            sov_all[i], _ = compute_sov_v2(horses[i].cheval, tr_i)
        except Exception:
            sov_all[i] = 0.0
    # v1.29.29 — concepts PIVOT/SEMI/VALUE/SAUVAGE abandonnés (plus de soft-fill rôles)
    roles_list = []  # module rôles définitivement retiré
    role_report = {
        "status": "DISABLED",
        "label": "Rôles retirés définitivement",
        "counts": {},
        "warns": [],
    }
    flags.append("ROLES_RETIRES_DEFINITIF")

    # Observabilité Top5 (n'influence pas la sélection)
    from app.engine.pl_inclusion import compute_ticket_top5_stats
    top5_stats = compute_ticket_top5_stats(
        horses, S,
        p_top5_quality={"observed": 0, "blended": len(S), "naive_proxy": 0},
    )

    _mk = [1.0 / float(_cote_of(h)) if _cote_of(h) and _cote_of(h) > 1.01 else 0.0 for h in horses]
    try:
        _pi_mk = inclusion_probs(_mk) if sum(_mk) > 0 else [0.0] * len(horses)
    except Exception:
        _pi_mk = [0.0] * len(horses)
    _best_model = best_expected_subset(_pi_model, 8)
    _best_market = best_expected_subset(_pi_mk, 8)
    captures_attendues = {
        "ticket_selon_modele": round(expected_hits(_pi_model, S), 3),
        "top8_modele_pur": round(expected_hits(_pi_model, _best_model), 3),
        "top8_marche_selon_modele": round(expected_hits(_pi_model, _best_market), 3),
        "ticket_selon_marche": round(expected_hits(_pi_mk, S), 3),
        "top8_marche_selon_marche": round(expected_hits(_pi_mk, _best_market), 3),
        "recouvrement_ticket_top8_modele": len(set(S) & set(_best_model)),
        "recouvrement_ticket_top8_marche": len(set(S) & set(_best_market)),
        "note": "E[captures]=somme des P(Top5) du ticket. Le manque à gagner 'ticket_selon_modele' vs "
                "'top8_modele_pur' mesure ce que coûtent les contraintes (quota, couverture marché...) "
                "SI les probabilités du modèle sont justes.",
    }
    return {
        "captures_attendues": captures_attendues,
        "p_boost_preclamp": [round(x, 5) for x in _p_boost_preclamp],
        "p_boost": [round(x, 5) for x in p_boost],
        "pi_top5_modele": [round(x, 4) for x in _pi_model],
        "pool_elargi": pool,
        "pool_trace": pool_trace,
        "selection": S,
        "log": log,
        "flags": flags,
        "p_top5_in_ticket": p_top5_final,
        "masse_residuelle": masse_residuelle,
        "statut_couverture": statut_couverture,
        "p_i": p,
        "q_top5": q_top5,
        "axes": {k: [round(x, 4) for x in v] for k, v in axes.items()},
        "roles": [],
        "roles_ticket": {},
        "roles_report": role_report,
        "operational_model": {
            "model_version": op_manifest.get("model_version"),
            "weight": op_manifest.get("weight"),
            "status": op_manifest.get("status"),
        },
        "top5_metrics": top5_stats,
        "gain_weights": {"w_pl": hw["w_pl"], "w_q": hw["w_q"], "w_pb": hw["w_pb"]},
        "hybrid_weights": hw,
        "guidance": {
            "n_partants": n_partants,
            "cible_ge12": n_partants >= 12,
            "bande_prioritaire": False,
            "hors_kpi_ge17": False,
            "market_blend_applique": blend,
            "market_blend_cap": 0.22,
            "proxy_sans_double_marche": True,
            "softmax_tau": tau,
            "icp_blend_weight": 0.05,
            "hillclimb_swaps": n_swaps,
            "prob_model": "hybrid_pl+q_top5+axes+sigma_q_guard",
            "roles_enabled": False,  # définitif: module rôles retiré
            "noyau_enabled": False,
            "forme_discipline_filter": True,
            "hybrid_select": "v1.29.30-p1p6",
            "market_min_top3": int(hw.get("market_min", 2)),
        },
    }
