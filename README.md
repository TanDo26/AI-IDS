# AI-IDS: Intrusion Detection System

A modular, reproducible **intrusion detection** pipeline built on the **CIC-IDS2017** dataset, combining traditional machine learning with deep learning. Supports both **binary** (Benign vs Attack) and **multiclass** (per-attack-type) classification.

## Overview

This project builds a complete ML pipeline — from raw data to evaluation reports — for network traffic classification. It compares **7 models** across **4 imbalance settings** (none, SMOTE, undersampling, class weights), **2 splitting strategies**, **2 label types** and **3 feature-selection profiles** — **71 experiments** defined in `configs/config.yaml` — to determine the most effective configuration.

### Models

| Model | Type | Framework |
|-------|------|-----------|
| Logistic Regression | Traditional ML | Scikit-learn |
| Gaussian Naive Bayes | Traditional ML | Scikit-learn |
| Random Forest | Traditional ML | Scikit-learn |
| Random Forest (Regularized) | Traditional ML | Scikit-learn |
| XGBoost | Gradient boosting | XGBoost (GPU when available) |
| MLP (Multi-Layer Perceptron) | Deep Learning | PyTorch |
| LSTM | Deep Learning | PyTorch |

### Key Principles

- **No data leakage** — scaler, imputer, feature selector, SMOTE/undersampler all fit on train only
- **Reproducible** — `random_state=42` everywhere, all artifacts saved to disk
- **Dataset-agnostic** — dataset-specific logic lives entirely in `config.yaml`
- **GPU-accelerated** — PyTorch models (MLP, LSTM) and XGBoost auto-detect and use an NVIDIA GPU when available, and fall back to CPU

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

All 71 experiments are entries in `configs/config.yaml` (`experiments:`). RF = Random Forest, RF-reg = Random Forest (Regularized), LR = Logistic Regression, NB = Gaussian Naive Bayes.

### Baselines, no resampling (EXP-01 → EXP-12)

| EXP | Model | Split | Label |
|:---:|-------|-------|-------|
| 01 / 02 / 03 / 04 | LR / RF / RF-reg / MLP | Random | Binary |
| 05 / 06 / 07 / 08 | LR / RF / RF-reg / LSTM | Temporal | Binary |
| 09 / 10 / 11 / 12 | LR / RF / RF-reg / MLP | Random | Multiclass |

### Imbalance strategies (EXP-13 → EXP-41)

| EXP | Model | Strategies | Split | Label |
|:---:|-------|------------|-------|-------|
| 13–15 | LR | SMOTE / Undersampling / Class Weight | Random | Binary |
| 16–18 | RF | SMOTE / Undersampling / Class Weight | Random | Binary |
| 19–21 | RF-reg | SMOTE / Undersampling / Class Weight | Random | Binary |
| 22–24 | LR | SMOTE / Undersampling / Class Weight | Temporal | Binary |
| 25–27 | RF | SMOTE / Undersampling / Class Weight | Temporal | Binary |
| 28–30 | RF-reg | SMOTE / Undersampling / Class Weight | Temporal | Binary |
| 31–32 | MLP | Undersampling / Class Weight | Random | Multiclass |
| 33–34 | RF | Undersampling / Class Weight | Random | Multiclass |
| 35–36 | RF-reg | Undersampling / Class Weight | Random | Multiclass |
| 37–38 | LR | Undersampling / Class Weight | Random | Multiclass |
| 39–41 | LSTM | SMOTE / Undersampling / Class Weight | Temporal | Binary |

### Naive Bayes and XGBoost (EXP-42 → EXP-59)

| EXP | Model | Strategies | Split | Label |
|:---:|-------|------------|-------|-------|
| 42–44 | NB | None / Undersampling / Class Weight | Random | Binary |
| 45–47 | NB | None / Undersampling / Class Weight | Temporal | Binary |
| 48–50 | NB | None / Undersampling / Class Weight | Random | Multiclass |
| 51–53 | XGBoost | None / Undersampling / Class Weight | Random | Binary |
| 54–56 | XGBoost | None / Undersampling / Class Weight | Temporal | Binary |
| 57–59 | XGBoost | None / Undersampling / Class Weight | Random | Multiclass |

### Feature selection (EXP-60 → EXP-71), no resampling

