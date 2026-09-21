"""
Random undersampling utilities for imbalanced classification.
"""

import numpy as np
import pandas as pd
from collections import Counter
from imblearn.under_sampling import RandomUnderSampler

def apply_undersampling(X_train, y_train, cap_threshold=5000, random_state=42):

    y_train = np.asarray(y_train)

    original_distribution = Counter(y_train)

    sampling_strategy = {
        class_name: cap_threshold
        for class_name, count in original_distribution.items()
        if count > cap_threshold
    }

    if not sampling_strategy:
        return X_train, y_train
    
    undersampler = RandomUnderSampler(sampling_strategy=sampling_strategy, random_state=random_state)

    X_resampled, y_resampled = undersampler.fit_resample(X_train, y_train)

    return X_resampled, y_resampled