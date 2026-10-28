"""
Column-name normalisation, the inference engine, and the open-set decision rule.
"""

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import IsolationForest

from src.inference.engine import InferenceEngine, MissingFeaturesError
from src.inference.open_set import anomaly_scores, decide, known_thresholds
from src.inference.schema import normalize_columns
from tests.tiny_bundle import BENIGN, CANONICAL_FLOWS, DDOS, PORTSCAN, flow

CLASSES = np.array([BENIGN, DDOS, PORTSCAN])


# ── open-set decision ───────────────────────────────────────

def test_decide_covers_every_reason():
    proba = np.array([[0.90, 0.05, 0.05],     # benign, typical          -> benign
                      [0.90, 0.05, 0.05],     # benign, anomalous        -> unknown
                      [0.05, 0.95, 0.00],     # DDoS, confident          -> known_attack
                      [0.30, 0.60, 0.10]])    # DDoS, unsure             -> unknown
    anomaly = np.array([0.1, 0.9, 0.9, 0.1])  # the anomaly score never demotes a known attack
    r = decide(proba, CLASSES, anomaly, BENIGN, tau_known=0.8, tau_anomaly=0.5)
    assert r["decision"].tolist() == ["benign", "unknown", "known_attack", "unknown"]
    assert r["reason"].tolist() == ["benign", "anomalous", "known", "low_confidence"]
    assert r["predicted_class"].tolist() == [BENIGN, BENIGN, DDOS, DDOS]
    np.testing.assert_allclose(r["confidence"], [0.9, 0.9, 0.95, 0.6])
    np.testing.assert_allclose(r["attack_score"], 1 - proba[:, 0])
    np.testing.assert_allclose(r["anomaly_score"], anomaly)


@pytest.mark.parametrize("max_features", [1.0, 0.5])
def test_isolation_scores_are_scikit_learns(max_features):
    # anomaly_scores() bypasses score_samples' per-tree overhead; the result must not change
    rng = np.random.default_rng(1)
    X_fit, X = rng.normal(size=(500, 6)), rng.normal(scale=2.0, size=(300, 6))
    X[0, 2] = np.nan                                   # trees send missing values down one side
    forest = IsolationForest(n_estimators=30, max_samples=64, max_features=max_features,
                             random_state=0).fit(X_fit)
    expected = -forest.score_samples(X)
    assert np.array_equal(anomaly_scores(forest, X), expected)
    assert np.array_equal(anomaly_scores(forest, X[:1]), expected[:1])
    assert np.array_equal(anomaly_scores(forest, X.astype(np.float32)), expected)


def test_decide_with_per_class_thresholds():
    proba = np.array([[0.1, 0.7, 0.2], [0.1, 0.2, 0.7]])
    tau = known_thresholds({"known": 0.9, "known_per_class": {str(DDOS): 0.6}}, CLASSES)
    np.testing.assert_allclose(tau, [0.9, 0.6, 0.9])        # uncalibrated classes use the global one
    r = decide(proba, CLASSES, np.zeros(2), BENIGN, tau, tau_anomaly=1.0)
    assert r["reason"].tolist() == ["known", "low_confidence"]


def test_thresholds_are_inclusive_for_known_and_strict_for_anomalous():
    proba = np.array([[0.2, 0.8, 0.0], [0.8, 0.1, 0.1]])
    r = decide(proba, CLASSES, np.array([0.0, 0.5]), BENIGN, tau_known=0.8, tau_anomaly=0.5)
    assert r["reason"].tolist() == ["known", "benign"]


# ── column names ────────────────────────────────────────────

FEATURES = ["Total Fwd Packets", "Init Fwd Win Bytes", "Flow Duration"]


def test_names_are_trimmed_case_insensitive_and_java_aware():
    df = pd.DataFrame(columns=[" total fwd PACKETS ", "FWD Init Win Bytes", "Flow  Duration", "src ip", " label"])
    out, renamed = normalize_columns(df, FEATURES)
    assert list(out.columns) == ["Total Fwd Packets", "Init Fwd Win Bytes", "Flow Duration", "Src IP", "Label"]
    assert renamed["FWD Init Win Bytes"] == "Init Fwd Win Bytes"


def test_an_exact_name_wins_over_a_variant():
    df = pd.DataFrame(columns=["Total Fwd Packet", "Total Fwd Packets"])    # Java name + training name
    out, renamed = normalize_columns(df, FEATURES)
    assert list(out.columns) == ["Total Fwd Packet", "Total Fwd Packets"] and renamed == {}


# ── engine ──────────────────────────────────────────────────

@pytest.fixture(scope="module")
def engine(tiny_bundle):
    return InferenceEngine(tiny_bundle)


def canonical_df(**extra_columns):
    df = pd.DataFrame([f for f, *_ in CANONICAL_FLOWS.values()])
    for name, values in extra_columns.items():
        df[name] = values
    return df


def test_missing_features(engine):
    with pytest.raises(MissingFeaturesError) as exc:
        engine.prepare(pd.DataFrame([flow(BENIGN)]).drop(columns=["Flow Duration"]))
    assert exc.value.missing == ["Flow Duration"]
    assert "Flow Duration" in str(exc.value)


def test_unusable_values_become_nan_and_are_counted(engine):
    df = pd.DataFrame([flow(BENIGN)] * 3)
    df["Flow Bytes/s"] = df["Flow Bytes/s"].astype(object)
    df.loc[0, "Flow Bytes/s"] = np.inf
    df.loc[1, "Flow Bytes/s"] = -np.inf
    df.loc[1, "Flow Duration"] = np.nan
    df.loc[2, "Flow Bytes/s"] = "not a number"
    prepared = engine.prepare(df)
    assert prepared.imputed_cells.tolist() == [1, 2, 1]
    assert not np.isinf(prepared.features.to_numpy()).any()
    assert len(engine.predict(df)) == 3


def test_predict_keeps_metadata_and_names_classes(engine):
    ips = [f"10.0.0.{i}" for i in range(len(CANONICAL_FLOWS))]
    result = engine.predict(canonical_df(**{"Src IP": ips, "Dst Port": 80, "Label": "x"}))
    assert list(result.columns[:2]) == ["Src IP", "Dst Port"]
    assert result["Src IP"].tolist() == ips
    assert result["class_name"].tolist() == ["Benign", "DDoS", "PortScan", "Benign"]
    assert result["decision"].tolist() == [d for _, d, *_ in CANONICAL_FLOWS.values()]
    assert (result["imputed_cells"] == 0).all()


def test_label_column_is_kept_for_comparison(engine):
    prepared = engine.prepare(canonical_df(Label=["BENIGN", "DDoS", "PortScan", "BENIGN"]))
    assert prepared.label.tolist() == ["BENIGN", "DDoS", "PortScan", "BENIGN"]


def test_batches_give_the_same_result(tiny_bundle):
    df = pd.concat([canonical_df()] * 5, ignore_index=True)
    whole = InferenceEngine(tiny_bundle).predict(df)
    batched = InferenceEngine(tiny_bundle, batch_size=3).predict(df)
    pd.testing.assert_frame_equal(whole, batched)


def test_zero_rows(engine):
    result = engine.predict(canonical_df().iloc[:0])
    assert len(result) == 0
    assert {"decision", "reason", "class_name", "imputed_cells"} <= set(result.columns)