Each pair compares Pearson and mutual information against the baseline that uses no supervised selection.

| EXP | Model | Feature selection | Split | Label | Baseline |
|:---:|-------|-------------------|-------|-------|:--------:|
| 60 / 61 | RF | Pearson / MI | Random | Binary | 02 |
| 62 / 63 | RF | Pearson / MI | Random | Multiclass | 10 |
| 64 / 65 | RF | Pearson / MI | Temporal | Binary | 06 |
| 66 / 67 | XGBoost | Pearson / MI | Random | Binary | 51 |
| 68 / 69 | XGBoost | Pearson / MI | Random | Multiclass | 57 |
| 70 / 71 | XGBoost | Pearson / MI | Temporal | Binary | 54 |

### Splitting Strategies

| Split | Method | Details |
|-------|--------|---------|
| **Random** | Stratified 70/15/15 | Stratified by original attack type |
| **Temporal** | Mon–Wed / Thu–Fri | Validation carved from train (17.65%) |

### Imbalance Handling Strategies

| Strategy | Method | Description |
|----------|--------|-------------|
| **SMOTE** | Oversampling | Synthetic Minority Over-sampling (k=5) |
| **Undersampling** | RandomUnderSampler | **Binary:** balance Benign and Attack 1:1. **Multiclass:** cap each class at `multiclass_max_per_class` (100,000); smaller classes keep every row |
| **Class Weight** | Balanced weighting | `class_weight='balanced'`; Naive Bayes and XGBoost (no such parameter) get balanced `sample_weight` in `fit()` |

Multiclass undersampling uses a cap because `sampling_strategy: auto` would cut every class down to the smallest one: Heartbleed has 8 training rows, so the model would train on 128 rows in total.

### Feature Selection

Every experiment first drops zero-variance columns and one of each pair of highly correlated columns (|r| > 0.95), which leaves 52 of 82 features on the random split. An experiment can then rank the remaining features against the label with a **profile** (`feature_selection:` in its entry, default `none`):

| Profile | Method | Keeps |
|---------|--------|-------|
| `none` | Base filters only | 52 features |
| `pearson` | \|Pearson r\| with the label (multiclass: one-vs-rest, max per feature) | Features with \|r\| ≥ 0.05 (19 for random/binary, 38 for random/multiclass) |
| `mi` | Mutual information, scored on a 200k-row stratified sample | Top 30 |

