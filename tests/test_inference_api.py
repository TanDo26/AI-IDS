"""
/predict and /batch_predict on the active bundle.
"""

import pytest

from src.inference.schema import JAVA_TO_TRAINING
from tests.conftest import TINY_A
from tests.helpers import API, bearer, csrf, login
from tests.tiny_bundle import CANONICAL_FLOWS, CONSTANT_FEATURE, DDOS, flow, BENIGN

TRAINING_TO_JAVA = {train: java for java, train in JAVA_TO_TRAINING.items()}


def predict(client, user, features):
    return client.post(f"{API}/predict", json={"features": features}, headers=bearer(user))


def batch(client, user, flows):
    return client.post(f"{API}/batch_predict", json={"flows": flows}, headers=bearer(user))


def test_login_required(client, active_bundle):
    assert client.post(f"{API}/predict", json={"features": flow(BENIGN)}).status_code == 401


def test_cookie_sessions_need_csrf(client, user, active_bundle):
    login(client)
    assert client.post(f"{API}/predict", json={"features": flow(BENIGN)}).status_code == 403
    r = client.post(f"{API}/predict", json={"features": flow(BENIGN)}, headers=csrf(client))
    assert r.status_code == 200


def test_no_active_bundle(client, user):
    r = predict(client, user, flow(BENIGN))
    assert r.status_code == 503
    assert "No active model bundle" in r.json()["detail"]


def test_predict_one_flow(client, user, active_bundle):
    r = predict(client, user, flow(DDOS))
    assert r.status_code == 200
    body = r.json()
    assert body["bundle_id"] == TINY_A
    assert (body["decision"], body["reason"], body["predicted_class"], body["class_name"]) == \
           ("known_attack", "known", DDOS, "DDoS")
    # attack_score = 1 - P(Benign), which is at least the predicted attack class's probability
    assert 0 < body["confidence"] <= body["attack_score"] + 1e-9 <= 1 + 1e-9
    assert body["imputed_cells"] == 0 and body["inference_ms"] >= 0


def test_batch_covers_every_decision(client, user, active_bundle):
    r = batch(client, user, [f for f, *_ in CANONICAL_FLOWS.values()])
    assert r.status_code == 200
    body = r.json()
    assert body["total_flows"] == len(CANONICAL_FLOWS)
    got = [(p["decision"], p["reason"], p["predicted_class"]) for p in body["predictions"]]
    assert got == [(d, reason, c) for _, d, reason, c in CANONICAL_FLOWS.values()]


def test_java_cicflowmeter_names_are_accepted(client, user, active_bundle):
    training = flow(DDOS)
    java = {TRAINING_TO_JAVA.get(k, k): v for k, v in training.items()}
    assert java.keys() != training.keys()
    assert predict(client, user, java).json()["decision"] == "known_attack"


def test_column_names_are_trimmed_and_case_insensitive(client, user, active_bundle):
    messy = {f"  {k.upper()} ": v for k, v in flow(DDOS).items()}
    assert predict(client, user, messy).json()["predicted_class"] == DDOS


def test_extra_and_unused_columns_are_ignored(client, user, active_bundle):
    features = flow(BENIGN, **{"Something Else": 1})
    del features[CONSTANT_FEATURE]          # dropped by the bundle's feature selector
    assert predict(client, user, features).status_code == 200


def test_missing_features_are_listed(client, user, active_bundle):
    features = flow(BENIGN)
    del features["Flow Duration"], features["Flow Bytes/s"]
    r = predict(client, user, features)
    assert r.status_code == 422
    assert sorted(r.json()["detail"]["missing"]) == ["Flow Bytes/s", "Flow Duration"]


def test_inf_and_non_numeric_values_are_imputed(client, user, active_bundle):
    # JSON has no Infinity literal; scripts send it as a string, which parses to inf
    features = {**flow(BENIGN), "Flow Bytes/s": "Infinity", "Total Fwd Packets": "n/a"}
    r = predict(client, user, features)
    assert r.status_code == 200
    assert r.json()["imputed_cells"] == 2


@pytest.mark.parametrize("n", [0, 10_001])
def test_batch_size_limits(client, user, active_bundle, n):
    assert batch(client, user, [{"Flow Duration": 1}] * n).status_code == 422
