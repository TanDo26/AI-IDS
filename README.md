# Machine Learning-Based Intrusion Detection on Real-World Edge IDS Telemetry

A multiclass network intrusion detection system using traditional machine learning on the [GeNIS (GECAD Network Intrusion Scenarios)](https://zenodo.org/records/14919237) dataset.

## Overview

Intrusion Detection Systems (IDS) are essential for identifying malicious activities in network traffic. Traditional rule-based approaches struggle with large-scale telemetry and novel attack patterns. This project investigates the application of supervised machine learning — specifically **Logistic Regression** and **Random Forest** — to classify network flows into 13 distinct sub-categories spanning benign traffic, brute-force attacks, denial-of-service attacks, and reconnaissance activities.

### Classification Task

Rather than binary (benign vs. malicious) detection, this project performs **multiclass classification** across four main categories and 13 sub-categories:

| Binary Label | Category | Sub-Categories |
|:---:|---|---|
| 0 | benign | `admin`, `background`, `user` |
| 1 | bruteforce | `bruteforce-ftp`, `bruteforce-smb`, `bruteforce-ssh` |
| 1 | dos | `dos-hulk`, `dos-icmp`, `dos-pushack`, `dos-slowloris`, `dos-udp` |
| 1 | recon | `recon-dns`, `recon-nmap` |

## Dataset

**GeNIS: GECAD Network Intrusion Scenarios**

**Download:** [https://zenodo.org/records/14919237](https://zenodo.org/records/14919237)

The GeNIS dataset provides labelled network-flow data with telemetry and enrichment information recorded from an enterprise network. This project uses the **scenario data** (8 scenario files), which contain a total of **816,435 network-flow records**.

<details>
<summary><strong>Label Distribution</strong></summary>

| Sub-Category | Count | Percent |
|---|---:|---:|
| dos-udp | 131,072 | 16.05% |
| dos-icmp | 131,072 | 16.05% |
| dos-pushack | 130,942 | 16.04% |
| user | 125,128 | 15.33% |
| dos-slowloris | 85,212 | 10.44% |
| background | 83,244 | 10.20% |
| dos-hulk | 51,327 | 6.29% |
| admin | 32,664 | 4.00% |
| recon-nmap | 27,713 | 3.39% |
| bruteforce-smb | 10,001 | 1.22% |
| bruteforce-ssh | 4,696 | 0.58% |
| bruteforce-ftp | 3,344 | 0.41% |
| recon-dns | 20 | 0.00% |
| **Total** | **816,435** | **100%** |

</details>

## What Has Been Done

### Dataset Investigation
- Loaded and concatenated all 8 scenario CSV files (`scenario-1-disrupt.csv` through `scenario-8-authtest.csv`)
- Analyzed label distribution across all 13 sub-categories
- Identified significant class imbalance (e.g., `recon-dns` has only 20 samples)

### Feature Selection & Preprocessing
- Selected **60 numeric features** (flow timing, volume, rate, and connection-level metrics) and **3 categorical features** (`State`, `Flgs`, `Proto`) from the original 126 raw fields
- Excluded identifiers, timestamps, MAC/IP addresses, and derived label columns to prevent data leakage
- Cleaned non-numeric placeholders with `pd.to_numeric(errors='coerce')` and filled NaN with 0
- One-hot encoded categorical features → **84 total features**
- Saved preprocessed dataset to `dataset/preprocessed_dataset.csv`

### Train/Test Split
- Applied stratified 80/20 split (`random_state=42`) preserving class proportions
- **Training set:** 653,148 rows | **Test set:** 163,287 rows
- All 13 classes present in both splits
- Saved splits to `dataset/splits/`

### Model Training (Planned)
A **2 × 2 experiment matrix** comparing two preprocessing strategies with two models:

|  | Logistic Regression | Random Forest |
|---|:---:|:---:|
| **A:** StandardScaler + `class_weight='balanced'` | LR-A | RF-A |
| **B:** StandardScaler + RandomUnderSampling | LR-B | RF-B |

## Project Structure

```
IDS/
├── DataInvestigate.ipynb     # Data exploration, preprocessing, and splitting
├── requirements.txt          # Python dependencies
├── main.pdf                  # Internship report
├── implementation_plan.md    # Detailed plan for model training
├── README.md
└── dataset/
    ├── scenario-*-disrupt.csv      # Raw scenario files (1–5)
    ├── scenario-*-authtest.csv     # Raw scenario files (6–8)
    ├── genis-features.csv          # Feature documentation
    ├── preprocessed_dataset.csv    # Cleaned & encoded dataset
    └── splits/
        ├── X_train.csv             # Training features (653K rows)
        ├── X_test.csv              # Test features (163K rows)
        ├── y_train.csv             # Training labels
        └── y_test.csv              # Test labels
```

## Requirements

```
torch
pandas
numpy
matplotlib
seaborn
scikit-learn
```

Install with:

```bash
pip install -r requirements.txt
```

## References

- **Dataset:** Lopes, J., Vasconcelos, G., & Vale, Z. (2025). *GeNIS: GECAD Network Intrusion Scenarios* [Dataset]. Zenodo. [https://zenodo.org/records/14919237](https://zenodo.org/records/14919237)