Profiles are defined under `preprocessing.feature_selection_profiles`. Everything is fitted on the training split only, and the fitted selector + preprocessor are saved per (split, label, profile) as `models/preprocessors/{split}_{label}_{fs}_*.pkl`.

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
│   │   ├── feature_selection.py     # Zero-variance + high-correlation removal, Pearson / MI ranking
│   │   ├── artifacts.py             # Per (split, label, profile) artifact names
│   │   └── build_preprocessor.py    # ColumnTransformer (imputer + scaler)
│   ├── imbalance/
│   │   ├── smote.py                 # SMOTE wrapper
│   │   └── undersampling.py         # RandomUnderSampler (multiclass: per-class cap)
│   ├── models/
│   │   ├── registry.py              # Model factory & dispatcher
│   │   ├── logistic_regression.py   # LR builder (Scikit-learn)
│   │   ├── random_forest.py         # RF builder (Scikit-learn)
│   │   ├── naive_bayes.py           # Gaussian NB builder (Scikit-learn)
│   │   ├── xgboost_model.py         # XGBoost builder (GPU when available)
│   │   ├── label_encoded.py         # Wrapper for models that need labels 0..K-1
│   │   ├── anomaly.py               # Isolation Forest for unknown-attack detection
│   │   ├── mlp.py                   # MLP builder (PyTorch)
│   │   ├── lstm.py                  # LSTM builder (PyTorch)
│   │   └── torch_wrapper.py         # Sklearn-compatible wrapper for PyTorch
│   ├── training/
│   │   └── train.py                 # Train orchestrator (with progress bar)
│   ├── evaluation/
│   │   ├── metrics.py               # Binary + multiclass metrics
│   │   ├── evaluate.py              # Evaluation orchestration
│   │   └── plots.py                 # Confusion matrix + PR curve plots
│   ├── inference/                   # Model bundles, open-set decision, explanations, model store
│   └── api/                         # FastAPI web API (main.py), DB models, Celery worker
├── scripts/
│   ├── prepare_data.py              # CLI: load → clean → split
│   ├── train_all.py                 # CLI: train experiments (with --exp filter)
│   ├── evaluate_all.py              # CLI: evaluate + report (with --exp filter)
│   ├── run_all.py                   # CLI: full pipeline (with --exp filter)
│   ├── optimize_hpo.py              # CLI: hyperparameter optimization (Optuna, --auto-update)
│   ├── xai_analysis.py              # CLI: SHAP explainability analysis
│   ├── build_bundle.py              # CLI: package an experiment as a server model bundle
│   ├── manage_models.py             # CLI: list / activate / roll back model bundles
│   ├── evaluate_open_set.py         # CLI: unseen-attack evaluation (temporal, leave-one-family-out)
│   └── create_admin.py              # CLI: first admin account for the web API
├── tests/                           # pytest suite for the web API + inference (tiny synthetic bundle)
├── web/                             # Next.js frontend (served by Caddy next to the API)
├── models/                          # Saved trained models (.pkl / .pt)
├── results/
│   ├── metrics/                     # CSV summary tables
│   ├── confusion_matrices/          # Heatmap PNGs
│   ├── pr_curves/                   # PR-AUC curve PNGs
│   ├── hpo/                         # HPO results (JSON + plots)
│   └── xai/                         # SHAP plots + feature importance CSVs
├── Dockerfile                       # Python 3.14 + PyTorch CUDA 13.0
├── docker-compose.yml               # Services with NVIDIA GPU support
└── requirements.txt
```

## How to Run

### Prerequisites

- **Python 3.11+** (or Docker)
- **PyTorch with CUDA** (for GPU-accelerated MLP/LSTM training)
- CIC-IDS2017 parquet files placed in `dataset/CIC-IDS2017/`
- **Docker Desktop** to run the web application (API, worker, database, frontend): see [Web frontend](#web-frontend-web)
- **Node.js 24 LTS** (npm included) only to develop the frontend with hot reload; running the app needs Docker alone

### Option 1: Run with Docker (Recommended)

Docker ensures reproducibility and automatically handles GPU setup.

**Run full pipeline:**

```bash
docker compose --profile pipeline build
docker compose run --rm run-all
```

The training services need an NVIDIA GPU in Docker. On a machine without one, run locally (Option 2) instead.

**Run specific experiments:**

```bash
docker compose run --rm run-all -e 42-59          # Naive Bayes + XGBoost experiments
docker compose run --rm run-all -e 39-41          # LSTM imbalance experiments
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
python scripts/run_all.py -e 60-71 --skip-prepare  # Feature-selection experiments, skip data prep
```

Works the same with `train_all.py` and `evaluate_all.py`:

```bash
python scripts/train_all.py -e 39-41     # Train only the LSTM imbalance experiments
python scripts/evaluate_all.py -e 39-41  # Evaluate them
```

**Resuming and retraining:** `train_all.py` and `run_all.py` skip experiments whose model file already exists and reuse the saved preprocessing, so rerunning a stopped run continues where it stopped. After changing the data or `config.yaml`, add `--force` to retrain and refit:

```bash
python scripts/run_all.py --force                # retrain everything
python scripts/train_all.py -e 15 --force        # retrain one experiment
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

## Extended Features

### Hyperparameter Optimization (HPO)

