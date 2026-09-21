"""
Classification metrics for the GeNIS IDS pipeline.
"""

from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    classification_report
)

def calculate_metrics(y_true, y_pred):
    metrics = {
        "accuracy": accuracy_score(y_true, y_pred),
        "macro_precision": precision_score(y_true, y_pred, average="macro", zero_division=0),
        "macro_recall": recall_score(y_true, y_pred, average="macro", zero_division=0),
        "macro_f1": f1_score(y_true, y_pred, average="macro", zero_division=0),
        "weighted_f1": f1_score(y_true, y_pred, average="weighted", zero_division=0),
    }

    return metrics

def get_classification_report(y_true, y_pred, class_names):
    report_string = classification_report(
        y_true,
        y_pred,
        labels=class_names,
        target_names=class_names,
        zero_division=0
    )

    report_dict = classification_report(
        y_true,
        y_pred,
        labels=class_names,
        target_names=class_names,
        zero_division=0,
        output_dict=True
    )

    return report_string, report_dict
