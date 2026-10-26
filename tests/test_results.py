"""
An upload's results: summary, paginated flows (DuckDB), explanations with the producing bundle,
CSV export, and the explainer cache.
"""

import io
import shutil
import uuid

import pandas as pd
import pytest
from sqlalchemy import update

from src.api.db.models import Upload
from src.api.runtime.explainers import ExplainerCache
from src.api.uploads import processing
from src.inference.bundle import BundleError
from src.inference.manager import ModelManager
from tests.conftest import TINY_A, TINY_B
from tests.helpers import API, bearer, flows_csv, upload_file
from tests.tiny_bundle import CANONICAL_FLOWS, FEATURES

LABELS = ["BENIGN", "DDoS", "PortScan", "BENIGN"]
COPIES = 5
N = len(CANONICAL_FLOWS) * COPIES            # 20 flows; row i is canonical flow i % 4
EXPECTED = [(decision, reason, cls) for _, decision, reason, cls in CANONICAL_FLOWS.values()]
RESULT_PATHS = ["summary", "flows", "flows/0/explain", "export.csv"]


@pytest.fixture
def completed(client, user, active_bundle, run_queued):
    """completed(content=None) -> id of a processed upload owned by `user`."""
    def make(content=None) -> str:
        r = upload_file(client, user, content if content is not None else flows_csv(n_copies=COPIES, label=LABELS))
        assert r.status_code == 201, r.text
        assert run_queued() == ["completed"]
        return r.json()["id"]
    return make


def get(client, user, upload_id, path, **params):
    return client.get(f"{API}/uploads/{upload_id}/{path}", params=params, headers=bearer(user))


# ── summary ─────────────────────────────────────────────────

def test_summary(client, user, completed, registry, db):
    upload_id = completed()
    body = get(client, user, upload_id, "summary").json()
    assert (body["n_flows"], body["n_benign"], body["n_known_attack"], body["n_unknown"]) == (N, 5, 5, 10)
    assert body["attack_breakdown"] == {"DDoS": 5}
    assert body["unknown_breakdown"] == {"anomalous": 5, "low_confidence": 5}
    assert body["label_agreement"] == pytest.approx(0.75) and body["inference_ms"] > 0
    assert body["model"]["bundle_id"] == TINY_A
    assert (body["model"]["experiment"], body["model"]["model"]) == ("TINY", "random_forest")


# ── availability and access ─────────────────────────────────

@pytest.mark.parametrize("path", RESULT_PATHS)
def test_not_ready_yet(client, user, active_bundle, path):
    upload_id = upload_file(client, user, flows_csv()).json()["id"]     # queued, never processed
    r = get(client, user, upload_id, path)
    assert r.status_code == 409 and "the upload is queued" in r.json()["detail"]


def test_failed_upload_says_why(client, user, active_bundle, run_queued, settings, db):
    upload_id = upload_file(client, user, flows_csv()).json()["id"]
    upload = db.get(Upload, uuid.UUID(upload_id))
    (settings.data_dir / upload.stored_path).write_bytes(b"Flow Duration,Other\n1,2\n")
    run_queued()
    r = get(client, user, upload_id, "summary")
    assert r.status_code == 409 and "failed" in r.json()["detail"] and "missing" in r.json()["detail"]


@pytest.mark.parametrize("path", RESULT_PATHS)
def test_results_file_gone(client, user, completed, settings, path):
    upload_id = completed()
    shutil.rmtree(settings.results_dir / upload_id)
    assert get(client, user, upload_id, path).status_code == 410


@pytest.mark.parametrize("path", RESULT_PATHS)
def test_owner_or_admin_only(client, user, admin, make_user, completed, path):
    upload_id = completed()
    assert get(client, make_user("bob@example.com"), upload_id, path).status_code == 404
    assert get(client, admin, upload_id, path).status_code == 200
    assert client.get(f"{API}/uploads/{upload_id}/{path}").status_code == 401


@pytest.mark.parametrize("path", RESULT_PATHS)
def test_deleted_upload(client, user, completed, path):
    upload_id = completed()
    client.delete(f"{API}/uploads/{upload_id}", headers=bearer(user))
    assert get(client, user, upload_id, path).status_code == 404


