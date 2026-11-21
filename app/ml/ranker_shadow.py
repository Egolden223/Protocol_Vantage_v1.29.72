"""Sidecar Ranker shadow (v1.25) adapté List[HorseScore].

N'écrit JAMAIS dans PCH / COMPOSITE / ORDRE. Ticket certifié inchangé.
Heuristique déterministe si LightGBM absent.
"""
from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional

from app.models import HorseScore
from app.engine.common import clamp
from app.engine.musique_features import score_musique_composite

MODEL_VERSION = "VANTAGE_RANKER_SHADOW_V1_0"
FEATURE_VERSION = "VANTAGE_PRE_RACE_FEATURES_V1_1_TOP5"
DEFAULT_SHADOW_WEIGHT = 0.15


def shadow_enabled() -> bool:
    val = os.environ.get("VANTAGE_ML_SHADOW", "1").strip().lower()
    return val not in {"0", "false", "no", "off"}


def _has_lightgbm() -> bool:
    try:
        import lightgbm  # noqa: F401
        return True
    except Exception:
        return False


def _features(h: HorseScore) -> Dict[str, float]:
    cote = h.cheval.cote_avant_course or h.cheval.cote_matin
    impl = 0.0
    if cote is not None and cote > 1.01:
        impl = clamp(0.0, 1.0, 1.0 / float(cote))
    mus = score_musique_composite(getattr(h.cheval, "musique", None), None)
    active = len(h.breakdown.signaux_actifs or [])
    icp = float(h.cheval.icp_global or 0) / 8.0
    return {
        "pch": clamp(0.0, 1.0, float(h.breakdown.pch_norm or 0)),
        "composite": clamp(0.0, 1.0, float(h.synthesis.composite or 0)),
        "ordre": clamp(0.0, 1.0, float(h.synthesis.ordre_final or 0)),
        "signal_strength": clamp(0.0, 1.0, active / 12.0),
        "family_strength": 0.0,
        "implied_prob": impl,
        "form_place_rate_5": mus,
        "form_win_rate_5": mus * 0.6,
        "form_consistency_5": mus,
        "tocard": 1.0 if (cote or 0) >= 15 else 0.0,
        "pct_ordre_in_field": 0.5,
        "icp": clamp(0.0, 1.0, icp),
    }


def _heuristic_score(feats: Dict[str, float], *, no_odds: bool = False) -> float:
    score = (
        0.22 * feats["pch"]
        + 0.18 * feats["composite"]
        + 0.15 * feats["ordre"]
        + 0.12 * feats["form_place_rate_5"]
        + 0.08 * feats["form_win_rate_5"]
        + 0.07 * feats["form_consistency_5"]
        + 0.08 * feats["signal_strength"]
        + 0.05 * feats.get("icp", 0.0)
        + 0.05 * feats["pct_ordre_in_field"]
    )
    if no_odds:
        score = 0.85 * score + 0.15 * (0.4 * feats["tocard"] + 0.3 * feats["signal_strength"] + 0.3 * feats["form_place_rate_5"])
    else:
        score = 0.88 * score + 0.12 * feats["implied_prob"]
    return clamp(0.0, 1.0, score)


def _softmax(scores: List[float], temperature: float = 1.0) -> List[float]:
    if not scores:
        return []
    T = max(0.05, temperature)
    m = max(scores)
    exps = [math.exp((s - m) / T) for s in scores]
    z = sum(exps) or 1.0
    return [e / z for e in exps]


def rank_race_heuristic(horses: List[HorseScore], *, no_odds: bool = False) -> Dict[str, Any]:
    feats_list = [_features(h) for h in horses]
    scores = [_heuristic_score(f, no_odds=no_odds) for f in feats_list]
    probs = _softmax(scores, temperature=0.5)
    ranked = sorted(
        [
            {
                "numero": horses[i].cheval.numero,
                "nom": horses[i].cheval.nom,
                "shadow_score": round(scores[i], 6),
                "p_win_shadow": round(probs[i], 6),
            }
            for i in range(len(horses))
        ],
        key=lambda x: x["shadow_score"],
        reverse=True,
    )
    return {
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "backend": "heuristic",
        "no_odds": no_odds,
        "partants": ranked,
        "top5_numbers": [p["numero"] for p in ranked[:5]],
    }


def apply_ranker_shadow(horses: List[HorseScore]) -> Optional[Dict[str, Any]]:
    """Produit un manifeste shadow. ticket_impact=False toujours.

    Utilise le modèle appris en continu (v1.29.15, cf.
    app/ml/continuous_learning.py) s'il est disponible ; retombe sur
    l'heuristique déterministe sinon (LightGBM absent, pas encore assez
    d'exemples accumulés, ou toute erreur de chargement/prédiction).
    Import différé pour éviter tout cycle d'import avec
    continuous_learning.py (qui importe _features d'ici)."""
    if not shadow_enabled() or not horses:
        return None

    no_odds = rank_race_heuristic(horses, no_odds=True)
    result = None

    try:
        from app.ml.continuous_learning import load_trained_model, FEATURE_KEYS
        booster = load_trained_model()
    except Exception:
        booster = None

    if booster is not None:
        try:
            feats_list = [_features(h) for h in horses]
            X = [[f.get(k, 0.0) for k in FEATURE_KEYS] for f in feats_list]
            preds = booster.predict(X)
            probs = [clamp(0.0, 1.0, float(p)) for p in preds]
            ranked = sorted(
                [
                    {
                        "numero": horses[i].cheval.numero,
                        "nom": horses[i].cheval.nom,
                        "shadow_score": round(probs[i], 6),
                        "p_win_shadow": round(probs[i], 6),
                    }
                    for i in range(len(horses))
                ],
                key=lambda x: x["shadow_score"],
                reverse=True,
            )
            result = {
                "backend": "lightgbm_trained",
                "top5_numbers": [p["numero"] for p in ranked[:5]],
                "partants": ranked,
            }
        except Exception as e:  # défense en profondeur -- ne bloque jamais le shadow
            result = None

    if result is None:
        result = rank_race_heuristic(horses, no_odds=False)

    return {
        "status": "SHADOW",
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "backend": result["backend"],
        "lightgbm_available": _has_lightgbm(),
        "shadow_weight": DEFAULT_SHADOW_WEIGHT,
        "ticket_impact": False,
        "note": (
            "Sidecar informatif. Ne modifie pas le ticket CERTIFIÉ. "
            "Modèle appris (si backend=lightgbm_trained) non validé en walk-forward -- indicatif."
        ),
        "top5_numbers": result["top5_numbers"],
        "top5_no_odds": no_odds["top5_numbers"],
        "partants": result["partants"],
        "n_partants": len(horses),
    }
