"""
AI-IDS web API: app factory, middleware, routers, lifespan.
"""

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response

from src.api import health, logs, metrics
from src.api.admin import router as admin
from src.api.auth import router as auth
from src.api.inference import router as inference
from src.api.results import router as results
from src.api.runtime.explainers import ExplainerCache
from src.api.runtime.model_manager import ModelRuntime, create_model_manager
from src.api.settings import get_settings
from src.api.uploads import router as uploads

API_PREFIX = "/api/v1"
_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
# Polled every few seconds by healthchecks and Prometheus: logged at DEBUG only
QUIET_PATHS = {f"{API_PREFIX}/healthz", f"{API_PREFIX}/readyz", "/metrics"}

access_log = logging.getLogger("ids.access")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.started_at = time.time()
    app.state.models = create_model_manager(settings)
    app.state.model_runtime = ModelRuntime(app.state.models, settings, kind="api", listen=True)
    app.state.model_runtime.start()  # picks up model switches
    app.state.explainers = ExplainerCache(app.state.models)
    yield
    app.state.model_runtime.stop()


def create_app() -> FastAPI:
    # Here rather than in the lifespan: each uvicorn worker imports the app before it logs its start
    settings = get_settings()
    logs.configure_logging(settings.log_format, settings.log_level)
    app = FastAPI(
        title="AI-IDS",
        version="3.0.0",
        description="Network intrusion detection: uploads, open-set predictions, explanations, admin.",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        # Keep a well-formed incoming id (e.g. from the proxy), otherwise make one
        incoming = request.headers.get("X-Request-ID", "")
        rid = incoming if _REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        request.state.request_id = rid
        token = logs.request_id.set(rid)        # every log record of this request carries it
        start, status = time.perf_counter(), 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            # Responses hold one user's data; never let a browser or Cloudflare keep a copy
            # (Cloudflare caches *.csv by default, export.csv included)
            response.headers.setdefault("Cache-Control", "no-store")
            return response
        except Exception:
            # Logged here too, because uvicorn's own log of it comes without the request id
            logging.getLogger("ids.error").exception("Unhandled error in %s %s", request.method, request.url.path)
            raise
        finally:
            path = request.url.path
            access_log.log(logging.DEBUG if path in QUIET_PATHS else logging.INFO,
                           "%s %s %s", request.method, path, status, extra={
                               "method": request.method, "path": path, "status": status,
                               "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                               "client": request.client.host if request.client else None,
                               "user_id": getattr(request.state, "user_id", None)})
            logs.request_id.reset(token)

    @app.middleware("http")
    async def http_metrics(request: Request, call_next):
        start, status = time.perf_counter(), 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            metrics.observe(request.method, metrics.route_label(request.scope), status, time.perf_counter() - start)

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics():
        """Outside /api: Caddy doesn't route it, so only the Compose network can scrape it."""
        if not get_settings().metrics_enabled:
            raise HTTPException(status_code=404)
        body, content_type = metrics.render()
        return Response(body, media_type=content_type)

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(health.router)
    api.include_router(auth.router)
    api.include_router(inference.router)
    api.include_router(uploads.router)
    api.include_router(results.router)
    api.include_router(admin.router)
    app.include_router(api)
    return app


app = create_app()
