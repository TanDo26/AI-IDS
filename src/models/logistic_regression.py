"""
Logistic Regression model builder.
"""

from sklearn.linear_model import LogisticRegression


def build_logistic_regression(config, model_name="logistic_regression"):
    lr_cfg = config["models"].get(model_name, config["models"]["logistic_regression"])
    return LogisticRegression(
        max_iter=lr_cfg.get("max_iter", 1000),
        C=lr_cfg.get("C", 1.0),
        solver=lr_cfg.get("solver", "lbfgs"),
        random_state=lr_cfg.get("random_state", 42),
    )