# ── flows ───────────────────────────────────────────────────

def test_flows_first_page(client, user, completed):
    body = get(client, user, completed(), "flows").json()
    assert (body["total"], body["page"], body["size"]) == (N, 1, 50)
    assert [f["row"] for f in body["items"]] == list(range(N))
    first = body["items"][0]
    assert first["metadata"] == {"Src IP": "10.0.0.1"} and first["label"] == "BENIGN"
    assert (first["decision"], first["class_name"], first["imputed_cells"]) == ("benign", "Benign", 0)
    assert not set(first) & set(FEATURES)                              # features stay in the file
    assert [(f["decision"], f["reason"], f["predicted_class"]) for f in body["items"]] == EXPECTED * COPIES


def test_flows_pagination(client, user, completed):
    upload_id = completed()
    body = get(client, user, upload_id, "flows", page=2, size=7).json()
    assert ([f["row"] for f in body["items"]], body["total"]) == (list(range(7, 14)), N)
    beyond = get(client, user, upload_id, "flows", page=5, size=7).json()
    assert (beyond["items"], beyond["total"]) == ([], N)


@pytest.mark.parametrize("params, total, check", [
    ({"decision": "unknown"}, 10, lambda f: f["decision"] == "unknown"),
    ({"class_name": "DDoS"}, 5, lambda f: f["class_name"] == "DDoS"),
    ({"decision": "unknown", "class_name": "PortScan"}, 5, lambda f: f["reason"] == "low_confidence"),
    ({"class_name": "x' OR '1'='1"}, 0, None),                         # a value, never SQL
])
def test_flows_filters(client, user, completed, params, total, check):
    body = get(client, user, completed(), "flows", **params).json()
    assert body["total"] == total and len(body["items"]) == total
    assert all(check(f) for f in body["items"])


def test_flows_sorting(client, user, completed):
    upload_id = completed()
    rows = get(client, user, upload_id, "flows", sort="-row").json()["items"]
    assert [f["row"] for f in rows] == list(range(N - 1, -1, -1))
    items = get(client, user, upload_id, "flows", sort="-anomaly_score").json()["items"]
    scores = [f["anomaly_score"] for f in items]
    assert scores == sorted(scores, reverse=True)
    for a, b in zip(items, items[1:]):                                  # ties: row order
        if a["anomaly_score"] == b["anomaly_score"]:
            assert a["row"] < b["row"]


@pytest.mark.parametrize("params", [
    {"sort": "bogus"}, {"sort": "row; DROP TABLE x"}, {"sort": "Flow Duration"},
    {"decision": "bogus"}, {"size": 501}, {"size": 0}, {"page": 0},
])
def test_flows_rejects_bad_parameters(client, user, completed, params):
    assert get(client, user, completed(), "flows", **params).status_code == 422


# ── explanations ────────────────────────────────────────────

@pytest.mark.parametrize("row", range(4))
def test_explain_each_decision(client, user, completed, row):
    upload_id = completed()
    body = get(client, user, upload_id, f"flows/{row}/explain").json()
    decision, reason, cls = EXPECTED[row]
    assert (body["decision"], body["reason"], body["predicted_class"]) == (decision, reason, cls)
    assert (body["upload_id"], body["row"], body["bundle_id"]) == (upload_id, row, TINY_A)

    stored = get(client, user, upload_id, "flows", size=1, page=row + 1).json()["items"][0]
    assert body["confidence"] == stored["confidence"] and body["anomaly_score"] == stored["anomaly_score"]

    explanations = body["explanations"]
    if reason == "anomalous":
        [e] = explanations
        assert e["target"] == "anomaly" and e["contributions"][0]["deviation_sd"] is not None
    elif reason == "low_confidence":
        assert len(explanations) == 2 and explanations[0]["class"] == cls
    else:
        [e] = explanations
        assert e["target"] == "class" and e["class"] == cls and e["output_space"] == "probability"
        assert e["benign"] == (decision == "benign")
    assert all(len(e["contributions"]) == 6 for e in explanations)


