"""
GET /admin/server (host, database, Redis, queue, uploads, model, warnings) and GET /metrics.
"""

import os
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import redis
from prometheus_client import REGISTRY

from src.api import health, metrics
from src.api.admin import status
from src.api.db.models import Upload
from src.api.runtime import model_events
from src.api.runtime.system_stats import gpu_stats, system_stats
from tests.conftest import TINY_A, TINY_B
from tests.helpers import API, bearer, flows_csv, upload_file

SERVER = f"{API}/admin/server"
needs_redis = pytest.mark.skipif(not os.environ.get("IDS_TEST_REDIS_URL"), reason="needs IDS_TEST_REDIS_URL")


def host(disk_percent=40.0, ram_percent=50.0) -> dict:
    return {"cpu_percent": 12.5, "ram_percent": ram_percent, "ram_used_mb": 4096, "ram_total_mb": 8192,
            "disk_percent": disk_percent, "disk_free_gb": 100.0, "disk_total_gb": 200.0, "gpus": []}


@pytest.fixture
def healthy(monkeypatch):
    """Host, Redis and queue as on a healthy server (no real Redis or worker needed)."""
    state = {"queue": {"ok": True, "queued": 3, "unacknowledged": 1, "workers": ["celery@w1"]}}
    monkeypatch.setattr(status, "system_stats", lambda data_dir: host(state.get("disk", 40.0), state.get("ram", 50.0)))
    monkeypatch.setattr(health, "_check_redis", lambda url: {"ok": True})
    monkeypatch.setattr(status, "queue_status", lambda url: state["queue"])
    return state


def server(client, admin):
    r = client.get(SERVER, headers=bearer(admin))
    assert r.status_code == 200, r.text
    return r.json()


# ── /admin/server ───────────────────────────────────────────

def test_admin_only(client, user):
    assert client.get(SERVER).status_code == 401
    assert client.get(SERVER, headers=bearer(user)).status_code == 403


def test_healthy_server(client, admin, user, healthy, active_bundle, run_queued):
    upload_file(client, user, flows_csv())
    run_queued()
    body = server(client, admin)
    assert body["warnings"] == []
    assert body["api"]["version"] == client.app.version and body["api"]["uptime_s"] >= 0
    assert body["api"]["process"] == model_events.process_id()
    assert body["system"]["disk_warning"] is False and body["system"]["cpu_percent"] == 12.5
    assert body["database"] == {"ok": True, "error": None} and body["redis"]["ok"] is True
    assert body["queue"] == {"ok": True, "error": None, "queued": 3, "unacknowledged": 1, "workers": ["celery@w1"]}
    assert body["uploads"] == {"by_status": {"completed": 1}, "failed_last_24h": 0, "stuck": 0}
    model = body["model"]
    assert model["loaded"] == model["active_in_store"] == TINY_A and model["lagging_processes"] is None


@pytest.mark.parametrize("disk, threshold, warned", [(90.0, 85, True), (90.0, 95, False), (85.0, 85, True)])
def test_disk_warning(client, admin, healthy, active_bundle, override_settings, disk, threshold, warned):
    healthy["disk"] = disk
    override_settings(disk_warning_percent=threshold)
    body = server(client, admin)
    assert body["system"]["disk_warning"] is warned
    assert any("data volume" in w for w in body["warnings"]) is warned


@pytest.mark.parametrize("ram, warned", [(89.9, False), (96.1, True)])
def test_memory_warning(client, admin, healthy, active_bundle, ram, warned):
    healthy["ram"] = ram
    assert any("Memory is" in w for w in server(client, admin)["warnings"]) is warned


def test_redis_down_skips_the_queue_checks(client, admin, healthy, active_bundle, monkeypatch):
    monkeypatch.setattr(health, "_check_redis", lambda url: {"ok": False, "error": "ConnectionError"})
    monkeypatch.setattr(status, "queue_status", lambda url: pytest.fail("queue checked without Redis"))
    body = server(client, admin)
    assert body["redis"] == {"ok": False, "error": "ConnectionError"}
    assert body["queue"]["ok"] is False and body["queue"]["workers"] is None
    assert any("Redis is unreachable" in w for w in body["warnings"])


