"""
Logistic Regression model builder.
"""

from sklearn.linear_model import LogisticRegression

def build_logistic_regression(weighted=True, **kwargs):
    params = {
        "class_weight": "balanced" if weighted else None, 
        "max_iter": 1000,
        "solver": "lbfgs",
        "random_state": 42
    }

    params.update(kwargs)

    return LogisticRegression(**params)