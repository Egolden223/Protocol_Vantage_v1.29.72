"""continuous_learning.py -- Apprentissage continu du Ranker shadow
(v1.29.15). Accumule un exemple d'entraînement pour CHAQUE cheval après
CHAQUE audit post-course confirmé (arrivée réelle connue), et réentraîne
périodiquement un modèle LightGBM (si le package est installé) prédisant
"ce cheval a-t-il fini dans le Top5 réel ?".

Reste strictement SHADOW, comme app/ml/ranker_shadow.py dont il
réutilise les features : ticket_impact=False, ne modifie JAMAIS le
ticket certifié. Ce module améliore uniquement la qualité du signal
informatif affiché à côté du ticket. Faire un jour influencer le ticket
par ces prédictions resterait une décision humaine explicite (un
nouveau flag dédié, à activer sciemment après validation walk-forward),
jamais un effet de bord automatique de ce module.

Persistance : /data/ml/ (même volume que db.py, cf. Dockerfile) --
training_log.jsonl (append-only, jamais réécrit), shadow_model.txt
(modèle LightGBM le plus récent), shadow_meta.json (métadonnées :
date, nb d'exemples, AUC in-sample -- PAS un backtest walk-forward).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.models import RaceResult
from app.ml.ranker_shadow import _features

logger = logging.getLogger("vantage.continuous_learning")

_lock = threading.Lock()

DATA_DIR = os.environ.get("VANTAGE_ML_DATA_DIR", "/data/ml")
TRAINING_LOG_PATH = os.path.join(DATA_DIR, "training_log.jsonl")
MODEL_PATH = os.path.join(DATA_DIR, "shadow_model.txt")
META_PATH = os.path.join(DATA_DIR, "shadow_meta.json")

MIN_EXAMPLES_TO_TRAIN = int(os.environ.get("VANTAGE_ML_MIN_EXAMPLES", "40"))
MIN_NEW_SINCE_RETRAIN = int(os.environ.get("VANTAGE_ML_MIN_NEW_RETRAIN", "5"))

FEATURE_KEYS = [
    "pch", "composite", "ordre", "signal_strength", "family_strength",
    "implied_prob", "form_place_rate_5", "form_win_rate_5",
    "form_consistency_5", "tocard", "pct_ordre_in_field", "icp",
]


def _ensure_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def record_race_outcome(race_id: str, result: RaceResult, arrival: List[Any]) -> Dict[str, Any]:
    """arrival : List[ArrivalHorse] (attributs rang, numero, nom) --
    l'arrivée réelle confirmée, produite par
    post_race_audit.confirm_arrival(). Ne lève jamais : en cas
    d'échec, retourne un statut ERROR et le pipeline/l'audit continue
    sans interruption.
    """
    try:
        _ensure_dir()
        top5_numeros = {a.numero for a in arrival if getattr(a, "rang", 999) <= 5}
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for h in result.horses:
            feats = _features(h)
            label = 1 if h.cheval.numero in top5_numeros else 0
            rows.append({
                "race_id": race_id,
                "recorded_at": now,
                "numero": h.cheval.numero,
                "nom": h.cheval.nom,
                "features": feats,
                "label": label,
            })
        with _lock, open(TRAINING_LOG_PATH, "a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {"status": "OK", "n_added": len(rows)}
    except Exception as e:
        logger.warning("continuous_learning: échec enregistrement pour %s: %s", race_id, e)
        return {"status": "ERROR", "error": str(e)}


def _read_training_log() -> List[Dict[str, Any]]:
    if not os.path.exists(TRAINING_LOG_PATH):
        return []
    rows: List[Dict[str, Any]] = []
    with open(TRAINING_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _read_meta() -> Dict[str, Any]:
    default = {"n_examples_at_last_train": 0, "trained_at": None, "backend": None}
    if not os.path.exists(META_PATH):
        return default
    try:
        with open(META_PATH, "r", encoding="utf-8") as f:
            return {**default, **json.load(f)}
    except (json.JSONDecodeError, OSError):
        return default


def _has_lightgbm() -> bool:
    try:
        import lightgbm  # noqa: F401
        return True
    except Exception:
        return False


def maybe_retrain() -> Dict[str, Any]:
    """Réentraîne le modèle shadow si assez de NOUVEAUX exemples se sont
    accumulés depuis le dernier entraînement. Ne lève jamais -- appelée
    juste après record_race_outcome(), doit rester silencieuse en cas
    d'échec (LightGBM absent, données insuffisantes, etc.)."""
    try:
        rows = _read_training_log()
        n_total = len(rows)
        if n_total < MIN_EXAMPLES_TO_TRAIN:
            return {"status": "PAS_ASSEZ_EXEMPLES", "n_total": n_total, "requis": MIN_EXAMPLES_TO_TRAIN}

        meta = _read_meta()
        n_since = n_total - meta.get("n_examples_at_last_train", 0)
        if n_since < MIN_NEW_SINCE_RETRAIN:
            return {"status": "PAS_DE_NOUVEAU", "n_total": n_total, "n_nouveaux": n_since}

        if not _has_lightgbm():
            return {
                "status": "LIGHTGBM_ABSENT", "n_total": n_total,
                "note": "Ranker shadow reste en mode heuristique (backend LightGBM non installé).",
            }

        import lightgbm as lgb

        X = [[r["features"].get(k, 0.0) for k in FEATURE_KEYS] for r in rows]
        y = [r["label"] for r in rows]

        if len(set(y)) < 2:
            return {"status": "LABELS_INSUFFISANTS", "n_total": n_total,
                    "note": "Toutes les étiquettes identiques (aucun ou tous top5) -- entraînement reporté."}

        model = lgb.LGBMClassifier(
            n_estimators=100, max_depth=4, learning_rate=0.05,
            min_child_samples=5, verbosity=-1,
        )
        model.fit(X, y)

        _ensure_dir()
        model.booster_.save_model(MODEL_PATH)

        # Auto-évaluation IN-SAMPLE (indicative seulement -- ce n'est PAS
        # un backtest walk-forward, il n'y a pas de split temporel ici.
        # Jamais à présenter comme une performance garantie hors
        # échantillon.
        auc_in_sample = None
        try:
            from sklearn.metrics import roc_auc_score
            preds = model.predict_proba(X)[:, 1]
            auc_in_sample = float(roc_auc_score(y, preds))
        except Exception:
            pass

        meta_out = {
            "n_examples_at_last_train": n_total,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "backend": "lightgbm",
            "feature_keys": FEATURE_KEYS,
            "auc_in_sample": auc_in_sample,
            "avertissement": "auc_in_sample n'est PAS un backtest walk-forward -- indicatif uniquement, ne pas s'y fier pour juger la qualité réelle.",
        }
        with open(META_PATH, "w", encoding="utf-8") as f:
            json.dump(meta_out, f, ensure_ascii=False, indent=2)

        logger.info("continuous_learning: modèle shadow réentraîné (%s exemples, AUC in-sample=%s)",
                    n_total, auc_in_sample)
        return {"status": "OK", **meta_out}
    except Exception as e:
        logger.warning("continuous_learning: échec réentraînement: %s", e)
        return {"status": "ERROR", "error": str(e)}


def get_learning_status() -> Dict[str, Any]:
    """Utilisé par /health et par un futur endpoint dédié -- transparence
    sur l'état de l'apprentissage continu (nb d'exemples, modèle présent
    ou non, date du dernier entraînement)."""
    try:
        rows = _read_training_log()
        meta = _read_meta()
        return {
            "n_examples_total": len(rows),
            "min_examples_to_train": MIN_EXAMPLES_TO_TRAIN,
            "min_new_since_retrain": MIN_NEW_SINCE_RETRAIN,
            "lightgbm_available": _has_lightgbm(),
            "model_trained": os.path.exists(MODEL_PATH),
            **meta,
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


def load_trained_model():
    """Retourne un lgb.Booster chargé, ou None si absent/erreur. Le
    fallback heuristique de ranker_shadow.py s'applique automatiquement
    si cette fonction retourne None -- jamais d'exception ici."""
    if not os.path.exists(MODEL_PATH):
        return None
    try:
        import lightgbm as lgb
        return lgb.Booster(model_file=MODEL_PATH)
    except Exception as e:
        logger.warning("continuous_learning: échec chargement modèle: %s", e)
        return None
