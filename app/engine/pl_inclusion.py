"""pl_inclusion.py -- Plackett-Luce / Harville exact et rapide (v1.29.41).

Une seule programmation dynamique sur les sous-ensembles (bitmasks) donne la
loi COMPLÈTE de l'ensemble des 5 premiers :
    dp[T] = P(les 5 premiers sont exactement T)      (|T| = 5)
dont on tire, sans simulation et en quelques ms (N <= 20) :
  * pi_i  = P(i dans le Top5)            -> objectif SÉPARABLE
  * P(Top5 ⊂ S)                          -> somme de dp[T] sur les T ⊂ S
  * E[captures] = somme des pi_i, i ∈ S  -> vraie mesure de rendement d'un ticket

Pourquoi : maximiser E[captures] est séparable (on prend les 8 plus grands pi_i)
alors que P(Top5 ⊂ S) vaut 1-15 % et varie à peine d'un ticket à l'autre : c'est
une métrique de vitrine, pas un objectif d'optimisation exploitable.
"""
from __future__ import annotations
from functools import lru_cache
from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple


@lru_cache(maxsize=8)
def _top_k_distribution(p: Tuple[float, ...], k: int = 5) -> Dict[int, float]:
    n = len(p)
    tot = sum(p) or 1.0
    w = [max(1e-12, x / tot) for x in p]
    layer: Dict[int, float] = {0: 1.0}
    sums: Dict[int, float] = {0: 0.0}
    for _ in range(min(k, n)):
        nxt: Dict[int, float] = {}
        nsums: Dict[int, float] = {}
        for mask, pr in layer.items():
            rest = 1.0 - sums[mask]
            if rest <= 1e-12:
                continue
            for i in range(n):
                bit = 1 << i
                if mask & bit:
                    continue
                m2 = mask | bit
                nxt[m2] = nxt.get(m2, 0.0) + pr * w[i] / rest
                nsums[m2] = sums[mask] + w[i]
        layer, sums = nxt, nsums
    return layer


def top_k_distribution(p: Sequence[float], k: int = 5) -> Dict[int, float]:
    return _top_k_distribution(tuple(float(x) for x in p), k)


def inclusion_probs(p: Sequence[float], k: int = 5) -> List[float]:
    dist = top_k_distribution(p, k)
    n = len(p)
    pi = [0.0] * n
    for mask, pr in dist.items():
        for i in range(n):
            if mask >> i & 1:
                pi[i] += pr
    return pi


def coverage(p: Sequence[float], subset: Sequence[int], k: int = 5) -> float:
    """P(les k premiers sont tous dans subset) -- exact."""
    subset = list(subset)
    if len(subset) < k:
        return 0.0
    dist = top_k_distribution(p, k)
    total = 0.0
    for comb in combinations(subset, k):
        m = 0
        for i in comb:
            m |= 1 << i
        total += dist.get(m, 0.0)
    return total


def expected_hits(pi: Sequence[float], subset: Sequence[int]) -> float:
    return float(sum(pi[i] for i in subset))


def best_expected_subset(pi: Sequence[float], size: int = 8) -> List[int]:
    return sorted(range(len(pi)), key=lambda i: -pi[i])[:size]


# --- Probabilités de marché sans marge (ex-probabilites_marche.py, fusionné en v1.29.42) ---
# La somme des 1/cote dépasse 100 % (overround PMU ~15-25 %) ; normalisation proportionnelle.
# N'altère aucun signal existant : exposé comme information (probabilite_marche_vraie / overround).
def compute_probabilites_marche(champ: List) -> Tuple[Dict[int, float], Optional[float]]:
    """Retourne ({numero: probabilite_vraie}, overround). overround est
    la marge du marché (0.20 = 20%) ou None si moins de 2 cotes
    disponibles dans le champ (rien à normaliser)."""
    brutes = {c.numero: 1.0 / c.cote_matin for c in champ if c.cote_matin and c.cote_matin > 0}
    if len(brutes) < 2:
        return {}, None

    total = sum(brutes.values())
    if total <= 0:
        return {}, None

    overround = total - 1.0
    probabilites = {numero: p / total for numero, p in brutes.items()}
    return probabilites, overround


