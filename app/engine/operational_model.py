"""Modèle opérationnel Vantage v1.1-TOP5 (porté de v1.26, adapté HorseScore).

Baseline déterministe versionné : transforme les signaux pré-course en
probabilité relative, puis mélange avec ORDRE_FINAL. N'écrit pas dans PCH.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from app.models import HorseScore
from app.engine.common import clamp
from app.engine.musique_features import score_musique_composite

MODEL_VERSION = "VANTAGE_OP_BASELINE_V1_1_TOP5"
FEATURE_VERSION = "VANTAGE_PRE_RACE_FEATURES_V1_1_TOP5"
OPERATIONAL_WEIGHT = 0.25


def _norm_score(value: Any) -> float:
    try:
        v = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if v > 1.0:
        v = v / 100.0
    return clamp(0.0, 1.0, v)


def _market_prior(h: HorseScore) -> Optional[float]:
    cote = h.cheval.cote_avant_course or h.cheval.cote_matin
    try:
        c = float(cote) if cote is not None else None
    except (TypeError, ValueError):
        return None
    if c is None or c <= 1.0:
        return None
    return clamp(0.0, 1.0, 1.0 / c)


def _market_prior_top5(h: HorseScore) -> Optional[float]:
    """Prior marché élargi pour Top-5 : 1.35 / cote^0.85 (v1.24)."""
    cote = h.cheval.cote_avant_course or h.cheval.cote_matin
    try:
        c = float(cote) if cote is not None else None
    except (TypeError, ValueError):
        return None
    if c is None or c <= 1.0:
        return None
    return clamp(0.02, 0.85, 1.35 / (c ** 0.85))


def _feature_vector(h: HorseScore) -> Dict[str, float]:
    bd = h.breakdown
    active = 0
    try:
        active = sum(1 for s in (bd.signaux_actifs or []) if s)
    except Exception:
        active = len(bd.signaux_actifs or [])
    families = 0
    try:
        fam = set()
        for s in (bd.signaux_actifs or []):
            if isinstance(s, dict) and s.get("id"):
                fam.add(str(s["id"])[:1])
            elif isinstance(s, dict) and s.get("famille"):
                fam.add(str(s["famille"]))
        families = len(fam)
    except Exception:
        families = 0
    icp = clamp(0.0, 1.0, float(h.cheval.icp_global or 0) / 8.0)
    mus = score_musique_composite(
        getattr(h.cheval, "musique", None),
        getattr(h.cheval, "deferre", None),
    )
    return {
        "pch": _norm_score(bd.pch_norm),
        "composite": _norm_score(h.synthesis.composite),
        "ordre": _norm_score(h.synthesis.ordre_final),
        "signal_strength": clamp(0.0, 1.0, active / 12.0),
        "family_strength": clamp(0.0, 1.0, families / 5.0),
        "icp": icp,
        "musique_forme": mus,
    }


def score_horse(h: HorseScore, weight: float = OPERATIONAL_WEIGHT) -> Dict[str, Any]:
    weight = clamp(0.0, 1.0, float(weight))
    features = _feature_vector(h)
    market = _market_prior(h)
    evidence = (
        0.26 * features["pch"]
        + 0.20 * features["composite"]
        + 0.16 * features["ordre"]
        + 0.12 * features["signal_strength"]
        + 0.10 * features["family_strength"]
        + 0.08 * features.get("icp", 0.0)
        + 0.08 * features.get("musique_forme", 0.5)
    )
    if market is not None:
        evidence = 0.85 * evidence + 0.15 * market  # correctif double marché 14/09
    model_probability = clamp(0.0, 1.0, evidence)
    base = _norm_score(h.synthesis.ordre_final)
    operational_score = (1.0 - weight) * base + weight * model_probability
    return {
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "status": "OPERATIONAL",
        "weight": weight,
        "model_probability": round(model_probability, 8),
        "base_order_score": round(base, 8),
        "operational_order_score": round(operational_score, 8),
        "market_prior": None if market is None else round(market, 8),
        "market_prior_top5": (
            None if _market_prior_top5(h) is None else round(_market_prior_top5(h), 8)
        ),
        "features": {k: round(v, 8) for k, v in features.items()},
        "pre_race_only": True,
        "ticket_impact": weight > 0,
    }


def apply_operational_model(
    horses: List[HorseScore], weight: float = OPERATIONAL_WEIGHT
) -> Dict[str, Any]:
    """Calcule le score opérationnel pour chaque cheval.

    Stocke le résultat dans synthesis.flags (tag) et retourne un manifeste
    + listes alignées sur `horses` pour GMO-V.
    """
    records: Dict[str, Any] = {}
    op_scores: List[float] = []
    model_ps: List[float] = []
    for h in horses:
        rec = score_horse(h, weight)
        records[str(h.cheval.numero)] = rec
        op_scores.append(rec["operational_order_score"])
        model_ps.append(rec["model_probability"])
        tag = "OP_MODEL_V1_1_TOP5"
        if tag not in h.breakdown.flags:
            h.breakdown.flags.append(tag)
        # conserve le score pour usages aval (GMO p_boost)
        h.breakdown.flags = [f for f in h.breakdown.flags if not f.startswith("OP_SCORE=")]
        h.breakdown.flags.append(f"OP_SCORE={rec['operational_order_score']:.6f}")
        h.breakdown.flags.append(f"OP_MODEL_P={rec['model_probability']:.6f}")
    return {
        "status": "OPERATIONAL",
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "weight": weight,
        "ticket_impact": weight > 0,
        "partants": records,
        "op_scores": op_scores,
        "model_probabilities": model_ps,
    }


def proxy_blended_p_top5(h: HorseScore, model_p: Optional[float] = None) -> Dict[str, Any]:
    """P(Top5) proxy multi-signaux (v1.24) pour observabilité / boost."""
    if model_p is None:
        model_p = score_horse(h)["model_probability"]
    market_p = _market_prior_top5(h)
    order_p = _norm_score(h.synthesis.ordre_final)
    components = []
    weights = []
    if model_p is not None:
        components.append(model_p)
        weights.append(0.45)
    if market_p is not None:
        components.append(market_p)
        weights.append(0.25)
    components.append(order_p)
    weights.append(0.30 if model_p is not None else 0.55)
    total_w = sum(weights) or 1.0
    blended = sum(c * w for c, w in zip(components, weights)) / total_w
    blended = clamp(0.0, 1.0, blended)
    return {
        "status": "PROXY_BLENDED",
        "value": round(blended, 6),
        "components": {
            "model_probability": None if model_p is None else round(model_p, 6),
            "market_prior_top5": None if market_p is None else round(market_p, 6),
            "order_score_norm": round(order_p, 6),
        },
    }
