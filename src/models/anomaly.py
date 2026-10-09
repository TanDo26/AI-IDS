"""
Anomaly detector for unknown-attack detection: an Isolation Forest fitted on benign flows.
"""

from sklearn.ensemble import IsolationForest


def build_anomaly_detector(config):
    os_cfg = config["open_set"]
    kind = os_cfg.get("anomaly_detector", "isolation_forest")
    if kind != "isolation_forest":
        raise ValueError(f"Unknown anomaly detector '{kind}'. Available: isolation_forest")
    return IsolationForest(
        n_estimators=os_cfg.get("n_estimators", 200),
        max_samples=os_cfg.get("max_samples", 256),
        random_state=os_cfg.get("random_state", 42),
        n_jobs=-1,
    )
