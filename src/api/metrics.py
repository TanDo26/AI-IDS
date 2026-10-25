"""
Prometheus metrics at GET /metrics: outside /api, so Caddy never exposes it; scrape api:8000 inside
the Compose network.

- **HTTP** (counted by the middleware in main.py):
  - `ids_http_requests_total{method,route,status}`;
  - `ids_http_request_duration_seconds{method,route}`, time to the response headers.
  The route is the matched path template, or "unmatched", so scans can't grow the label set.
- **State**, read from the database and Redis at scrape time, so it is the same whichever process answers:
  - `ids_uploads{status}`;
  - `ids_uploaded_bytes_total`, `ids_processed_flows_total` (deleted uploads included);
  - `ids_users{role,active}`;
  - `ids_active_model_info{bundle_id}`;
  - `ids_queue_length`;
  - `ids_dependency_up{name}`.

With several uvicorn workers, set PROMETHEUS_MULTIPROC_DIR to an empty directory (Compose: a tmpfs)
before start, so the HTTP metrics of all workers are summed.
"""

import os

import redis
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from prometheus_client.multiprocess import MultiProcessCollector
from sqlalchemy import func, select

from src.api.admin.status import CELERY_QUEUE
from src.api.db.models import ModelVersion, Upload, User
from src.api.db.session import get_sessionmaker
from src.api.settings import get_settings

REQUESTS = Counter("ids_http_requests", "HTTP requests", ["method", "route", "status"])
LATENCY = Histogram("ids_http_request_duration_seconds", "Time to the response headers", ["method", "route"],
                    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30))


def route_label(scope) -> str:
    """The matched path template, prefix included, e.g. /api/v1/uploads/{upload_id}/flows/{row}/explain.

    The route object only knows its own template (routers are included lazily), so the prefix is taken
    from the real path: path parameters never contain '/', so the template covers its last segments.
    """
    template = getattr(scope.get("route"), "path", None)
    if template is None:
        return "unmatched"
    parts = scope["path"].split("/")
    return "/".join(parts[: len(parts) - template.count("/")]) + template


def observe(method: str, route: str, status: int, seconds: float) -> None:
    REQUESTS.labels(method, route, str(status)).inc()
    LATENCY.labels(method, route).observe(seconds)


class StateCollector:
    """Database and Redis state, collected at each scrape."""

    def collect(self):
        up = GaugeMetricFamily("ids_dependency_up", "1 when the dependency answered this scrape", labels=["name"])
        try:
            with get_sessionmaker()() as db:
                uploads = GaugeMetricFamily("ids_uploads", "Uploads not deleted, by status", labels=["status"])
                for status, count in db.execute(select(Upload.status, func.count())
                                                .where(Upload.deleted_at.is_(None)).group_by(Upload.status)):
                    uploads.add_metric([status], count)
                yield uploads
                size, flows = db.execute(select(func.coalesce(func.sum(Upload.size_bytes), 0),
                                                func.coalesce(func.sum(Upload.n_flows), 0))).one()
                yield CounterMetricFamily("ids_uploaded_bytes", "Bytes uploaded, deleted uploads included", value=size)
                yield CounterMetricFamily("ids_processed_flows", "Flows predicted from uploads", value=flows)
                users = GaugeMetricFamily("ids_users", "User accounts", labels=["role", "active"])
                for role, active, count in db.execute(select(User.role, User.is_active, func.count())
                                                      .group_by(User.role, User.is_active)):
                    users.add_metric([role, str(bool(active)).lower()], count)
                yield users
                model = GaugeMetricFamily("ids_active_model_info", "The active model bundle", labels=["bundle_id"])
                active = db.scalar(select(ModelVersion.bundle_id).where(ModelVersion.status == "active"))
                if active:
                    model.add_metric([active], 1)
                yield model
            up.add_metric(["database"], 1)
        except Exception:
            up.add_metric(["database"], 0)
        try:
            client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
            yield GaugeMetricFamily("ids_queue_length", "Tasks waiting in the Celery queue",
                                    value=client.llen(CELERY_QUEUE))
            up.add_metric(["redis"], 1)
        except redis.RedisError:
            up.add_metric(["redis"], 0)
        yield up


def render() -> tuple[bytes, str]:
    if "PROMETHEUS_MULTIPROC_DIR" in os.environ:
        http = CollectorRegistry()
        MultiProcessCollector(http)      # every worker's files; per-process collectors make no sense here
    else:
        http = REGISTRY                  # this process: HTTP metrics + process/platform/GC
    state = CollectorRegistry()
    state.register(StateCollector())
    return generate_latest(http) + generate_latest(state), CONTENT_TYPE_LATEST
