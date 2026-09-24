"""
Random Forest model builder.
"""

from sklearn.ensemble import RandomForestClassifier


def build_random_forest(config, model_name="random_forest"):
    rf_cfg = config["models"].get(model_name, config["models"]["random_forest"])
    return RandomForestClassifier(
        n_estimators=rf_cfg.get("n_estimators", 200),
        max_depth=rf_cfg.get("max_depth"),
        min_samples_split=rf_cfg.get("min_samples_split", 2),
        min_samples_leaf=rf_cfg.get("min_samples_leaf", 1),
        max_features=rf_cfg.get("max_features", "sqrt"),
        random_state=rf_cfg.get("random_state", 42),
        n_jobs=rf_cfg.get("n_jobs", -1),
    )