Automatic hyperparameter tuning using [Optuna](https://optuna.org/). Supports every model, including Naive Bayes and XGBoost. Each trial builds its model the same way training does, and the score is validation macro-F1.

```bash
# Tune one experiment under its own split, label, feature selection and imbalance strategy,
# on 20% of the training rows, and write the best params back to config.yaml
python scripts/optimize_hpo.py --exp EXP-53 --trials 50 --subsample 0.2 --auto-update
python scripts/train_all.py -e 53 --force        # retrain with the tuned params

# Tune a model directly
python scripts/optimize_hpo.py --model random_forest --trials 20
python scripts/optimize_hpo.py --model mlp --split temporal --trials 30
python scripts/optimize_hpo.py --model logistic_regression --label multiclass --strategy class_weight --trials 50

# Docker
docker compose run --rm hpo --model xgboost --trials 20
```

| Flag | Meaning |
|------|---------|
| `--exp EXP-NN` | Take model, split, label, feature selection and imbalance strategy from that experiment |
| `--model`, `--split`, `--label`, `--fs`, `--strategy` | Set these directly (or override `--exp`) |
| `--trials N` | Number of Optuna trials (default 20) |
| `--subsample F` | Tune on a stratified fraction of the training rows, for faster trials |
| `--auto-update` | Write the best params to `config.yaml`: into that experiment's `params:` block with `--exp`, otherwise into `models.<model>` (shared by every experiment using it) |

`--auto-update` edits only the affected lines of `config.yaml` (comments and formatting are kept), adds a comment with the date, score and trial count, and saves `config.yaml.bak` first. It refuses `--exp` combined with overriding flags, since the params would then be tuned under a different setup than the experiment's. Training picks up an experiment's `params:` automatically; because existing models are skipped, retrain with `--force`.

Results (best params + all trial history) are saved to `results/hpo/` as JSON files.

### Explainable AI (XAI)

Model interpretability analysis using [SHAP](https://shap.readthedocs.io/).

```bash
# Explain best Random Forest model
python scripts/xai_analysis.py --exp EXP-02 --model random_forest

# Explain multiclass model with more samples
python scripts/xai_analysis.py --exp EXP-10 --model random_forest --label multiclass --samples 2000

# Docker
docker compose run --rm xai --exp EXP-02 --model random_forest
```

Outputs saved to `results/xai/`:
- **Summary plot** — beeswarm showing feature impact direction & magnitude
- **Bar plot** — mean |SHAP| ranking of features
- **Waterfall plot** — explains a single prediction (binary only)
- **Feature importance CSV** — ranked table of all features

### Inference API

Real-time prediction API using [FastAPI](https://fastapi.tiangolo.com/). It serves the **active model bundle**, so there is no per-experiment configuration any more:

```bash
python scripts/build_bundle.py --exp EXP-59                 # package a trained multiclass experiment

# Full stack: Postgres, Redis, migrations, API, Celery worker, Caddy proxy on http://localhost:8080
cp .env.example .env                                        # then set IDS_SECRET_KEY and POSTGRES_PASSWORD
docker compose --profile app up --build

# Register the bundles in model_store/ and choose the served one (or use the /admin/models endpoints)
docker compose exec api python scripts/manage_models.py --db rescan
docker compose exec api python scripts/manage_models.py --db activate <bundle_id>

# Or the API alone on the host (needs Postgres/Redis reachable via IDS_DATABASE_URL / IDS_REDIS_URL)
alembic upgrade head
uvicorn src.api.main:app --port 8000
```

**On Windows:**
- **Git Bash path rewriting:** Git Bash rewrites `/app/...` arguments of `docker compose exec` into Windows paths. Run `export MSYS_NO_PATHCONV=1` first, or leave out `--store` (it defaults to `/app/model_store`).
- **Large uploads to `localhost:8080`:** Docker Desktop's port forwarding can stall on very large uploads that the server rejects early, especially when RAM is short. Users reach the stack through the tunnel instead, and Caddy rejects anything announced over 100 MB before it reaches the API.

**Upload processing.** Each upload is queued for the Celery `worker`:
- it predicts the flows in batches of 50,000;
- it writes per-flow results to `data/results/<upload_id>/flows.parquet` and a summary: decision counts, known-attack breakdown, and agreement with an uploaded `Label` column (attack vs benign);
- `GET /uploads/{id}` shows the status (`queued` → `predicting` → `completed` / `failed`), the progress and any error.

The `beat` service deletes raw uploads older than `IDS_RETENTION_DAYS` (30) every night at 03:30 UTC; results and usage records stay.

**Model switching.** The server's active bundle is recorded in its database, in the `model_versions` table.
`manage_models.py` without `--db` only edits `model_store/registry.json`, which is for offline use on the
training machine.
- **Rescan** registers new bundles and re-checks known ones; broken ones are marked `invalid`.
- **Activate** verifies the bundle first, then switches it in one transaction and writes the audit log.
- **Propagation:** every API process switches within seconds through Redis (`ids:model-events`), or at its next database check (`IDS_MODEL_POLL_SECONDS`, 30 s) if Redis is down. Requests already running finish on the old bundle. Celery workers switch at the start of each job.

**Endpoints** (prefix `/api/v1`; Swagger UI at `/api/docs`):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/healthz` | Liveness |
| `GET` | `/readyz` | Readiness: database, Redis, active model |
| `POST` | `/auth/signup`, `/auth/login` | Create an account / log in (sets cookies, returns an access token) |
| `POST` | `/auth/refresh`, `/auth/logout`, `/auth/password` | Session management |
| `GET` | `/auth/me` | Current user |
| `POST` | `/predict` | One flow → `benign` / `known_attack` / `unknown`, attack type, scores (login required) |
| `POST` | `/batch_predict` | Up to 10,000 flows (login required) |
| `POST` | `/uploads` | Upload a CICFlowMeter CSV as multipart field `file` (≤ 100 MB) and queue it for processing. The type is read from the content, and missing features are listed at once. PCAP / PCAPNG only with `IDS_ENABLE_PCAP=true`. |
| `GET` | `/uploads`, `/uploads/{id}` | Your uploads (newest first, `page` / `size` / `status`), or one upload's status and progress |
| `GET` | `/uploads/stats` | Your totals over the uploads you still have: per status, bytes, flows, known attacks, unknowns |
| `DELETE` | `/uploads/{id}` | Delete the file and its results (owner or admin); it still counts in usage totals |
| `GET` | `/uploads/{id}/summary` | Decision counts, known attacks per type, unknowns per reason, label agreement, the model that produced them |
| `GET` | `/uploads/{id}/flows` | Paginated flows (`page`, `size` ≤ 500), filtered by `decision` / `class_name`, sorted by `sort` (e.g. `-anomaly_score`) |
| `GET` | `/uploads/{id}/flows/{row}/explain` | SHAP explanation of one flow, computed with the bundle that produced it |
| `GET` | `/uploads/{id}/export.csv` | Download the results as CSV (`decision`, `class_name`, `features=true` to include the model inputs) |
| `GET` | `/admin/models` | Admin: versions with metrics, the active one, what each process has loaded |
| `POST` | `/admin/models/rescan` | Admin: register / re-check the bundles in `model_store/` |
| `POST` | `/admin/models/{id}/activate`, `/admin/models/rollback` | Admin: switch the served model |
| `GET` / `PATCH` | `/admin/users`, `/admin/users/{id}` | Admin: search users; deactivate/reactivate, promote/demote (audited; not yourself, never the last admin) |
| `GET` | `/admin/usage`, `/admin/usage/{user_id}/daily` | Admin: per-user uploads, bytes, flows, processing time, storage (`from` / `to`); one user's daily series |
| `GET` | `/admin/uploads`, `/admin/audit` | Admin: every user's uploads (`user_id`, `status`, `deleted`); the audit log (`action`, `actor_id`, `target_type`, `target_id`) |
| `GET` | `/admin/server` | Admin: CPU/RAM/disk/GPU, database, Redis, Celery queue and workers, upload counts, model state, plain-language warnings |
| `GET` | `/metrics` | Prometheus metrics, outside `/api` so Caddy never exposes it (scrape `api:8000` inside the Compose network) |

Create the first admin with `python scripts/create_admin.py --email you@example.com --username admin`
(in Docker: `docker compose exec api python scripts/create_admin.py ...`). Scripts call `/predict` with
the `access_token` from `/auth/login` as `Authorization: Bearer <token>`.

Settings are `IDS_*` environment variables (see `.env.example`).

### Web frontend (`web/`)

[Next.js](https://nextjs.org/) 16 (App Router, TypeScript, Tailwind CSS). Caddy serves it on the same origin as the API: pages at `http://localhost:8080/`, the API under `/api/`. To use the app you only need Docker (step 3). Node.js is needed to change the frontend with hot reload (steps 1 and 2).

#### 1. Install Node.js and npm

npm ships with Node.js: installing Node.js installs npm too. Use the **24 LTS** line.

```powershell
# Windows, any one of:
winget install OpenJS.NodeJS.LTS                # Windows Package Manager
#   or the installer from https://nodejs.org (LTS), with "npm package manager" left ticked
#   or nvm-windows, to switch versions later:  nvm install 24  then  nvm use 24

# Linux / macOS (nvm):
#   curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/master/install.sh | bash
#   nvm install 24
```

Open a **new** terminal, then check:

```powershell
node --version        # v24.x
npm --version
```

If PowerShell says *running scripts is disabled on this system* for `npm`, allow local scripts once with
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or call `npm.cmd` instead of `npm`.

Install the frontend's packages, at the exact versions in `package-lock.json`:

```powershell
cd web
npm ci                # use `npm install <package>` only to add or upgrade a package
```

#### 2. Develop with hot reload

The dev server needs the API running. Start the stack (step 3), then:

```powershell
cd web
npm run dev           # http://localhost:3000; /api/* is forwarded to the stack on http://localhost:8080
npm test              # unit tests: API client, session rules
npm run typecheck     # TypeScript
```

To use an API on another address, e.g. uvicorn on the host: `$env:IDS_API_ORIGIN="http://localhost:8000"; npm run dev`
(PowerShell) or `IDS_API_ORIGIN=http://localhost:8000 npm run dev` (bash).

After changing an API endpoint or response model, regenerate the frontend's types:

```powershell
python scripts/export_openapi.py      # -> web/lib/openapi.json
cd web; npm run gen:api               # -> web/lib/api-schema.d.ts
```

#### 3. Run the frontend with Docker

The `app` profile runs the frontend together with the rest of the stack:

| Service | Role |
|---|---|
| `web` | Next.js |
| `api` | FastAPI |
| `worker`, `beat` | Celery |
| `postgres`, `redis` | Database and broker |
| `migrate` | One-shot schema upgrade |
| `proxy` | Caddy on port 8080 |

```powershell
# One-time setup
copy .env.example .env                              # then set IDS_SECRET_KEY and POSTGRES_PASSWORD

# Build the images and start everything (first build takes a few minutes)
docker compose --profile app up -d --build
docker compose --profile app ps                     # wait for api and web to show (healthy)

# First admin account (prompts for the password) and the served model
docker compose exec api python scripts/create_admin.py --email you@example.com --username admin
python scripts/build_bundle.py --exp EXP-59         # on the host, once: package a trained model into model_store/
docker compose exec api python scripts/manage_models.py --db rescan
docker compose exec api python scripts/manage_models.py --db activate <bundle_id>
```

Open **http://localhost:8080** and sign in. New users create an account at `/signup` (they get the `user` role).

| Page | What it shows |
|---|---|
| `/dashboard` | Your totals (uploads, flows analysed, known attacks, unknowns, data uploaded), a quick upload area and the recent uploads |
| `/uploads/new` | Drag and drop a CICFlowMeter CSV (≤ 100 MB, checked before sending) with transfer progress. A CSV missing features the active model needs is refused with the list. After sending, you land on the upload's results page |
| `/uploads` | Your uploads with live status while they're analysed; filter by status; delete. The file name opens its results |
| `/uploads/[id]` | Live progress while it's analysed, then the results: benign / unknown / known-attack counts (unknowns split into low confidence and anomalous), known attacks per type, the model used and the agreement with the file's `Label`, and every flow in a table you can filter by decision or class, sort and page through. Clicking a count or a bar filters the table. Download the flows as CSV, optionally with the model's input features. Click a flow to open its explanation: the reason in one line, and the 15 features that pushed the decision most, as bars toward or away from the class (red toward an attack, blue toward benign). An unknown flow shows the two classes the model hesitated between, or how far each unusual feature is from normal traffic |
| `/account` | Profile and password change |
| `/admin` (admins) | Server status, refreshed every 5 s: problems in plain words, API / database / Redis / workers, CPU, memory and disk, the job queue and uploads by status, and which model this process serves |
| `/admin/models` (admins) | Every registered bundle side by side (macro-F1, attack recall, false alarms, unknown rates, latency, throughput; the best of each in bold), Rescan `model_store/`, Activate or Roll back after a confirmation, and the version each API and worker process has loaded |
| `/admin/users` (admins) | Search by email or username, filter by role and status; make or remove admins, deactivate (signs the user out everywhere) or reactivate, each after a confirmation. Links to each user's usage and history |
| `/admin/usage` (admins) | For the last 7 / 30 / 90 days or all time: totals, a sortable per-user table (uploads, failed, deleted, data, flows, processing time, storage held now), and one user's activity per day (per week for all time) as a chart or a table |
| `/admin/audit` (admins) | Every admin change and model switch, newest first, in plain words; filter by action, or follow a person or a target to see only theirs |

| Task | Command |
|---|---|
| Rebuild only the frontend after changing `web/` | `docker compose --profile app up -d --build web` |
| Follow the frontend's logs | `docker compose logs -f web` |
| Stop, keeping data | `docker compose --profile app down` |
| Stop and delete the database, uploads and results | `docker compose --profile app down -v` |

Without Node.js installed, npm commands run in a container too. The volume `ai-ids-web-node-modules` keeps the packages between runs:

```powershell
# PowerShell
docker run --rm -v "${PWD}/web:/app" -v ai-ids-web-node-modules:/app/node_modules -w /app node:24-alpine sh -c "npm ci && npm test && npm run typecheck"
```

```bash
# Git Bash (keep it from rewriting /app into a Windows path)
export MSYS_NO_PATHCONV=1
docker run --rm -v "$(pwd -W)/web:/app" -v ai-ids-web-node-modules:/app/node_modules -w /app node:24-alpine sh -c "npm ci && npm test && npm run typecheck"
```

**Notes:**
- **Session cookies** are `Secure`, so browsers keep them over HTTPS and on `http://localhost` only. For plain-http access from another machine, set `IDS_COOKIE_SECURE=false`; the sign-in page says so if the cookies were refused.
- **If `http://localhost:8080` stops answering while the containers are healthy**, Docker Desktop's port forwarding is stuck (this happened when the PC ran out of RAM). Restarting Docker Desktop fixes it.

### Tests

The web API and the inference library are covered by a pytest suite in `tests/`. It doesn't touch your data: `.env` is ignored, and the database, model store and data directory are temporary. Bundles come from a tiny synthetic model (`tests/tiny_bundle.py`), so no trained models or dataset are needed.

```bash
pip install -r requirements/test.txt
pytest                                   # SQLite, no services needed

# Against real Postgres + Redis (Compose profile "test"; data in tmpfs, ports on localhost only)
docker compose --profile test up -d
IDS_TEST_DATABASE_URL=postgresql+psycopg://ids:ids@127.0.0.1:5433/ids_test \
IDS_TEST_REDIS_URL=redis://127.0.0.1:6380/0 pytest
docker compose --profile test down
```

The tests empty every table, so `IDS_TEST_DATABASE_URL` must name a database containing `test`.

## Configuration

All experiment parameters are controlled via [`configs/config.yaml`](configs/config.yaml):

- Dataset paths and feature definitions
- Splitting ratios and strategies (random, temporal)
- Model hyperparameters:
  - **LR:** `max_iter`, `C`, `solver`
  - **Naive Bayes:** `var_smoothing`
  - **RF:** `n_estimators`, `max_depth`, `min_samples_leaf`
  - **RF (Regularized):** `max_depth=15`, `min_samples_split=10`, `max_features=sqrt`
  - **XGBoost:** `n_estimators`, `max_depth`, `learning_rate`, `subsample`, `colsample_bytree`, `min_child_weight`, `gamma`, `reg_lambda`, `device: auto`
  - **MLP:** `hidden_sizes`, `dropout`, `epochs`, `batch_size`, `lr`, `patience`
  - **LSTM:** `hidden_size`, `num_layers`, `dropout`, `bidirectional`, `epochs`, `batch_size`, `lr`, `patience`
- Per-experiment overrides: `feature_selection:` (profile name) and `params:` (tuned hyperparameters, written by `optimize_hpo.py --auto-update`)
- Feature-selection base filters and profiles (`preprocessing.feature_selection_profiles`)
- Imbalance strategies (SMOTE, undersampling with `multiclass_max_per_class`, class_weight)
- Open-set (unknown-attack) detection settings (`open_set:`) and attack families for its evaluation (`datasets.<name>.attack_families`)
- Evaluation metrics and output paths

## Requirements

- `requirements.txt`: training pipeline (PyTorch with CUDA, Optuna, SHAP, …); it includes `requirements/api.txt`
- `requirements/api.txt`: model serving + web backend. It pins scikit-learn and XGBoost to the versions model bundles are built with.
- `requirements/test.txt`: `api.txt` plus pytest
