"""
AI-IDS web API: app factory, middleware, routers, lifespan.
"""

import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response

from src.api import health, metrics
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
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

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
