# AI-IDS: Intrusion Detection System

A modular, reproducible **intrusion detection** pipeline built on the **CIC-IDS2017** dataset, combining traditional machine learning with deep learning. Supports both **binary** (Benign vs Attack) and **multiclass** (per-attack-type) classification.

## Overview

This project builds a complete ML pipeline — from raw data to evaluation reports — for network traffic classification. It compares **5 models × 3 imbalance strategies × 2 splitting strategies × 2 label types = 33 experiments** to determine the most effective configuration.

### Models

| Model | Type | Framework |
|-------|------|-----------|
| Logistic Regression | Traditional ML | Scikit-learn |
| Random Forest | Traditional ML | Scikit-learn |
| Random Forest (Regularized) | Traditional ML | Scikit-learn |
| MLP (Multi-Layer Perceptron) | Deep Learning | PyTorch |
| LSTM | Deep Learning | PyTorch |

### Key Principles

- **No data leakage** — scaler, imputer, feature selector, SMOTE/undersampler all fit on train only
- **Reproducible** — `random_state=42` everywhere, all artifacts saved to disk
- **Dataset-agnostic** — dataset-specific logic lives entirely in `config.yaml`
- **GPU-accelerated** — PyTorch models (MLP, LSTM) auto-detect and use NVIDIA GPU when available

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

**Label mappings:**
- **Binary:** `Benign` → 0, everything else → 1, `Attempted-*` rows dropped
- **Multiclass:** Each attack type encoded as a unique integer label

After cleaning: **~1,778,392 flows** with **82 numeric features**.

## Experiment Matrix

### Binary Classification (EXP-01 → EXP-18)

| EXP | Model | Strategy | Split |
|:---:|-------|----------|-------|
| 01–03 | Logistic Regression | SMOTE / Undersampling / Class Weight | Random |
| 04–06 | Random Forest | SMOTE / Undersampling / Class Weight | Random |
| 07–09 | Random Forest (Regularized) | SMOTE / Undersampling / Class Weight | Random |
| 10–12 | Logistic Regression | SMOTE / Undersampling / Class Weight | Temporal |
| 13–15 | Random Forest | SMOTE / Undersampling / Class Weight | Temporal |
| 16–18 | Random Forest (Regularized) | SMOTE / Undersampling / Class Weight | Temporal |

### Multiclass Classification (EXP-19 → EXP-30)

| EXP | Model | Strategy | Split |
|:---:|-------|----------|-------|
| 19–21 | MLP | SMOTE / Undersampling / Class Weight | Random |
| 22–24 | Random Forest | SMOTE / Undersampling / Class Weight | Random |
| 25–27 | Random Forest (Regularized) | SMOTE / Undersampling / Class Weight | Random |
| 28–30 | Logistic Regression | SMOTE / Undersampling / Class Weight | Random |

### Deep Learning — Binary (EXP-31 → EXP-33)

| EXP | Model | Strategy | Split |
|:---:|-------|----------|-------|
| 31–33 | LSTM | SMOTE / Undersampling / Class Weight | Temporal |

### Splitting Strategies

| Split | Method | Details |
|-------|--------|---------|
| **Random** | Stratified 70/15/15 | Stratified by original attack type |
| **Temporal** | Mon–Wed / Thu–Fri | Validation carved from train (17.65%) |

### Imbalance Handling Strategies

| Strategy | Method | Description |
|----------|--------|-------------|
| **SMOTE** | Oversampling | Synthetic Minority Over-sampling (k=5) |
| **Undersampling** | RandomUnderSampler | Reduce majority class |
| **Class Weight** | Balanced weighting | Pass `class_weight='balanced'` to model |

## Model Architectures

### MLP (PyTorch)
- 3 hidden layers: 256 → 128 → 64 neurons
- BatchNorm + ReLU + Dropout (0.3) after each layer
- Adam optimizer with weight decay (L2 regularization)
- Learning rate scheduler (ReduceLROnPlateau)
- Early stopping (patience=5)

### LSTM (PyTorch)
- 2-layer LSTM (hidden_size=128)
- Input reshaped to (batch, 1, n_features) — single-timestep sequence
- FC classification head with BatchNorm + Dropout
- Same optimizer, scheduler, and early stopping as MLP

## Evaluation Metrics

### Binary Classification

| Metric | Description |
|--------|-------------|
| `f1_attack` | F1-score for the Attack class |
| `recall_attack` | Recall for Attack (sensitivity) |
| `precision_attack` | Precision for Attack |
| `macro_f1` | Macro-averaged F1 across both classes |
| `fpr` | False Positive Rate |
| `fnr` | False Negative Rate |
| `pr_auc` | Area under Precision-Recall curve |
| `accuracy` | Overall accuracy |

### Multiclass Classification

| Metric | Description |
|--------|-------------|
| `accuracy` | Overall accuracy |
| `macro_f1` | Macro-averaged F1 across all classes |
| `weighted_f1` | Weighted F1 (by class support) |
| `macro_recall` | Macro-averaged Recall |
| `macro_precision` | Macro-averaged Precision |
| `macro_pr_auc` | Macro-averaged PR-AUC |

Outputs include confusion matrix heatmaps, PR curves, and a CSV summary table.

## Project Structure

