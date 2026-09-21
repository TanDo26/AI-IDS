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

    print("\n[Undersampling] Before:")
    for cls, count in sorted(original_distribution.items()):
        print(f"  {cls}: {count}")

    sampling_strategy = {
        class_name: cap_threshold
        for class_name, count in original_distribution.items()
        if count > cap_threshold
    }

    if not sampling_strategy:
        return X_train, y_train
    
    undersampler = RandomUnderSampler(sampling_strategy=sampling_strategy, random_state=random_state)

    X_resampled, y_resampled = undersampler.fit_resample(X_train, y_train)

    resampled_distribution = Counter(y_resampled)
    print("\n[Undersampling] After:")
    for cls, count in sorted(resampled_distribution.items()):
        print(f"  {cls}: {count}")
    print(f"\n[Undersampling] Reduced: {len(X_train)} → {len(X_resampled)} samples")

    return X_resampled, y_resampled