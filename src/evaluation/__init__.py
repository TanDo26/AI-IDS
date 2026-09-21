"""
Evaluation utilities for the GeNIS IDS pipeline.
"""

from .metrics import (
    calculate_metrics,
    get_classification_report
)

from .evaluate import (
    evaluate_model,
    save_predictions
)

from .plots import (
    plot_confusion_matrix,
    plot_normalized_confusion_matrix
)

__all__ = [
    "calculate_metrics",
    "get_classification_report",
    "evaluate_model",
    "save_predictions",
    "plot_confusion_matrix",
    "plot_normalized_confusion_matrix"
]