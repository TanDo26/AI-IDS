"""
Confusion matrix visualisation utilities.
"""

import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import confusion_matrix, precision_recall_curve, auc
from pathlib import Path


def plot_confusion_matrix(y_true, y_pred, experiment_name, split_name, output_dir):
    
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    cm_pct = cm.astype(float) / cm.sum() * 100

    labels = np.array([
        [f"{cm[i][j]:,}\n({cm_pct[i][j]:.1f}%)"
         for j in range(2)] for i in range(2)
    ])

    fig, ax = plt.subplots(figsize=(8, 6))
    sns.heatmap(cm, annot=labels, fmt="", cmap="Blues", ax=ax,
                xticklabels=["Benign (0)", "Attack (1)"],
                yticklabels=["Benign (0)", "Attack (1)"])
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    ax.set_title(f"Confusion Matrix — {experiment_name} ({split_name})")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / f"{experiment_name}_{split_name}.png",
                dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_pr_curve(y_true, y_prob, experiment_name, split_name, output_dir):
    
    if y_prob is None:
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