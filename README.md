# AI-IDS: Binary Intrusion Detection System

A modular, reproducible **binary intrusion detection** pipeline built on the **CIC-IDS2017** dataset using traditional machine learning.

## Overview

This project builds a complete ML pipeline — from raw data to evaluation reports — for **binary classification** (Benign vs Attack) of network traffic flows. It compares **2 models × 2 imbalance strategies × 2 splitting strategies = 8 evaluations** to determine the most effective configuration.

### Key Principles

- **No data leakage** — scaler, imputer, feature selector, SMOTE/undersampler all fit on train only
- **Reproducible** — `random_state=42` everywhere, all artifacts saved to disk
- **Dataset-agnostic** — dataset-specific logic lives entirely in `config.yaml`

## Dataset

**CIC-IDS2017** — 5 parquet files, one per day:

| Day File | Rows | Attack Types |
|---|---:|---|
| `Benign-Monday.parquet` | 350,718 | _(100% Benign)_ |
| `Bruteforce-Tuesday.parquet` | 307,071 | FTP-Patator, SSH-Patator |
| `DoS-Wednesday.parquet` | 477,871 | DoS Hulk, GoldenEye, Slowloris, Slowhttptest, Heartbleed |
| `Infiltration-Webattacks-Thursday.parquet` | 281,439 | Infiltration, Portscan, Web Attack (BF/XSS/SQLi) |
| `Portscan-DDos-Botnet-Friday.parquet` | 370,259 | DDoS, Portscan, Botnet |
| **Total** | **~1,787,358** | **15 attack types** |

**Binary label mapping:** `Benign` → 0, everything else → 1, `Attempted-*` rows dropped.

After cleaning: **~1,778,392 flows** (≈84% Benign / 16% Attack) with **82 numeric features**.

## Experiment Matrix

| Experiment | Model | Imbalance Strategy |
|:---:|---|---|
| EXP-01 | Logistic Regression | SMOTE |
| EXP-02 | Random Forest | SMOTE |
| EXP-03 | Logistic Regression | Undersampling |
| EXP-04 | Random Forest | Undersampling |

Each experiment runs on **both** splitting strategies:

| Split | Method | Details |
|---|---|---|
| **Random** | Stratified 70/15/15 | Stratified by original attack type |
| **Temporal** | Mon–Wed / Thu–Fri | Validation carved from train |

→ **8 total evaluations**

## Evaluation Metrics

| Metric | Description |
|---|---|
| `f1_attack` | F1-score for the Attack class |
| `recall_attack` | Recall for Attack (sensitivity) |
| `precision_attack` | Precision for Attack |
| `macro_f1` | Macro-averaged F1 across both classes |
| `fpr` | False Positive Rate |
| `fnr` | False Negative Rate |
| `pr_auc` | Area under Precision-Recall curve |
| `accuracy` | Overall accuracy |

Outputs include confusion matrix heatmaps, PR curves, and a CSV summary table.

## Project Structure

```
AI-IDS/
├── configs/
│   └── config.yaml                  # Central experiment configuration
├── dataset/
│   └── CIC-IDS2017/
│       ├── *.parquet                # Raw data files (5 files)
│       └── splits/
│           ├── random/              # Random split (X/y train/val/test)
│           └── temporal/            # Temporal split
├── src/
│   ├── data/
│   │   ├── load_data.py             # Load + concat parquet files
│   │   ├── clean_data.py            # NaN/Inf, dedup, binary labels
│   │   └── split_data.py            # Random stratified + temporal split
│   ├── preprocessing/
│   │   ├── feature_selection.py     # Zero-variance, high-correlation removal
│   │   └── build_preprocessor.py    # ColumnTransformer (imputer + scaler)
│   ├── imbalance/
│   │   ├── smote.py                 # SMOTE wrapper
│   │   └── undersampling.py         # RandomUnderSampler wrapper
│   ├── models/
│   │   ├── registry.py              # Model factory
│   │   ├── logistic_regression.py   # LR builder
│   │   └── random_forest.py         # RF builder
│   ├── training/
│   │   └── train.py                 # Train orchestrator (with progress bar)
│   └── evaluation/
│       ├── metrics.py               # F1, Recall, FPR, FNR, PR-AUC
│       ├── evaluate.py              # Evaluation orchestration
│       └── plots.py                 # Confusion matrix + PR curve plots
├── scipts/
│   ├── prepare_data.py              # CLI: load → clean → split
│   ├── train_all.py                 # CLI: train 4 experiments × 2 splits
│   └── evaluate_all.py              # CLI: evaluate + report
├── models/                          # Saved trained models (.pkl)
├── results/
│   ├── metrics/                     # CSV summary tables
│   ├── confusion_matrices/          # Heatmap PNGs
│   └── pr_curves/                   # PR-AUC curve PNGs
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## How to Run

### Prerequisites

- **Python 3.12+** (or Docker)
- CIC-IDS2017 parquet files placed in `dataset/CIC-IDS2017/`

### Option 1: Run with Docker (Recommended)

```bash
# Build the Docker image
docker compose build

# Step 1 — Prepare data (load, clean, split)
docker compose run --rm prepare

# Step 2 — Train all experiments
docker compose run --rm train

# Step 3 — Evaluate and generate reports
docker compose run --rm evaluate
```

### Option 2: Run Locally with Python

```bash
# 1. Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

# 2. Install dependencies
pip install -r requirements.txt

# 3. Prepare data (load → clean → split)
python scipts/prepare_data.py

# 4. Train all experiments (4 experiments × 2 splits)
python scipts/train_all.py

# 5. Evaluate and generate reports
python scipts/evaluate_all.py
```

### Pipeline Steps Explained

| Step | Script | What It Does |
|:---:|---|---|
| 1 | `prepare_data.py` | Loads 5 parquet files, cleans data (drop NaN/Inf/duplicates, binary labelling), performs random + temporal splits, saves to `dataset/CIC-IDS2017/splits/` |
| 2 | `train_all.py` | For each experiment × split: feature selection → preprocessing → imbalance handling → model training → save model to `models/` |
| 3 | `evaluate_all.py` | Loads trained models, evaluates on test sets, generates confusion matrices, PR curves, and a summary CSV in `results/` |

### Output

After running all 3 steps, results are saved to:

- `results/metrics/summary.csv` — comparison table of all 8 evaluations
- `results/confusion_matrices/` — confusion matrix heatmaps (PNG)
- `results/pr_curves/` — precision-recall curves (PNG)
- `models/` — saved model files (`.pkl`)

## Configuration

All experiment parameters are controlled via [`configs/config.yaml`](configs/config.yaml):

- Dataset paths and feature definitions
- Splitting ratios and strategies
- Model hyperparameters (LR: `max_iter`, `C`, `solver` / RF: `n_estimators`, `max_depth`)
- SMOTE and undersampling parameters
- Evaluation metrics and output paths

## Requirements

```
pandas>=2.0
numpy>=1.24
matplotlib>=3.7
seaborn>=0.13
scikit-learn>=1.3
imbalanced-learn>=0.11
pyyaml>=6.0
joblib>=1.3
tqdm>=4.65
pyarrow>=14.0
```
