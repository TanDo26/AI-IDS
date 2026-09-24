"""
Confusion matrix visualisation utilities.
"""

import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import confusion_matrix, precision_recall_curve, auc
from pathlib import Path


def plot_confusion_matrix(y_true, y_pred, experiment_name, split_name, output_dir, label_type="binary", class_names=None):
    
    if label_type == "binary":
        labels_list = [0, 1]
        display_names = ["Benign (0)", "Attack (1)"]
    else:
        labels_list = sorted(set(y_true.unique()) | set(y_pred.flatten() if hasattr(y_pred, 'flatten') else y_pred))
        display_names = [class_names.get(str(l), str(l)) for l in labels_list] if class_names else [str(l) for l in labels_list]

    cm = confusion_matrix(y_true, y_pred, labels=labels_list)
    cm_pct = np.zeros_like(cm, dtype=float)
    row_sums = cm.sum(axis=1)
    
    for i in range(len(labels_list)):
        if row_sums[i] > 0:
            cm_pct[i] = cm[i].astype(float) / row_sums[i] * 100

    labels = np.array([
        [f"{cm[i][j]:,}\n({cm_pct[i][j]:.1f}%)" if cm[i][j] > 0 else "0"
         for j in range(len(labels_list))] for i in range(len(labels_list))
    ])

    figsize = (8, 6) if label_type == "binary" else (max(10, len(labels_list) * 0.8), max(8, len(labels_list) * 0.8))
    fig, ax = plt.subplots(figsize=figsize)
    
    sns.heatmap(cm, annot=labels, fmt="", cmap="Blues", ax=ax,
                xticklabels=display_names,
                yticklabels=display_names)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    ax.set_title(f"Confusion Matrix — {experiment_name} ({split_name})")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / f"{experiment_name}_{split_name}.png",
                dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_pr_curve(y_true, y_prob, experiment_name, split_name, output_dir, label_type="binary"):
    
    if y_prob is None or label_type != "binary":
        return

    precision, recall, _ = precision_recall_curve(y_true, y_prob)
    pr_auc_val = auc(recall, precision)

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.plot(recall, precision, lw=2,
            label=f"PR-AUC = {pr_auc_val:.4f}")
    ax.set_xlabel("Recall")
    ax.set_ylabel("Precision")
    ax.set_title(f"Precision-Recall Curve — {experiment_name} ({split_name})")
    ax.legend(loc="lower left")
    ax.set_xlim([0, 1])
    ax.set_ylim([0, 1.05])
    ax.grid(True, alpha=0.3)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / f"{experiment_name}_{split_name}_pr_curve.png",
                dpi=150, bbox_inches="tight")
    plt.close(fig)