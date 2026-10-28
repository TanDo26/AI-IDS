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
│   ├── flowmeter/                   # pcap / pcapng -> CICFlowMeter flows (port of the reference tool)
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
│   ├── create_admin.py              # CLI: first admin account for the web API
│   ├── make_sample_upload.py        # CLI: real test-split flows as an upload CSV (demos, smoke test)
│   ├── make_test_uploads.py         # CLI: N files per class (CICFlowMeter CSV / pcap / pcapng) + manifest
│   ├── make_test_capture.py         # CLI: synthetic pcap for the flow extractor (parity, benchmark)
│   ├── validate_flowmeter.py        # CLI: compare src/flowmeter with the Java CICFlowMeter
│   ├── benchmark_bundle.py          # CLI: a bundle's CPU latency against the targets
│   └── pipeline_smoke.py            # CLI: prepare → train → evaluate → bundle on synthetic data (CI)
├── tests/                           # pytest suite for the web API + inference (tiny synthetic bundle)
├── web/                             # Next.js frontend (served by Caddy next to the API)
│   └── e2e/                         # Playwright browser smoke test of the running stack
├── loadtest/locustfile.py           # Load test of the running stack (locust)
├── docker/                          # API image, Caddyfile, nightly backup script, Java reference tool
├── .github/workflows/ci.yml         # Lint, tests, pipeline smoke run, image builds
├── models/                          # Saved trained models (.pkl / .pt)
├── results/
│   ├── metrics/                     # CSV summary tables
│   ├── confusion_matrices/          # Heatmap PNGs
│   ├── pr_curves/                   # PR-AUC curve PNGs
│   ├── hpo/                         # HPO results (JSON + plots)
│   └── xai/                         # SHAP plots + feature importance CSVs
├── Dockerfile                       # Training pipeline: Python 3.13 + PyTorch CUDA 13.0
├── docker-compose.yml               # Pipeline (GPU), app stack, tunnel, tests, load test
└── requirements.txt
```

## How to Run

### Prerequisites

- **Python 3.13** (or Docker): the version of the API image too, since model bundles are pickles
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
- a pcap / pcapng capture is first turned into flows by the [flow extractor](#flow-extractor-srcflowmeter) (status `converting`);
- it predicts the flows in batches of 50,000;
- it writes per-flow results to `data/results/<upload_id>/flows.parquet` and a summary: decision counts, known-attack breakdown, agreement with an uploaded `Label` column (attack vs benign), and for a capture what was read from it;
- `GET /uploads/{id}` shows the status (`queued` → `converting` for captures → `predicting` → `completed` / `failed`), the progress and any error.

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
| `GET` | `/auth/me` | Current user (`needs_email_verification` while the app is closed to them) |
| `POST` | `/auth/verify-email`, `/auth/verify-email/resend` | Confirm an address with the emailed token (no session needed) / send a new link |
| `POST` | `/predict` | One flow → `benign` / `known_attack` / `unknown`, attack type, scores (login required) |
| `POST` | `/batch_predict` | Up to 10,000 flows (login required) |
| `POST` | `/uploads` | Upload a CICFlowMeter CSV or a pcap / pcapng capture as multipart field `file` (≤ 100 MB) and queue it for processing. The type is read from the content; a CSV's missing features are listed at once. `IDS_ENABLE_PCAP=false` turns captures off. |
| `GET` | `/uploads`, `/uploads/{id}` | Your uploads (newest first, `page` / `size` / `status`), or one upload's status and progress |
| `GET` | `/uploads/stats` | Your totals over the uploads you still have: per status, bytes, flows, known attacks, unknowns |
| `DELETE` | `/uploads/{id}` | Delete the file and its results (owner or admin); it still counts in usage totals |
| `GET` | `/uploads/{id}/summary` | Decision counts, known attacks per type, unknowns per reason, label agreement, the model that produced them; for a capture, packets read, flows extracted and what was left out |
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

### Flow extractor (`src/flowmeter/`)

Turns a packet capture into the flows the models were trained on. It is a Python port of the corrected CICFlowMeter by Engelen et al. ([GintsEngelen/CICFlowMeter](https://github.com/GintsEngelen/CICFlowMeter)) at commit `13a0615`, the version that produced the CIC-IDS2017 training data. It writes the same 82 features under the training names, keeps the tool's quirks, and needs only the standard library (pandas for the output).

```bash
python -m src.flowmeter capture.pcap -o flows.csv          # or flows.parquet; prints packets, flows and time
python -m src.flowmeter capture.pcapng --min-packets 1     # keep single-packet flows too, as the Java tool does
```

- **Input:** pcap (µs or ns) and pcapng, with Ethernet (VLAN tags too), Linux cooked (SLL, SLL2), raw IP or loopback frames.
- **IPv4 only,** like the reference's command-line tool. IPv6, ARP and damaged frames are skipped and counted.
- **Single-packet flows are left out** by default: the training data has none.
- **Flows ending:** after 120 s, after a FIN both ways and the last ACK, or after an RST, as in the reference. Flows past the timeout leave memory during the capture, so memory stays bounded; the output is the same as keeping them.
- **Where it differs from the Java tool,** all on frames that tool misreads:
  - it reads some ARP frames as IPv4, which yields a flow between `8.6.0.1` and `8.0.6.4`;
  - it counts the padding of short frames behind a VLAN tag as payload;
  - it reads every capture as Ethernet.

**Parity with the Java tool.** `docker/cicflowmeter.Dockerfile` builds the reference at `13a0615` (Java 8, jnetpcap). It reads classic pcap with Ethernet frames. `scripts/validate_flowmeter.py` matches the flows of both tools on Flow ID + start time and compares every feature. It passes at ≥ 99% of flows matched and ≥ 99.9% of values within 1e-6.

```bash
docker build -f docker/cicflowmeter.Dockerfile -t ai-ids-cicflowmeter docker
python scripts/make_test_capture.py --packets 60000 --out captures/test.pcap      # or any capture of your own
docker run --rm -v "$PWD/captures:/data" ai-ids-cicflowmeter /data/test.pcap /data/   # Git Bash: MSYS_NO_PATHCONV=1
python scripts/validate_flowmeter.py --pcap captures/test.pcap --reference captures/test.pcap_Flow.csv     --bundle model_store/<bundle_id>                       # optional: also compare the predictions
```

Checked so far:

| Capture | Packets | Flows matched | Values within 1e-6 |
|---|---:|---:|---:|
| Synthetic, 5 seeds (timeouts, teardowns, scans, ICMP, fragments, truncated frames) | 10k–60k each | 100% | 100% |
| Synthetic, 100 MB | 252,484 | 38,094 / 38,094 | 100% |
| Synthetic, 100 MB of short frames | 1,167,133 | 162,497 / 162,497 | 100% |
| Real traffic between containers (HTTP, downloads, nmap, hping3, iperf3, a connection > 120 s) | 11,763 | 1,688 / 1,689 (the ARP flow) | 100% |

On the real capture, the EXP-59 bundle gave the same decision for 100% of the matched flows from either tool. Differences in the last digits are the Java tool's: Java 8 prints some doubles with one digit too few.

**Speed:** 40,000–45,000 packets/s on one core, so a 100 MB capture takes 6–30 s depending on packet size: 6.5 s for the 252,484 packets above, 25.8 s for the 1.17 million short frames. The target was under 60 s.

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
| `proxy` | Caddy on port 8080 of this machine only (`127.0.0.1`; see [Deployment](#deployment)) |
| `backup` | Nightly `pg_dump` into `./backups` |

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
For a file to try, `python scripts/make_sample_upload.py --out sample.csv` writes 2,524 real flows of the test split (every attack type). Like real traffic, it has no `Label` column. The page shows only what the model decided, and ignores a `Label` column in an uploaded file.

**Test uploads.** `scripts/make_test_uploads.py` writes several files of chosen classes, each holding flows of one class, plus `manifest.csv` naming each file's class. It writes CICFlowMeter CSVs or pcap / pcapng captures, into `test_uploads/` (git-ignored):

```bash
python scripts/make_test_uploads.py DDoS=3 Portscan=2 Benign=1                  # 6 CSVs of 200 flows
python scripts/make_test_uploads.py "DoS Hulk=2" ssh-patator=1 --format pcap --flows 100
python scripts/make_test_uploads.py all=1 --format pcapng --only-matching       # one file per class
```

- **Where the flows come from:** held-out rows (test + validation) of the `random` split, which EXP-59 never trained on. Class names match loosely (`dos-hulk`, `DoS Hulk`, or the id `4`).
- **No answers in the files:** a file holds only what the model reads, as real traffic would, with no `Label` column. Only `manifest.csv` says which class each file holds.
- **CSV:** the rows' features, under the Java CICFlowMeter's column names, with made-up endpoints.
- **Captures:** each row is rebuilt as packets that the flow extractor reads back as the same flow:
  - packet counts, payload sizes, timing, TCP flags, header sizes and windows;
  - the Java CICFlowMeter reads these captures exactly like `src/flowmeter` does (checked: 82/82 features on every flow);
  - left out: flows over 5,000 packets, and rows that continue a connection split by the 120 s timeout;
  - a capture stops before the 100 MB upload limit.
- **Checking the files:** each file is read back the way the server reads an upload and predicted with the newest bundle in `model_store/` (`--bundle` picks another one, `--bundle none` skips the check).

  | `manifest.csv` column | Meaning |
  |---|---|
  | `predicted_as_class` / `match_rate` | How many flows the model put in the file's class |
  | `decisions` | The decision counts the results page will show (benign / unknown / known_attack) |
  | `unique_rows` | Distinct source rows. Rare classes (Heartbleed, Infiltration, the web attacks) have only a few, so their rows repeat |

- **`--only-matching`:** keeps only the flows the model puts in their class.

| Page | What it shows |
|---|---|
| `/dashboard` | Your totals (uploads, flows analysed, known attacks, unknowns, data uploaded), a quick upload area and the recent uploads |
| `/uploads/new` | Drag and drop a CICFlowMeter CSV (≤ 100 MB, checked before sending) with transfer progress. A CSV missing features the active model needs is refused with the list. After sending, you land on the upload's results page |
| `/uploads` | Your uploads with live status while they're analysed; filter by status; delete. The file name opens its results |
| `/uploads/[id]` | Live progress while it's analysed, then the results: benign / unknown / known-attack counts (unknowns split into low confidence and anomalous), known attacks per type, the model used, and every flow in a table you can filter by decision or class, sort and page through. Clicking a count or a bar filters the table. Download the flows as CSV, optionally with the model's input features. Click a flow to open its explanation: the reason in one line, and the 15 features that pushed the decision most, as bars toward or away from the class (red toward an attack, blue toward benign). An unknown flow shows the two classes the model hesitated between, or how far each unusual feature is from normal traffic |
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

The frontend's unit tests run with `npm test` (see [Web frontend](#web-frontend-web)).

**Browser smoke test** (`web/e2e/`, Playwright). It drives Chromium through Caddy against the running `app` stack:
- a new user follows a link to a page, is sent to sign in, signs up instead and lands on that page; they upload real flows and read the summary, the flows table, an explanation and the CSV export; then they upload a packet capture, which is turned into flows and analysed;
- an admin checks the server and switches the model. The user's next upload is analysed by the new model, while the first upload still explains with its own. The admin rolls back, finds both changes in the audit log, and finds the user and their usage;
- every page fits a phone screen; no console errors or failed requests along the way; signing out ends the session.

It needs an active model, an admin account, the sample flows and a sample capture. It leaves its user and uploads behind, so run it against a development stack. With only one usable bundle in `model_store/`, the model switch is skipped.

```bash
python scripts/make_sample_upload.py                       # once: -> web/e2e/data/flows.csv
python scripts/make_test_capture.py --packets 3000 --out web/e2e/data/capture.pcap   # once
docker compose exec api python scripts/create_admin.py --email e2e-admin@example.test --username e2e_admin

