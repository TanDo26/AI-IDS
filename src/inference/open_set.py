"""
Open-set decision per flow: known attack, unknown, or benign.

    classifier says attack, confident        -> known_attack  (reason: known)
    classifier says attack, not confident    -> unknown       (reason: low_confidence)
    classifier says benign, anomalous        -> unknown       (reason: anomalous)
    classifier says benign, not anomalous    -> benign        (reason: benign)

The classifier runs first, so known attacks never depend on the anomaly detector.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.ensemble._iforest import _average_path_length

BENIGN, KNOWN_ATTACK, UNKNOWN = "benign", "known_attack", "unknown"


def anomaly_scores(detector, X) -> np.ndarray:
    """Higher = less like the benign traffic the detector was fitted on."""
    if isinstance(detector, IsolationForest) and hasattr(detector, "_decision_path_lengths"):
        return _isolation_scores(detector, X)
    return -detector.score_samples(X)


def _isolation_scores(forest: IsolationForest, X) -> np.ndarray:
    """-forest.score_samples(X), bit for bit, about 10x faster for a single flow.

    scikit-learn 1.9 calls each of the 200 trees through joblib with input checks, about 0.1 ms per
    tree whatever the batch size. This is its _compute_score_samples with the trees' compiled apply()
    called directly: same leaves, same per-tree arrays, same summation order. Tested against
    score_samples in tests/test_inference.py; scikit-learn's major.minor is pinned with the bundle.
    """
    X = np.asarray(X, dtype=np.float32)
    subsample = forest._max_features != X.shape[1]
    depths = np.zeros(X.shape[0], order="f")
    for tree, features, path_lengths, average_lengths in zip(
            forest.estimators_, forest.estimators_features_,
            forest._decision_path_lengths, forest._average_path_length_per_tree):
        leaves = tree.tree_.apply(np.ascontiguousarray(X[:, features]) if subsample else X)
        depths += path_lengths[leaves] + average_lengths[leaves] - 1.0
    denominator = len(forest.estimators_) * _average_path_length([forest._max_samples])
    return 2 ** -np.divide(depths, denominator, out=np.ones_like(depths), where=denominator != 0)


def known_thresholds(thresholds: dict, classes) -> np.ndarray:
    """Confidence threshold per class, aligned with classes (global threshold where none was calibrated)."""
    per_class = thresholds.get("known_per_class", {})
    return np.array([per_class.get(str(int(c)), thresholds["known"]) for c in classes], dtype=float)


def decide(proba, classes, anomaly, benign_class, tau_known, tau_anomaly) -> pd.DataFrame:
    """tau_known: one threshold for all classes, or an array aligned with classes."""
    classes = np.asarray(classes)
    top = proba.argmax(axis=1)
    predicted = classes[top]
    confidence = proba[np.arange(len(proba)), top]
    benign_col = int(np.flatnonzero(classes == benign_class)[0])
    tau = np.asarray(tau_known, dtype=float)

    says_attack = predicted != benign_class
    known = says_attack & (confidence >= (tau[top] if tau.ndim else tau))
    low_confidence = says_attack & ~known
    anomalous = ~says_attack & (anomaly > tau_anomaly)

    decision = np.full(len(proba), BENIGN, dtype=object)
    decision[known] = KNOWN_ATTACK
    decision[low_confidence | anomalous] = UNKNOWN

    reason = np.full(len(proba), "benign", dtype=object)
    reason[known] = "known"
    reason[low_confidence] = "low_confidence"
    reason[anomalous] = "anomalous"

    return pd.DataFrame({
        "decision": decision,
        "reason": reason,
        "predicted_class": predicted,
        "confidence": confidence,
        "attack_score": 1.0 - proba[:, benign_col],
        "anomaly_score": anomaly,
    })