def test_explain_uses_the_bundle_that_produced_the_results(client, user, completed, register_bundle):
    upload_id = completed()
    register_bundle(TINY_B)                                             # a newer model is active now
    assert client.app.state.models.ensure_current().bundle_id == TINY_B
    assert get(client, user, upload_id, "flows/1/explain").json()["bundle_id"] == TINY_A


def test_explain_when_the_producing_bundle_is_gone(client, user, completed, register_bundle, settings):
    upload_id = completed()
    register_bundle(TINY_B)
    client.app.state.models.ensure_current()
    shutil.rmtree(settings.model_store / TINY_A)
    r = get(client, user, upload_id, "flows/1/explain")
    assert r.status_code == 410 and TINY_A in r.json()["detail"]


def test_explain_when_the_version_is_unregistered(client, user, completed, db):
    upload_id = completed()
    db.execute(update(Upload).where(Upload.id == uuid.UUID(upload_id)).values(model_version_id=None))
    db.commit()
    assert get(client, user, upload_id, "flows/1/explain").status_code == 410


def test_explain_rows_that_dont_exist(client, user, completed):
    upload_id = completed()
    assert get(client, user, upload_id, f"flows/{N}/explain").status_code == 404
    assert get(client, user, upload_id, "flows/-1/explain").status_code == 422


def test_explain_reports_imputed_values_as_null(client, user, completed):
    upload_id = completed(flows_csv().replace(b"20000.0", b"Infinity", 1))   # benign flow's Flow Bytes/s
    body = get(client, user, upload_id, "flows/0/explain").json()
    values = {c["feature"]: c["value"] for e in body["explanations"] for c in e["contributions"]}
    assert values["Flow Bytes/s"] is None


# ── export ──────────────────────────────────────────────────

def read_export(response) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(response.content))


def test_export(client, user, completed):
    r = get(client, user, completed(), "export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == 'attachment; filename="flows-results.csv"'
    df = read_export(r)
    assert df["row"].tolist() == list(range(N))
    assert list(df.columns[:3]) == ["row", "Src IP", "Label"]
    assert list(zip(df["decision"], df["reason"], df["predicted_class"])) == EXPECTED * COPIES
    assert not set(df.columns) & set(FEATURES)


def test_export_with_features_and_filters(client, user, completed):
    upload_id = completed()
    df = read_export(get(client, user, upload_id, "export.csv", decision="known_attack", features="true"))
    assert len(df) == COPIES and (df["class_name"] == "DDoS").all()
    assert "Flow Duration" in df.columns and "Bwd PSH Flags" not in df.columns
    empty = get(client, user, upload_id, "export.csv", class_name="nothing")
    assert empty.status_code == 200 and len(read_export(empty)) == 0 and "decision" in read_export(empty).columns


def test_export_in_several_batches(client, user, completed, monkeypatch):
    from src.api.results import service
    monkeypatch.setattr(service, "EXPORT_BATCH_ROWS", 3)
    df = read_export(get(client, user, completed(), "export.csv"))
    assert df["row"].tolist() == list(range(N))                         # one header, no gaps


def test_export_filename_is_safe(client, user, active_bundle, run_queued):
    upload_id = upload_file(client, user, flows_csv(), filename="ngày 1; test.csv").json()["id"]
    run_queued()
    disposition = get(client, user, upload_id, "export.csv").headers["content-disposition"]
    assert disposition == 'attachment; filename="ng_y_1_test-results.csv"'   # ASCII only, nothing to break the header


# ── explainer cache ─────────────────────────────────────────

def test_explainer_cache(register_bundle, registry):
    register_bundle(TINY_A)
    register_bundle(TINY_B, activate=False)
    manager = ModelManager(registry)
    active = manager.ensure_current()
    cache = ExplainerCache(manager, size=1)

    a = cache.get(TINY_A)
    assert a.bundle is active and cache.get(TINY_A) is a                # the active bundle is reused, not reloaded
    b = cache.get(TINY_B)                                               # loaded from the store
    assert b.bundle.bundle_id == TINY_B and b.bundle is not active
    assert cache.get(TINY_A) is not a                                   # evicted (size 1), rebuilt
    with pytest.raises(BundleError):
        cache.get("no-such-bundle")
