"""
Class weighting utilities for imbalanced multiclass classification.
"""

from imblearn.over_sampling import SMOTE
from sklearn.neighbors import NearestNeighbors


def apply_smote(X_train, y_train, config: dict):

    smote_cfg = config["imbalance"]["smote"]
    
    nn = NearestNeighbors(
        n_neighbors=smote_cfg.get("k_neighbors", 5), 
        n_jobs=-1
    )

    smote = SMOTE(
        sampling_strategy=smote_cfg.get("sampling_strategy", "auto"),
        k_neighbors=nn,
        random_state=smote_cfg.get("random_state", 42)
    )

    X_res, y_res = smote.fit_resample(X_train, y_train)

    return X_res, y_res