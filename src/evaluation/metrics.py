"""
Classification metrics for the GeNIS IDS pipeline.
Supports both binary and multiclass evaluation.
"""

from sklearn.metrics import (
    accuracy_score, f1_score, recall_score, precision_score,
    confusion_matrix, precision_recall_curve, auc
)


def calculate_metrics(y_true, y_pred, y_prob=None, label_type="binary"):
    if label_type == "binary":
        return _binary_metrics(y_true, y_pred, y_prob)
    else:
        return _multiclass_metrics(y_true, y_pred, y_prob)


def _binary_metrics(y_true, y_pred, y_prob=None):

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


def _multiclass_metrics(y_true, y_pred, y_prob=None):

    labels = sorted(set(y_true.unique()) | set(y_pred.flatten() if hasattr(y_pred, 'flatten') else y_pred))

    metrics = {
        "accuracy": accuracy_score(y_true, y_pred),
        "macro_f1": f1_score(y_true, y_pred, average="macro", zero_division=0),
        "weighted_f1": f1_score(y_true, y_pred, average="weighted", zero_division=0),
        "macro_recall": recall_score(y_true, y_pred, average="macro", zero_division=0),
        "weighted_recall": recall_score(y_true, y_pred, average="weighted", zero_division=0),
        "macro_precision": precision_score(y_true, y_pred, average="macro", zero_division=0),
        "weighted_precision": precision_score(y_true, y_pred, average="weighted", zero_division=0),
        "num_classes": len(labels),
    }

    if y_prob is not None and len(y_prob.shape) == 2:
        per_class_pr_auc = []
        for i, cls in enumerate(sorted(labels)):
            if i < y_prob.shape[1]:
                y_binary = (y_true == cls).astype(int)
                if y_binary.sum() > 0:
                    prec_curve, rec_curve, _ = precision_recall_curve(y_binary, y_prob[:, i])
                    per_class_pr_auc.append(float(auc(rec_curve, prec_curve)))
        metrics["macro_pr_auc"] = float(sum(per_class_pr_auc) / len(per_class_pr_auc)) if per_class_pr_auc else None
    else:
        metrics["macro_pr_auc"] = None

    return metrics