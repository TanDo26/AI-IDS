"""
Gaussian Naive Bayes model builder.
"""

from sklearn.naive_bayes import GaussianNB


def build_naive_bayes(config, model_name="naive_bayes", class_weight=None):
    # class_weight is applied as sample_weight in train.py (GaussianNB has no class_weight)
    nb_cfg = config["models"].get(model_name, config["models"]["naive_bayes"])
    return GaussianNB(
        var_smoothing=nb_cfg.get("var_smoothing", 1e-9),
    )