def test_no_worker_answered(client, admin, healthy, active_bundle):
    healthy["queue"] = {"ok": True, "queued": 5, "unacknowledged": 0, "workers": []}
    assert any("No Celery worker" in w for w in server(client, admin)["warnings"])


def test_queue_check_failure_is_reported(client, admin, healthy, active_bundle, monkeypatch):
    def broken(url):
        raise redis.ResponseError("WRONGTYPE")
    monkeypatch.setattr(status, "queue_status", broken)
    assert server(client, admin)["queue"] == {"ok": False, "error": "ResponseError", "queued": None,
                                              "unacknowledged": None, "workers": None}


def test_model_warnings(client, admin, healthy, register_bundle):
    body = server(client, admin)
    assert body["model"]["active_in_store"] is None and any("No model is active" in w for w in body["warnings"])

    register_bundle(TINY_A)
    client.app.state.models.ensure_current()
    register_bundle(TINY_B)                                  # activated, not yet picked up by this process
    body = server(client, admin)
    assert any(f"serves {TINY_A}, not the active {TINY_B}" in w for w in body["warnings"])


def test_failed_model_load_is_reported(client, admin, healthy, active_bundle, monkeypatch):
    monkeypatch.setattr(client.app.state.models, "_last_error", "2026-10-25T10:00:00 tiny-b: hash mismatch")
    assert any("last model load failed" in w for w in server(client, admin)["warnings"])


def test_upload_counts_and_stuck_uploads(client, admin, user, healthy, active_bundle, db):
    now = datetime.now(timezone.utc)
    for status_, started, finished in [("predicting", now - timedelta(minutes=40), None),   # stuck
                                       ("predicting", now - timedelta(minutes=5), None),
                                       ("failed", now - timedelta(hours=2), now - timedelta(hours=2)),
                                       ("failed", now - timedelta(days=3), now - timedelta(days=3))]:
        db.add(Upload(id=uuid.uuid4(), user_id=user.id, original_filename="f.csv", stored_path="uploads/x.csv",
                      file_type="csv", size_bytes=1, sha256="0" * 64, status=status_, started_at=started,
                      finished_at=finished))
    db.commit()
    body = server(client, admin)
    assert body["uploads"] == {"by_status": {"predicting": 2, "failed": 2}, "failed_last_24h": 1, "stuck": 1}
    assert any("1 upload(s) have been processing for over 35 minutes" in w for w in body["warnings"])


def test_database_down(client, admin, healthy, active_bundle, monkeypatch):
    monkeypatch.setattr(health, "_check_database", lambda: {"ok": False, "error": "OperationalError"})
    body = server(client, admin)
    assert body["uploads"] is None and "The database is unreachable" in body["warnings"]


@needs_redis
def test_real_queue_and_process_reports(client, admin, active_bundle, override_settings, monkeypatch):
    url = os.environ["IDS_TEST_REDIS_URL"]
    override_settings(redis_url=url, model_events_enabled=True)
    monkeypatch.setattr(status, "system_stats", lambda data_dir: host())
    r = redis.Redis.from_url(url)
    r.delete(status.CELERY_QUEUE)
    r.lpush(status.CELERY_QUEUE, "a", "b")
    model_events.report_loaded(url, "worker", {"loaded": TINY_B, "loaded_at": None, "active_in_store": TINY_A,
                                               "last_error": None}, ttl_s=60)
    try:
        body = server(client, admin)
        assert body["queue"]["ok"] is True and body["queue"]["queued"] == 2
        assert body["queue"]["workers"] == []                # nothing answers the ping
        assert body["model"]["lagging_processes"] == 1
    finally:
        r.delete(status.CELERY_QUEUE)
        model_events.clear_report(url)


# ── host stats ──────────────────────────────────────────────

def test_system_stats(tmp_path):
    stats = system_stats(tmp_path / "data")
    assert 0 <= stats["cpu_percent"] <= 100 and 0 < stats["ram_percent"] <= 100
    assert 0 < stats["disk_percent"] <= 100 and stats["disk_total_gb"] >= stats["disk_free_gb"] > 0
    assert isinstance(stats["gpus"], list)


