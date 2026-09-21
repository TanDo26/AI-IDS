"""
Confusion matrix visualisation utilities.
"""

from scipy.spatial.transform import rotation
from paramiko import file
from pathlib import Path

import matplotlib.pyplot as plt
import seaborn as sns

from sklearn.metrics import confusion_matrix

CLASS_NAMES = [
    "admin",
    "background",
    "user",
    "bruteforce-ftp",
    "bruteforce-smb",
    "bruteforce-ssh",
    "dos-hulk",
    "dos-icmp",
    "dos-pushack",
    "dos-slowloris",
    "dos-udp",
    "recon-dns",
    "recon-nmap"
]

def plot_confusion_matrix(y_true, y_pred, class_names, experiment_name, save_dir):
    cm = confusion_matrix(y_true, y_pred, labels=class_names)

    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    filepath = (save_dir / f"{experiment_name}_cm.png")

    plt.figure(figsize=(14,12))

    sns.heatmap(cm, annot=True, fmt="d", xticklabels=class_names, yticklabels=class_names, cmap="Blues")

    plt.xlabel("Predicted Label")
    plt.ylabel("True Label")
    plt.title(f"Confusion Matrix - {experiment_name}")
    plt.xticks(rotation=45, ha="right")
    plt.yticks(rotation=0)
    plt.tight_layout()
    plt.savefig(filepath, dpi=300, bbox_inches="tight")

    plt.close()

    print(f"Confusion matrix saved to: {filepath}")

    return filepath

def plot_normalized_confusion_matrix(y_true, y_pred, class_names, experiment_name, save_dir):
    cm = confusion_matrix(y_true, y_pred, labels=class_names, normalize="true")

    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    filepath = (save_dir / f"{experiment_name}_cm_normalized.png")

    plt.figure(figsize=(14, 12))

    sns.heatmap(cm, annot=True, fmt=".2f", xticklabels=class_names, yticklabels=class_names, cmap="Blues", vmin=0, vmax=1)

    plt.xlabel("Predicted Label")
    plt.ylabel("True Label")
    plt.title(f"Normalized Confusion Matrix - {experiment_name}")
    plt.xticks(rotation=45, ha="right")
    plt.yticks(rotation=0)
    plt.tight_layout()
    plt.savefig(filepath, dpi=300, bbox_inches="tight")

    plt.close()

    print(f"Normalized confusion matrix saved to: {filepath}")

    return filepath