export E2E_ADMIN_EMAIL=e2e-admin@example.test
read -rsp "Admin password: " E2E_ADMIN_PASSWORD && export E2E_ADMIN_PASSWORD
docker compose --profile app run --rm e2e                  # about 30 s, plus a minute for the first npm install
```

In PowerShell, set `$env:E2E_ADMIN_EMAIL` and `$env:E2E_ADMIN_PASSWORD` instead. On failure, `web/test-results/` holds a trace and a screenshot and `web/playwright-report/index.html` the report.
Sign-up allows 3 accounts an hour per address, so a fourth run within the hour stops at sign-up.

## Deployment

The whole app runs on one machine with Docker Compose: this PC for now, a cloud VM later. Visitors reach it through a **Cloudflare Tunnel**, so no router port is opened and Cloudflare provides HTTPS.

### Compose profiles

| Profile | Services | Use |
|---|---|---|
| `app` | `proxy` (Caddy), `web`, `api`, `worker`, `beat`, `postgres`, `redis`, `migrate`, `backup` | The application |
| `tunnel` | `cloudflared` | Publish `app` on your own hostname (named tunnel) |
| `quick-tunnel` | `quick-tunnel` | Publish `app` on a throwaway `*.trycloudflare.com` address |
| `pipeline` | `prepare`, `train`, `evaluate`, `run-all`, `hpo`, `xai` | Training on the GPU (`docker compose run --rm train` enables it) |
| `test` | `postgres-test`, `redis-test` | pytest against real services |
| `e2e` | `e2e` | Browser smoke test |
| `loadtest` | `locust` | Load test |

Every long-running service has a healthcheck and `restart: unless-stopped`, so the stack comes back with Docker Desktop. `docker compose --profile app ps` should show each one `(healthy)`. `cloudflared` is the exception: its image has no shell for a healthcheck.

### Production settings

In `.env` (from `.env.example`), before the first start:

| Setting | Why |
|---|---|
| `IDS_ENV=production` | The API then refuses to start with the default or a short secret key |
| `IDS_SECRET_KEY` | Signs the session tokens: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `POSTGRES_PASSWORD` | Set it before the first start. The database volume keeps the password it was created with, so changing it later also needs `ALTER USER` inside Postgres |
| `IDS_ENABLE_PCAP` | Leave it out (default `true`), or capture uploads are refused |
| `CLOUDFLARE_TUNNEL_TOKEN` | For the named tunnel (below) |
| `IDS_EMAIL_VERIFICATION`, `IDS_SMTP_*` | Optional: new accounts confirm their email address ("Email verification" below) |

```bash
docker compose --profile app up -d --build
docker compose exec api python scripts/create_admin.py --email you@example.com --username admin
docker compose exec api python scripts/manage_models.py --db rescan
docker compose exec api python scripts/manage_models.py --db activate <bundle_id>
```

Caddy listens on `127.0.0.1:8080` only, so other machines on the network can't reach it directly; visitors come through the tunnel, which runs inside the Docker network. `IDS_HTTP_PORT=8080` would listen on every interface. The PC has to stay awake for the site to be up.

### Publishing with Cloudflare Tunnel

**Named tunnel** (a stable address such as `https://ids.example.com`; needs a domain on Cloudflare, Free plan):
1. In the Cloudflare dashboard, open **Zero Trust → Networks → Tunnels → Create a tunnel**, choose **Cloudflared** and name it.
2. Of the install command it shows, copy only the token (the long value after `--token`) into `.env` as `CLOUDFLARE_TUNNEL_TOKEN`.
3. Add a **public hostname**: e.g. `ids` on your domain, service type `HTTP`, URL `proxy:80`.
4. Start the stack with the tunnel:

