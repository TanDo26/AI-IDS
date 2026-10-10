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

BENIGN, KNOWN_ATTACK, UNKNOWN = "benign", "known_attack", "unknown"


def anomaly_scores(detector, X) -> np.ndarray:
    """Higher = less like the benign traffic the detector was fitted on."""
    return -detector.score_samples(X)


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
