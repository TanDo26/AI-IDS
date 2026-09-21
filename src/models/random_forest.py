"""
Random Forest model builder.
"""

from sklearn.ensemble import RandomForestClassifier

def build_random_forest(
    weighted=True,
    **kwargs
):
    params = {
        "n_estimators": 200,
        "class_weight": "balanced" if weighted else None,
        "max_depth": None,
        "min_samples_leaf": 2,
        "random_state": 42,
        "n_jobs": -1,
        "verbose": 1
    }

    params.update(kwargs)

    return RandomForestClassifier(**params)