```bash
docker compose --profile app --profile tunnel up -d
docker compose --profile app --profile tunnel logs -f cloudflared        # "Registered tunnel connection" x4
```

If the log says `"cloudflared tunnel run" requires the ID or name of the tunnel`, the token is missing from `.env`.

**Quick tunnel** (a short demo, no account): the address changes at every start.

```bash
docker compose --profile app --profile quick-tunnel up -d
docker compose --profile app --profile quick-tunnel logs quick-tunnel | grep trycloudflare.com
```

Commands that name `cloudflared` or `quick-tunnel` need both profiles, as above. Their service depends on `proxy`, which is in `app`, and without `--profile app` Compose answers `no such service: proxy`.

**What the proxy does for the tunnel** (`docker/Caddyfile`):
- **Visitor addresses:** Caddy takes the visitor's address from Cloudflare's `Cf-Connecting-Ip`, which a browser can't fake, and hands only that address to the API. Without this, every visitor would share cloudflared's address, and so would the sign-in (5 a minute) and sign-up (3 an hour) limits. Access logs and sessions record the real address.
- **Security headers:** `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin` and `Content-Security-Policy: frame-ancestors 'none'` (no framing). The `Server` header is removed.
- **Caching:**
  - The API answers with `Cache-Control: no-store`. Cloudflare caches `.csv` files by default, so without that header a results export could be kept at the edge.
  - Pages get `no-cache`, so a redeploy never leaves the edge serving pages whose script files are gone.
  - The hashed files under `/_next/static/` stay cacheable for a year.
  - Leave Cloudflare's default caching as it is (no "Cache Everything" rule).
