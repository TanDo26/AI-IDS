"""
XGBoost model builder.
"""

from xgboost import XGBClassifier

from .label_encoded import LabelEncodedClassifier


def _resolve_device(device):
    # XGBoost does not fall back to CPU on its own
    if device != "auto":
        return device
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def build_xgboost(config, model_name="xgboost", class_weight=None):
    # class_weight is applied as sample_weight in train.py (XGBClassifier has no class_weight)
    xgb_cfg = config["models"].get(model_name, config["models"]["xgboost"])
    model = XGBClassifier(
        n_estimators=xgb_cfg.get("n_estimators", 300),
        max_depth=xgb_cfg.get("max_depth", 8),
        learning_rate=xgb_cfg.get("learning_rate", 0.1),
        subsample=xgb_cfg.get("subsample", 0.8),
        colsample_bytree=xgb_cfg.get("colsample_bytree", 0.8),
        min_child_weight=xgb_cfg.get("min_child_weight", 1),
        gamma=xgb_cfg.get("gamma", 0.0),
        tree_method=xgb_cfg.get("tree_method", "hist"),
        device=_resolve_device(xgb_cfg.get("device", "auto")),
        random_state=xgb_cfg.get("random_state", 42),
        n_jobs=xgb_cfg.get("n_jobs", -1),
    )
    return LabelEncodedClassifier(model)