# ===== top5_metrics.py (fusionné en v1.29.42) =====
# Métriques de capture Top-5 (porté v1.24, adapté ticket Protocol Vantage).
from typing import Any, Dict, List, Optional, Sequence

from app.models import HorseScore, TicketSlot


def _tranche_label(h: HorseScore) -> str:
    t = h.synthesis.tranche
    if t is not None:
        return t.value if hasattr(t, "value") else str(t)
    cote = h.cheval.cote_matin
    if cote is None:
        return "INCONNU"
    if cote <= 5:
        return "T1"
    if cote <= 8:
        return "T2"
    if cote <= 15:
        return "T3"
    return "T4"


def compute_ticket_top5_stats(
    horses: Sequence[HorseScore],
    selection_indices: Sequence[int],
    arrived_top5: Optional[Sequence[int]] = None,
    p_top5_quality: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Stats de capture pour un ticket de 8 (P1-P5 core + R)."""
    sel = list(selection_indices or [])
    core_idx = sel[:5]
    res_idx = sel[5:]
    core_nums = [horses[i].cheval.numero for i in core_idx if 0 <= i < len(horses)]
    res_nums = [horses[i].cheval.numero for i in res_idx if 0 <= i < len(horses)]

    tranche_counts: Dict[str, int] = {}
    for i in core_idx:
        if 0 <= i < len(horses):
            lab = _tranche_label(horses[i])
            tranche_counts[lab] = tranche_counts.get(lab, 0) + 1

    quality = p_top5_quality or {"observed": 0, "blended": 0, "naive_proxy": 0}
    n_core = max(1, len(core_nums))
    qscore = (
        quality.get("observed", 0) * 1.0
        + quality.get("blended", 0) * 0.7
        + quality.get("naive_proxy", 0) * 0.3
    ) / n_core

    stats: Dict[str, Any] = {
        "version": "v1.24-top5+prod-1309",
        "core_size": len(core_nums),
        "reserve_size": len(res_nums),
        "core_numbers": core_nums,
        "reserve_numbers": res_nums,
        "all_ticket_numbers": core_nums + res_nums,
        "tranche_distribution": tranche_counts,
        "p_top5_quality": {
            **quality,
            "quality_score": round(qscore, 3),
        },
    }

    if arrived_top5 is not None:
        arrived = set(int(x) for x in arrived_top5)
        hits_core = [n for n in core_nums if n in arrived]
        hits_res = [n for n in res_nums if n in arrived]
        all_ticket = set(core_nums + res_nums)
        hits_all = [n for n in arrived if n in all_ticket]
        stats["post_course"] = {
            "arrived_top5": sorted(arrived),
            "hits_in_core": hits_core,
            "hits_in_reserve": hits_res,
            "hit_count_core": len(hits_core),
            "hit_count_ticket8": len(hits_all),
            "hit_rate_core": round(len(hits_core) / 5.0, 3),
            "hit_rate_ticket8": round(len(hits_all) / 5.0, 3),
            "coverage_including_reserves": round(len(hits_all) / 5.0, 3),
        }
    return stats


def stats_from_ticket_slots(
    ticket: Sequence[TicketSlot],
    arrived_top5: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    """Variante à partir des TicketSlot (après build_ticket)."""
    nums = [s.numero for s in ticket]
    core, res = nums[:5], nums[5:]
    stats: Dict[str, Any] = {
        "version": "v1.24-top5+prod-1309",
        "core_numbers": core,
        "reserve_numbers": res,
        "all_ticket_numbers": nums,
    }
    if arrived_top5 is not None:
        arrived = set(int(x) for x in arrived_top5)
        hits = [n for n in nums if n in arrived]
        stats["post_course"] = {
            "arrived_top5": sorted(arrived),
            "hit_count_ticket8": len(hits),
            "hit_rate_ticket8": round(len(hits) / 5.0, 3),
            "hits": hits,
        }
    return stats
