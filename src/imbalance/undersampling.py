"""
Random undersampling utilities for imbalanced classification.
"""

import numpy as np
from imblearn.under_sampling import RandomUnderSampler


def apply_undersampling(X_train, y_train, config, label_type="binary"):

    us_cfg = config["imbalance"]["undersampling"]
    sampling_strategy = us_cfg.get("sampling_strategy", "auto")

    if label_type == "multiclass":
        # "auto" would cut every class to the smallest one (Heartbleed has 8 training rows),
        # so cap the large classes instead and leave the small ones untouched.
        cap = us_cfg.get("multiclass_max_per_class", 100000)
        classes, counts = np.unique(y_train, return_counts=True)
        sampling_strategy = {c: min(int(n), cap) for c, n in zip(classes, counts)}

    sampler = RandomUnderSampler(
        sampling_strategy=sampling_strategy,
        random_state=us_cfg.get("random_state", 42)
    )

    X_res, y_res = sampler.fit_resample(X_train, y_train)
    print(f"  Undersampling ({label_type}): {len(y_train):,} -> {len(y_res):,} rows")

    return X_res, y_res
