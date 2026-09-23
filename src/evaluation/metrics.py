"""
Classification metrics for the GeNIS IDS pipeline.
"""

from sklearn.metrics import (
    accuracy_score, f1_score, recall_score, precision_score,
    confusion_matrix, precision_recall_curve, auc
)


def calculate_metrics(y_true, y_pred, y_prob=None):

    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()

    metrics = {
        "f1_attack": f1_score(y_true, y_pred, pos_label=1, zero_division=0),
        "recall_attack": recall_score(y_true, y_pred, pos_label=1, zero_division=0),
        "precision_attack": precision_score(y_true, y_pred, pos_label=1, zero_division=0),
        "macro_f1": f1_score(y_true, y_pred, average="macro", zero_division=0),
        "fpr": float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0,
        "fnr": float(fn / (fn + tp)) if (fn + tp) > 0 else 0.0,

        "accuracy": accuracy_score(y_true, y_pred),

        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn),
    }

    if y_prob is not None:
        prec_curve, rec_curve, _ = precision_recall_curve(y_true, y_prob)
        metrics["pr_auc"] = float(auc(rec_curve, prec_curve))
    else:
        metrics["pr_auc"] = None

    return metrics