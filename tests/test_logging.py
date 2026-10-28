"""
Structured logs (src/api/logs.py): the access line per request, request and task ids on records,
both formats; and the API's Cache-Control default.
"""

import json
import logging

import pytest

from src.api import logs
from src.api.worker import tasks
from tests.helpers import API, bearer, flows_csv, upload_file


class Collect(logging.Handler):
    """The JSON lines the containers would print."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.setFormatter(logs.JsonFormatter())
        self.addFilter(logs.ContextFilter())
        self.lines = []

    def emit(self, record):
        self.lines.append(json.loads(self.format(record)))

    def named(self, logger):
        return [line for line in self.lines if line["logger"] == logger]


@pytest.fixture
def collect():
    handler, root = Collect(), logging.getLogger()
    level = root.level
    root.addHandler(handler)
    yield handler
    root.removeHandler(handler)
    root.setLevel(level)


def test_one_access_line_per_request(client, user, collect):
    r = client.get(f"{API}/auth/me", headers=bearer(user))
    [line] = collect.named("ids.access")
    assert line["level"] == "INFO"
    assert line["message"] == f"GET {API}/auth/me 200"
    assert line["request_id"] == r.headers["X-Request-ID"]
    assert (line["method"], line["path"], line["status"], line["user_id"]) == ("GET", f"{API}/auth/me", 200, user.id)
    assert line["duration_ms"] >= 0 and line["client"]


def test_failed_and_anonymous_requests_are_logged_too(client, collect):
    client.get(f"{API}/auth/me")
    [line] = collect.named("ids.access")
    assert line["status"] == 401 and "user_id" not in line


def test_health_checks_are_debug_only(client, collect):
    client.get(f"{API}/healthz")
    assert collect.named("ids.access") == []          # INFO is the configured level
    logging.getLogger().setLevel(logging.DEBUG)
    client.get(f"{API}/healthz")
    assert [line["level"] for line in collect.named("ids.access")] == ["DEBUG"]


def test_records_made_during_a_request_carry_its_id(client, user, active_bundle, collect, monkeypatch):
    def broker_down(upload_id):
        raise ConnectionError("broker down")

    monkeypatch.setattr(tasks, "enqueue_upload", broker_down)
    r = upload_file(client, user, flows_csv())
    assert r.status_code == 503
    [line] = collect.named("src.api.uploads.router")
    assert line["level"] == "ERROR" and line["message"].startswith("Could not queue upload")
    assert line["request_id"] == r.headers["X-Request-ID"]
    assert "ConnectionError: broker down" in line["exception"]


def test_records_made_by_a_task_carry_its_id(client, user, active_bundle, run_queued, collect):
    assert upload_file(client, user, flows_csv()).status_code == 201
    collect.lines.clear()
    assert run_queued() == ["completed"]
    [line] = [x for x in collect.named("src.api.uploads.processing") if "flows with" in x["message"]]
    [done] = collect.named("celery.app.trace")
    assert line["task_name"] == "ids.process_upload"
    assert line["task_id"] == done["data"]["id"]
    assert "request_id" not in line
    assert logs.task.get() is None                     # reset after the task


def test_text_format():
    formatter, record = logs.TextFormatter(), logging.LogRecord("ids.access", logging.INFO, "", 0,
                                                                "GET /x 200", None, None)
    record.status, record.request_id = 200, "abc"
    assert formatter.format(record).endswith("INFO    ids.access: GET /x 200 [status=200 request_id=abc]")


def test_configure_logging_is_idempotent():
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        logs.configure_logging("json", "WARNING")
        logs.configure_logging("json", "WARNING")
        ours = [h for h in root.handlers if getattr(h, "ids_handler", False)]
        assert len(ours) == 1 and isinstance(ours[0].formatter, logs.JsonFormatter)
        assert root.level == logging.WARNING
        assert logging.getLogger("uvicorn.access").disabled
    finally:
        root.handlers = before


def test_api_responses_are_not_cached(client, user):
    assert client.get(f"{API}/healthz").headers["Cache-Control"] == "no-store"
    assert client.get(f"{API}/auth/me", headers=bearer(user)).headers["Cache-Control"] == "no-store"
