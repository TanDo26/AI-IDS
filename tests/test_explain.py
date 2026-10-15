"""
Per-flow explanations: shape of the JSON for each decision reason.
"""

import json

import numpy as np
import pandas as pd
import pytest

from src.inference.explain import FlowExplainer
from tests.tiny_bundle import BENIGN, CANONICAL_FLOWS, flow


@pytest.fixture(scope="module")
def explainer(tiny_bundle):
    return FlowExplainer(tiny_bundle)


def explain(explainer, name):
    return explainer.explain(pd.DataFrame([CANONICAL_FLOWS[name][0]]))


def check_contributions(explanation, features):
    items = explanation["contributions"]
    assert 0 < len(items) <= 15
    assert {i["feature"] for i in items} <= set(features)
    sizes = [abs(i["contribution"]) for i in items]
    assert sizes == sorted(sizes, reverse=True)


@pytest.mark.parametrize("name", list(CANONICAL_FLOWS))
def test_explanation_matches_the_prediction(explainer, name):
    _, decision, reason, predicted = CANONICAL_FLOWS[name]
    out = explain(explainer, name)
    json.dumps(out)                                  # plain JSON types only
    assert (out["decision"], out["reason"], out["predicted_class"]) == (decision, reason, predicted)
    assert out["bundle_id"] == explainer.bundle.bundle_id
    for explanation in out["explanations"]:
        check_contributions(explanation, explainer.features)


@pytest.mark.parametrize("name", ["benign", "ddos"])
def test_known_or_benign_explains_the_predicted_class(explainer, name):
    out = explain(explainer, name)
    [explanation] = out["explanations"]
    assert explanation["target"] == "class" and explanation["class"] == out["predicted_class"]
    assert explanation["output_space"] == "probability"         # RandomForest
    # Every feature is listed (6 < 15), so SHAP's additivity holds: base + contributions = probability
    total = explanation["base_value"] + sum(i["contribution"] for i in explanation["contributions"])
    assert total == pytest.approx(out["confidence"], abs=1e-6)


def test_low_confidence_explains_the_top_two_classes(explainer):
    out = explain(explainer, "portscan")
    classes = [e["class"] for e in out["explanations"]]
    assert len(classes) == 2 and classes[0] == out["predicted_class"] and classes[1] != classes[0]


def test_anomalous_explains_the_anomaly_score(explainer):
    out = explain(explainer, "odd_benign")
    [explanation] = out["explanations"]
    assert explanation["target"] == "anomaly" and explanation["output_space"] == "anomaly_score"
    top = explanation["contributions"][0]
    assert top["deviation_sd"] > 3 and "benign_median" in top
    assert all("deviation_sd" in i for i in explanation["contributions"])


def test_stored_result_gives_the_same_explanation(explainer):
    df = pd.DataFrame([CANONICAL_FLOWS["ddos"][0]])
    stored = explainer.bundle.predict(df).iloc[0]
    assert explainer.explain(df, result=stored) == explainer.explain(df)


def test_missing_values_are_reported_as_null(explainer):
    out = explainer.explain(pd.DataFrame([flow(BENIGN, **{"Flow Duration": np.nan})]))
    values = {i["feature"]: i["value"] for e in out["explanations"] for i in e["contributions"]}
    assert values["Flow Duration"] is None


def test_one_flow_at_a_time(explainer):
    with pytest.raises(ValueError, match="one flow"):
        explainer.explain(pd.DataFrame([flow(BENIGN)] * 2))
