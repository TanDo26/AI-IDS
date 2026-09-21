"""
Class weighting utilities for imbalanced multiclass classification.
"""

import numpy as np
import pandas as pd
from sklearn.utils.class_weight import compute_class_weight

def compute_class_weights(y_train):

    y_train = np.asarray(y_train)

    classes = np.unique(y_train)

    weights = compute_class_weight(
        class_weight="balanced",
        classes=classes,
        y=y_train
    )

    class_weight = dict(zip(classes, weights))

    return class_weight

def get_sample_weights(y_train, class_weight):
    y_train = np.asarray(y_train)

    sample_weights = np.array([
        class_weight[label]
        for label in y_train
    ])

    return sample_weights