def test_gpu_stats_with_a_gpu(monkeypatch):
    fake = types.SimpleNamespace(
        NVMLError=Exception, nvmlInit=lambda: None, nvmlShutdown=lambda: None, nvmlDeviceGetCount=lambda: 1,
        nvmlDeviceGetHandleByIndex=lambda i: i, nvmlDeviceGetName=lambda h: b"NVIDIA RTX 4060",
        nvmlDeviceGetMemoryInfo=lambda h: types.SimpleNamespace(used=2 * 2**30, total=8 * 2**30),
        nvmlDeviceGetUtilizationRates=lambda h: types.SimpleNamespace(gpu=37))
    monkeypatch.setitem(sys.modules, "pynvml", fake)
    assert gpu_stats() == [{"name": "NVIDIA RTX 4060", "utilization_percent": 37,
                            "memory_used_mb": 2048, "memory_total_mb": 8192}]


def test_gpu_stats_without_a_driver(monkeypatch):
    def no_driver():
        raise Exception("NVML Shared Library Not Found")
    monkeypatch.setitem(sys.modules, "pynvml", types.SimpleNamespace(NVMLError=Exception, nvmlInit=no_driver))
    assert gpu_stats() == []


# ── /metrics ────────────────────────────────────────────────

def requests_count(route, status_code, method="GET") -> float:
    return REGISTRY.get_sample_value("ids_http_requests_total",
                                     {"method": method, "route": route, "status": str(status_code)}) or 0.0


def test_http_metrics_use_route_templates(client, user, active_bundle):
    route = "/api/v1/uploads/{upload_id}"
    before = requests_count(route, 404)
    for _ in range(2):
        client.get(f"{API}/uploads/{uuid.uuid4()}", headers=bearer(user))
    unmatched = requests_count("unmatched", 404)
    client.get("/wp-login.php")
    assert requests_count(route, 404) == before + 2           # two ids, one series
    assert requests_count("unmatched", 404) == unmatched + 1


def test_broken_metrics_never_fail_requests(client, monkeypatch, caplog):
    # Found running the stack: an unwritable PROMETHEUS_MULTIPROC_DIR turned every request into a 500
    def unwritable(*labels):
        raise PermissionError("[Errno 13] Permission denied: '/tmp/prometheus/counter_8.db'")
    monkeypatch.setattr(metrics.REQUESTS, "labels", unwritable)
    monkeypatch.setattr(metrics, "_observe_failed", False)
    assert client.get(f"{API}/healthz").status_code == 200
    assert client.get(f"{API}/healthz").status_code == 200
    assert caplog.text.count("Recording HTTP metrics failed") == 1      # logged once, not per request


def test_metrics_endpoint(client, user, admin, active_bundle, run_queued):
    upload_file(client, user, flows_csv())
    run_queued()
    r = client.get("/metrics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    text = r.text
    assert 'ids_http_requests_total{method="POST",route="/api/v1/uploads",status="201"}' in text
    assert 'ids_uploads{status="completed"} 1.0' in text
    assert "ids_processed_flows_total 4.0" in text
    assert 'ids_users{active="true",role="admin"} 1.0' in text
    assert f'ids_active_model_info{{bundle_id="{TINY_A}"}} 1.0' in text
    assert 'ids_dependency_up{name="database"} 1.0' in text


def test_metrics_are_not_under_the_api_prefix(client, override_settings):
    assert client.get(f"{API}/metrics").status_code == 404     # Caddy only forwards /api/*
    override_settings(metrics_enabled=False)
    assert client.get("/metrics").status_code == 404


@pytest.mark.parametrize("path, template, expected", [
    ("/api/v1/uploads/5/flows/1/explain", "/uploads/{upload_id}/flows/{row}/explain",
     "/api/v1/uploads/{upload_id}/flows/{row}/explain"),
    ("/api/v1/healthz", "/healthz", "/api/v1/healthz"),
    ("/metrics", "/metrics", "/metrics"),
])
def test_route_label(path, template, expected):
    assert metrics.route_label({"path": path, "route": types.SimpleNamespace(path=template)}) == expected
    assert metrics.route_label({"path": path}) == "unmatched"
