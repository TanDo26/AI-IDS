"""
Random undersampling utilities for imbalanced classification.
"""

from imblearn.under_sampling import RandomUnderSampler


def apply_undersampling(X_train, y_train, config):


    us_cfg = config["imbalance"]["undersampling"]

    sampler = RandomUnderSampler(
        sampling_strategy=us_cfg.get("sampling_strategy", "auto"),
        random_state=us_cfg.get("random_state", 42)
    )

    X_res, y_res = sampler.fit_resample(X_train, y_train)

    return X_res, y_res