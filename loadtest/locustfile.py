"""
Load test of the running app stack (plan §F.6), through Caddy like a browser or script would:

    POST /api/v1/predict                          one flow                  target p95 < 50 ms
    GET  /api/v1/uploads/{id}/flows/{row}/explain one flow's explanation    target p95 < 300 ms
    a capture upload, from upload done to results ready (LOADTEST_CAPTURE)  target < 2 min

    docker compose --profile app --profile loadtest run --rm locust        # README "Load test"

Inputs (environment):
    LOADTEST_EMAIL / LOADTEST_PASSWORD   an existing account; any user may predict
    LOADTEST_FLOWS                       CSV of flows for the active model (scripts/make_sample_upload.py)
    LOADTEST_CAPTURE                     optional pcap / pcapng to time before the load starts

Before the simulated users start: one sign-in (its Bearer token is shared, since sign-in allows
5 per minute per address), the capture if given, and one upload of the CSV, whose rows are then
explained. The run fails (exit code 1) when a target is missed or a request fails.
`--tags predict` or `--tags explain` runs one kind of request only.
"""

import csv
import os
import random
import time
from datetime import datetime

import requests
from locust import HttpUser, between, events, tag, task

API = "/api/v1"
PREDICT, EXPLAIN = "POST /predict", "GET /uploads/{id}/flows/{row}/explain"
TARGETS_MS = {("POST", PREDICT): 50, ("GET", EXPLAIN): 300}
CAPTURE_TARGET_S = 120
state = {}


def _number(value: str):
    try:
        return float(value)
    except ValueError:
        return value                  # metadata (addresses, timestamp) stays text


def _upload(host, headers, path) -> dict:
    """Upload a file, wait until it is processed, return the upload."""
    with open(path, "rb") as f:
        r = requests.post(f"{host}{API}/uploads", headers=headers, timeout=600,
                          files={"file": (os.path.basename(path), f, "application/octet-stream")})
    r.raise_for_status()
    upload_id, deadline = r.json()["id"], time.monotonic() + 600
    while time.monotonic() < deadline:
        upload = requests.get(f"{host}{API}/uploads/{upload_id}", headers=headers, timeout=10).json()
        if upload["status"] in ("completed", "failed"):
            if upload["status"] == "failed":
                raise RuntimeError(f"{path}: processing failed: {upload['error']}")
            return upload
        time.sleep(1)
    raise RuntimeError(f"{path}: not processed within 10 minutes")


@events.test_start.add_listener
def _setup(environment, **_):
    host = environment.host
    r = requests.post(f"{host}{API}/auth/login", timeout=10,
                      json={"email": os.environ["LOADTEST_EMAIL"], "password": os.environ["LOADTEST_PASSWORD"]})
    r.raise_for_status()
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    capture = os.environ.get("LOADTEST_CAPTURE")
    if capture:
        upload = _upload(host, headers, capture)
        took = (datetime.fromisoformat(upload["finished_at"]) - datetime.fromisoformat(upload["created_at"]))
        state["capture"] = (os.path.basename(capture), upload["size_bytes"], upload["n_flows"],
                            took.total_seconds(), upload["processing_ms"] / 1000)

    flows_csv = os.environ["LOADTEST_FLOWS"]
    with open(flows_csv, encoding="utf-8-sig", newline="") as f:
        flows = [{k: _number(v) for k, v in row.items()} for row in csv.DictReader(f)]
    upload = _upload(host, headers, flows_csv)
    state.update(headers=headers, flows=flows, upload=upload["id"], rows=upload["n_flows"])


class ApiUser(HttpUser):
    wait_time = between(0.5, 1.5)

    @tag("predict")
    @task(5)
    def predict(self):
        self.client.post(f"{API}/predict", json={"features": random.choice(state["flows"])},
                         headers=state["headers"], name=PREDICT)

    @tag("explain")
    @task(1)
    def explain(self):
        row = random.randrange(state["rows"])
        self.client.get(f"{API}/uploads/{state['upload']}/flows/{row}/explain",
                        headers=state["headers"], name=EXPLAIN)


@events.quitting.add_listener
def _check_targets(environment, **_):
    stats, ok = environment.stats, True
    print("\nTargets (plan §F.6)")
    for (method, name), target in TARGETS_MS.items():
        entry = stats.get(name, method)
        if not entry.num_requests:
            continue                  # left out with --tags
        p95 = entry.get_response_time_percentile(0.95)
        met = p95 < target and entry.num_failures == 0
        ok &= met
        print(f"  {name:<40} p95 {p95} ms (target < {target} ms), {entry.num_requests} requests, "
              f"{entry.num_failures} failed  {'ok' if met else 'MISSED'}")
    if "capture" in state:
        name, size, flows, took, processing = state["capture"]
        met = took < CAPTURE_TARGET_S
        ok &= met
        print(f"  capture {name} ({size / 1e6:.0f} MB, {flows} flows): results {took:.1f} s after the upload "
              f"({processing:.1f} s processing; target < {CAPTURE_TARGET_S} s)  {'ok' if met else 'MISSED'}")
    if not ok or stats.total.num_failures:
        environment.process_exit_code = 1