- **Upload size:** uploads over 100 MB are refused before they reach the API (Cloudflare Free's limit is the same).

### Email verification

With `IDS_EMAIL_VERIFICATION=true`, a new account gets an email with a link, and can't use the app until the link is opened. The feature is off by default.

**How it works:**
- **Signing up still signs in.** Until the link is opened, the app shows only "Confirm your email address", with **Send a new link** and **Sign out**. The API answers 403 to uploads, results, `/predict` and the admin pages.
- **The link** opens `/verify-email`:
  - it works for 24 hours (`IDS_EMAIL_TOKEN_HOURS`);
  - it needs no session, so it also works on another device;
  - opening it twice does no harm;
  - a new link replaces the earlier ones, and a user can ask for at most 3 an hour.
- **The waiting page goes on by itself** once the link has been opened somewhere else: it asks the API again every 5 seconds.
- **Existing accounts count as confirmed:** accounts that existed before migration 0004, and admins made with `create_admin.py`.
- **Admins see who hasn't confirmed:** "Email not confirmed" in the users list.
- **Nobody can block an address by registering it first.** An email or username is released when someone signs up with it, if the account holding it:
  - never confirmed its address;
  - is older than a link's lifetime;
  - has no uploads.

  The old account is removed, and the audit log records it as "Unconfirmed account removed".

**Settings** in `.env`:

| Setting | Gmail | Resend | Mailpit (testing) |
|---|---|---|---|
| `IDS_MAIL_BACKEND` | `smtp` | `smtp` | `smtp` |
| `IDS_SMTP_HOST` | `smtp.gmail.com` | `smtp.resend.com` | `mailpit` |
| `IDS_SMTP_PORT` | `587` | `587` | `1025` |
| `IDS_SMTP_SECURITY` | `starttls` | `starttls` | `none` |
| `IDS_SMTP_USERNAME` | your Gmail address | `resend` | (none) |
| `IDS_SMTP_PASSWORD` | an app password | the API key | (none) |
| `IDS_MAIL_FROM` | `AI-IDS <you@gmail.com>` | an address on your verified domain | anything |

**Mail providers:**
- **Gmail:**
  - Turn on 2-Step Verification for the account.
  - Create an app password at https://myaccount.google.com/apppasswords and use its 16 letters, without the spaces, as `IDS_SMTP_PASSWORD`. The account's normal password doesn't work.
  - Gmail sends about 500 emails a day.
- **Resend:** the free plan sends 100 emails a day, but only from a domain you have verified there with DNS records, such as the named tunnel's domain.
- **Mailpit:** it keeps every email on this machine and shows them at http://127.0.0.1:8025; nothing is delivered. Start it with the stack:

```bash
docker compose --profile app --profile mail up -d     # with the Mailpit column above and IDS_EMAIL_VERIFICATION=true
```

**Notes:**
- **`IDS_PUBLIC_URL`** (e.g. `https://ids.example.com`) is the base of the links.
  - Empty: links use the address the visitor signed up on, which suits the changing quick-tunnel address.
  - Set it once the site is reachable other than through the tunnel. Otherwise a forged `Host` header could put another site's address in the email.
- **Production needs SMTP:** with `IDS_ENV=production`, the API refuses to start when verification is on but no SMTP server is set.
- **Development without SMTP:** `IDS_MAIL_BACKEND=console` writes each email, link included, to the api log (`docker compose logs api | grep verify-email`).
- **Delivery failures:** mail goes out after the response. If the SMTP server fails, the api log has `Could not send email`, and the user can send a new link.
- **Browser smoke test:** with verification on, it reads the sign-up link from Mailpit, so start Mailpit too (`E2E_MAILPIT_URL`, default `http://mailpit:8025`).

### Logs

The API, worker and beat write one JSON object per line (`IDS_LOG_FORMAT=json` in Compose; `text` is easier to read on the host). Every request gets one access line with its id, user, status and duration. Everything logged while handling it carries the same `request_id`, which the browser sees as the `X-Request-ID` header. Lines from a processing job carry the Celery `task_id`.

```json
{"time": "2026-10-27T17:57:26.096+00:00", "level": "INFO", "logger": "ids.access", "message": "GET /api/v1/auth/me 200", "method": "GET", "path": "/api/v1/auth/me", "status": 200, "duration_ms": 5.6, "client": "203.0.113.7", "user_id": 1, "request_id": "10437b11-97b5-4678-b8da-a89264ed8b8b"}
```

```bash
docker compose logs -f api worker                        # follow
docker compose logs api | grep <request id>              # one request
docker compose logs api | grep '"status": 5'             # server errors
```

Health checks and Prometheus scrapes are logged at DEBUG only (`IDS_LOG_LEVEL=DEBUG` shows them). Metrics for Prometheus are at `http://api:8000/metrics` inside the Compose network. Grafana is not part of the stack.

### Backups

The `backup` service dumps the database (`pg_dump`, custom format) into `./backups` once a day. The dump runs at the first check after `BACKUP_HOUR` (UTC, default 2), or as soon as the newest dump is more than a day old, so a PC that was off catches up when it's back. The newest `BACKUP_KEEP` (7) dumps are kept. The files contain password hashes and e-mail addresses: copy them somewhere safe, off this machine.

```bash
export MSYS_NO_PATHCONV=1                                # Git Bash only
docker compose exec backup sh /backup.sh now             # one more now
ls backups/

# Restore (replaces the current database): stop what writes to it first
docker compose stop api worker beat
docker compose exec backup pg_restore --clean --if-exists --no-owner --single-transaction \
    --dbname=ids /backups/ids-20261027-175743.dump      # your POSTGRES_DB and dump name
docker compose start api worker beat
```

Two things are not in the dump:
- **`model_store/`:** bundles can be rebuilt from the pipeline, but copy the folder with the backups anyway.
- **Uploads and results** (volume `ai-ids_appdata`): archive it when needed:

```bash
docker run --rm -v ai-ids_appdata:/data:ro -v "$(pwd -W)/backups:/out" alpine:3.22 tar czf /out/appdata.tgz -C /data .
```

(`$(pwd -W)` is Git Bash; use `${PWD}` in PowerShell and `$(pwd)` on Linux.)

### Moving to a VM

1. Install Docker on the VM (e.g. Oracle Cloud Always Free, or student credits), then clone the repository.
2. Copy `.env`, `model_store/`, the newest dump from `backups/` and, if wanted, `appdata.tgz`.
3. Start the stack: `docker compose --profile app up -d --build`. `migrate` creates an empty schema.
4. Restore the dump as above. For the uploads, unpack `appdata.tgz` into the `ai-ids_appdata` volume with the same `alpine` command, using `tar xzf`.
5. Stop the tunnel on the PC. Then start it on the VM with the same `CLOUDFLARE_TUNNEL_TOKEN`: `docker compose --profile app --profile tunnel up -d`. The hostname stays the same.

### Continuous integration

`.github/workflows/ci.yml` runs on every push to `main` and every pull request:

| Job | What it checks |
|---|---|
| `lint` | `ruff check .` (`ruff.toml`: undefined names, unused imports and variables, syntax-level errors) |
| `test` | pytest on SQLite, then again against Postgres and Redis service containers |
| `pipeline` | `scripts/pipeline_smoke.py` with CPU PyTorch: synthetic data for 5 days, prepare → train → evaluate for two experiments, then a bundle built and loaded as the server does (about 20 s) |
| `web` | Vitest and `tsc` |
| `images` | Builds the API and web images, checks the API image imports the app, validates `docker-compose.yml` |

The GPU pipeline image (`Dockerfile`, about 12 GB with CUDA PyTorch) is too big for a CI runner. The `pipeline` job runs the same code on CPU instead.

```bash
pip install -r requirements/dev.txt      # pytest, ruff, locust
ruff check .
python scripts/pipeline_smoke.py         # in a temporary directory; your dataset/, models/, results/ are untouched
```

### Load test and targets

The bundle on its own:

```bash
python scripts/benchmark_bundle.py --bundle model_store/<bundle_id>
docker compose exec api python scripts/benchmark_bundle.py --bundle /app/model_store/<bundle_id>   # in the server image
```

The whole stack, through Caddy, from inside the Docker network:
- 20 simulated users, each sending a `/predict` or an explanation about once a second;
- before that, one capture upload is timed, from upload done to results ready;
- the account can be any user, e.g. the admin; the flows come from `scripts/make_sample_upload.py`;
- the run fails (exit code 1) when a target is missed.

```bash
python scripts/make_sample_upload.py                                         # -> web/e2e/data/flows.csv
python scripts/make_test_capture.py --size-mb 99.5 --out web/e2e/data/load.pcap
export LOADTEST_EMAIL=you@example.com LOADTEST_CAPTURE=load.pcap
read -rsp "Password: " LOADTEST_PASSWORD && export LOADTEST_PASSWORD
docker compose --profile app --profile loadtest run --rm locust                    # 2 minutes
docker compose --profile app --profile loadtest run --rm locust --tags predict --users 50   # options override
```

Results on the development PC (8 logical CPUs, Docker Desktop on Windows, load generator on the same machine), EXP-59 (XGBoost, 52 features):

| Measure | Target | Result |
|---|---|---|
| One flow, bundle alone (in the API container) | p95 < 1 ms | p50 9 ms, p95 13 ms: **missed** |
| 10,000 flows, bundle alone | < 1 s | 612 ms in the API (one thread per request, `/batch_predict`); 225 ms in the worker (8 threads, uploads) |
| `POST /predict`, one request at a time | p95 < 50 ms | p50 27 ms, p95 36 ms |
| `POST /predict` under 20 users (~14 requests/s) | p95 < 50 ms | p50 28 ms, p95 86 ms: **missed** |
| One explanation under 20 users | p95 < 300 ms | p50 68 ms, p95 120 ms |
| 100 MB capture (233,411 packets, 24,321 flows), upload done → results ready | < 2 min | 6.6 s |

**What made it faster.** Before this, one flow took 37 ms (p95) in the bundle and 50–100 ms in the server image.

| Change | Effect |
|---|---|
| `OMP_WAIT_POLICY=PASSIVE` in the API image | XGBoost's OpenMP threads were spinning between calls and fighting over the CPUs of a container with several processes. A 10k batch also went from 392 to 226 ms |
| One OpenMP thread per API request | Concurrent requests no longer each start 8 threads |
| 4 API processes instead of 2 (`IDS_API_WORKERS`) | Explanation p95 went from 580 ms to 120 ms. Each process uses about 370 MB; set 2 on a machine short of memory |
| Isolation Forest scored with its trees directly (same result to the bit) | 23 → 2 ms per flow |
| Flows converted to numbers in one step | 24 → 4 ms per request |

**What is still missed:**
- **One flow in under 1 ms:** the flow passes through pandas, scikit-learn's preprocessing, XGBoost's Python interface and the Isolation Forest, each costing 1–4 ms of overhead per call. Getting under 1 ms needs the pipeline compiled into one model (e.g. ONNX or Treelite), which the plan postponed.
- **`/predict` p95 under load:** about 25 ms of CPU-bound Python per request. With concurrent requests, they queue for the CPU (and for each process's interpreter lock). It stays under 50 ms one request at a time.
- **First explanation:** the first explanation in each API process builds the SHAP explainers (2–5 s), so p99 is a few seconds.

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
- `requirements/dev.txt`: `test.txt` plus ruff (lint, `ruff.toml`) and locust (load test)