```
AI-IDS/
├── configs/
│   └── config.yaml                  # Central experiment configuration
├── dataset/
│   └── CIC-IDS2017/
│       ├── *.parquet                # Raw data files (5 files)
│       ├── label_mapping.json       # Multiclass label encoding map
│       └── splits/
│           ├── random/              # Random split (X/y train/val/test)
│           └── temporal/            # Temporal split
├── src/
│   ├── data/
│   │   ├── load_data.py             # Load + concat parquet files
│   │   ├── clean_data.py            # NaN/Inf, dedup, binary + multiclass labels
│   │   └── split_data.py            # Random stratified + temporal split
│   ├── preprocessing/
│   │   ├── feature_selection.py     # Zero-variance, high-correlation removal
│   │   └── build_preprocessor.py    # ColumnTransformer (imputer + scaler)
│   ├── imbalance/
│   │   ├── smote.py                 # SMOTE wrapper
│   │   └── undersampling.py         # RandomUnderSampler wrapper
│   ├── models/
│   │   ├── registry.py              # Model factory & dispatcher
│   │   ├── logistic_regression.py   # LR builder (Scikit-learn)
│   │   ├── random_forest.py         # RF builder (Scikit-learn)
│   │   ├── mlp.py                   # MLP builder (PyTorch)
│   │   ├── lstm.py                  # LSTM builder (PyTorch)
│   │   └── torch_wrapper.py         # Sklearn-compatible wrapper for PyTorch
│   ├── training/
│   │   └── train.py                 # Train orchestrator (with progress bar)
│   └── evaluation/
│       ├── metrics.py               # Binary + multiclass metrics
│       ├── evaluate.py              # Evaluation orchestration
│       └── plots.py                 # Confusion matrix + PR curve plots
├── scripts/
│   ├── prepare_data.py              # CLI: load → clean → split
│   ├── train_all.py                 # CLI: train experiments (with --exp filter)
│   ├── evaluate_all.py              # CLI: evaluate + report (with --exp filter)
│   └── run_all.py                   # CLI: full pipeline (with --exp filter)
├── models/                          # Saved trained models (.pkl / .pt)
├── results/
│   ├── metrics/                     # CSV summary tables
│   ├── confusion_matrices/          # Heatmap PNGs
│   └── pr_curves/                   # PR-AUC curve PNGs
├── Dockerfile                       # Python 3.11 + PyTorch CUDA 12.4
├── docker-compose.yml               # Services with NVIDIA GPU support
└── requirements.txt
```

## How to Run

### Prerequisites

- **Python 3.11+** (or Docker)
- **PyTorch with CUDA** (for GPU-accelerated MLP/LSTM training)
- CIC-IDS2017 parquet files placed in `dataset/CIC-IDS2017/`

### Option 1: Run with Docker (Recommended)

Docker ensures reproducibility and automatically handles GPU setup.

**Run full pipeline:**

```bash
docker compose build
docker compose run --rm run-all
```

**Run specific experiments:**

```bash
docker compose run --rm run-all -e 19-21         # MLP experiments only
docker compose run --rm run-all -e 31-33          # LSTM experiments only
docker compose run --rm run-all -e . --skip-prepare  # All, skip data prep
```

**Run each step individually:**

```bash
docker compose run --rm prepare                    # Step 1: load → clean → split
docker compose run --rm train                      # Step 2: train all experiments
docker compose run --rm evaluate                   # Step 3: evaluate + report
```

### Option 2: Run Locally with Python

```bash
# 1. Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

# 2. Install dependencies
pip install -r requirements.txt

# For GPU support (NVIDIA), install PyTorch with CUDA:
pip install torch --index-url https://download.pytorch.org/whl/cu124

# 3. Run full pipeline
python scripts/run_all.py
```

### Experiment Filter (`--exp` / `-e`)

All scripts support experiment filtering:

```bash
python scripts/run_all.py -e .           # Run ALL experiments (default)
python scripts/run_all.py -e 15          # Run only EXP-15
python scripts/run_all.py -e 10-13       # Run EXP-10 through EXP-13
python scripts/run_all.py -e 5,8,12      # Run EXP-05, EXP-08, EXP-12
python scripts/run_all.py -e 19-33 --skip-prepare  # New experiments, skip data prep
```

Works the same with `train_all.py` and `evaluate_all.py`:

```bash
python scripts/train_all.py -e 31-33     # Train only LSTM experiments
python scripts/evaluate_all.py -e 31-33  # Evaluate only LSTM experiments
```

### Pipeline Steps

| Step | Script | What It Does |
|:---:|--------|--------------|
| 1 | `prepare_data.py` | Loads 5 parquet files, cleans data (drop NaN/Inf/duplicates, binary + multiclass labelling), performs random + temporal splits, saves to `dataset/CIC-IDS2017/splits/` |
| 2 | `train_all.py` | For each experiment: feature selection → preprocessing → imbalance handling → model training → save model |
| 3 | `evaluate_all.py` | Loads trained models, evaluates on test sets, generates confusion matrices, PR curves, and a summary CSV |

### Output

After running the pipeline, results are saved to:

- `results/metrics/summary.csv` — comparison table of all experiments
- `results/confusion_matrices/` — confusion matrix heatmaps (PNG)
- `results/pr_curves/` — precision-recall curves (PNG)
- `models/` — saved model files (`.pkl` for Sklearn, `.pt` for PyTorch)

## Configuration

All experiment parameters are controlled via [`configs/config.yaml`](configs/config.yaml):

- Dataset paths and feature definitions
- Splitting ratios and strategies (random, temporal)
- Model hyperparameters:
  - **LR:** `max_iter`, `C`, `solver`
  - **RF:** `n_estimators`, `max_depth`, `min_samples_leaf`
  - **RF (Regularized):** `max_depth=15`, `min_samples_split=10`, `max_features=sqrt`
  - **MLP:** `hidden_sizes`, `dropout`, `epochs`, `batch_size`, `lr`, `patience`
  - **LSTM:** `hidden_size`, `num_layers`, `dropout`, `bidirectional`, `epochs`, `batch_size`, `lr`, `patience`
- Imbalance strategies (SMOTE, undersampling, class_weight)
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
torch>=2.0
```
