"""
Shared fixtures.

The environment is fixed here, before anything reads the settings:
- .env and other IDS_* variables are ignored; rate limits are off; bcrypt runs at cost 4.
- Database: SQLite in a temp directory, or IDS_TEST_DATABASE_URL (the Compose "test" Postgres).
  It is migrated once with Alembic, and the `db` fixture empties every table before each test.
- Redis: IDS_TEST_REDIS_URL if set; tests that need Redis skip without it. Model events (pub/sub
  and loaded-version reports) are off unless a test turns them on.
- Model store and data directory: temp directories, emptied before each test that uses them.
  Tiny real bundles (tests/tiny_bundle.py) go in with `install_bundle` (files + registry.json, for
  the offline store) or `register_bundle` / `active_bundle` (files + model_versions, as the server).
- Celery doesn't run: uploads queued for processing are collected in `queued_jobs`, and
  `run_queued()` processes them in-process through the real task (retry and on_failure included).
- Email: `outbox` collects what the app would send; `verifying` also turns email verification on.
"""

import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

TMP = Path(tempfile.mkdtemp(prefix="ids-tests-"))
PROJECT_ROOT = Path(__file__).resolve().parents[1]

for _name in [n for n in os.environ if n.startswith("IDS_") and not n.startswith("IDS_TEST_")]:
    del os.environ[_name]
os.environ.update({
    "IDS_ENV": "test",
    "IDS_SECRET_KEY": "test-only-secret-key-that-is-long-enough-for-hs256",
    "IDS_DATABASE_URL": os.environ.get("IDS_TEST_DATABASE_URL") or f"sqlite:///{(TMP / 'test.db').as_posix()}",
    "IDS_REDIS_URL": os.environ.get("IDS_TEST_REDIS_URL") or "redis://127.0.0.1:6380/0",
    "IDS_MODEL_STORE": str(TMP / "model_store"),
    "IDS_DATA_DIR": str(TMP / "data"),
    "IDS_MODEL_POLL_SECONDS": "3600",           # tests switch models explicitly
    "IDS_RATE_LIMITS_ENABLED": "false",
    "IDS_MODEL_EVENTS_ENABLED": "false",
})

# Before any other import: celery_app reads the settings when it is imported
from src.api.settings import Settings, get_settings  # noqa: E402

Settings.model_config["env_file"] = None       # a developer's .env must not reach the tests

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from src.api.auth import security  # noqa: E402
from src.api.db.models import Base, ModelVersion, User  # noqa: E402
from src.api.db.session import get_engine, get_sessionmaker  # noqa: E402
from src.api.runtime.model_registry import ModelRegistry  # noqa: E402
from src.inference.bundle import load_bundle  # noqa: E402
from src.inference.store import ModelStore  # noqa: E402
from src.api.worker import tasks  # noqa: E402
from tests.helpers import PASSWORD  # noqa: E402
from tests.tiny_bundle import build_tiny_bundle  # noqa: E402

security.BCRYPT_ROUNDS = 4                     # cost 12 makes every signup/login ~0.25 s

TINY_A, TINY_B = "tiny-a", "tiny-b"


def pytest_configure(config):
    url = make_url(os.environ["IDS_DATABASE_URL"])
    if url.get_backend_name() != "sqlite" and "test" not in (url.database or ""):
        raise pytest.UsageError(f"IDS_TEST_DATABASE_URL must name a database containing 'test' "
                                f"(got '{url.database}'): the tests delete every row")


def pytest_unconfigure(config):
    get_engine().dispose()
    shutil.rmtree(TMP, ignore_errors=True)


# ── settings ────────────────────────────────────────────────

@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def override_settings(monkeypatch):
    """override_settings(rate_limits_enabled=True, ...): re-read settings with these IDS_* values."""
    def override(**values):
        for key, value in values.items():
            monkeypatch.setenv(f"IDS_{key.upper()}", str(value))
        get_settings.cache_clear()
    yield override
    get_settings.cache_clear()   # monkeypatch restores the environment right after this


# ── database ────────────────────────────────────────────────

@pytest.fixture(scope="session")
def database():
    """The test database, migrated once with Alembic (which also exercises the migrations)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config()   # no ini file: alembic.ini's logging setup would silence the app's loggers
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    command.upgrade(cfg, "head")
    return get_engine()


@pytest.fixture
def db(database):
    """A session on an empty database."""
    with database.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    with get_sessionmaker()() as session:
        yield session


@pytest.fixture
def make_user(db):
    def make(email="alice@example.com", username=None, password=PASSWORD, role="user", is_active=True,
             verified=True) -> User:
        user = User(email=email, username=username or email.split("@")[0],
                    password_hash=security.hash_password(password), role=role, is_active=is_active,
                    email_verified_at=datetime.now(timezone.utc) if verified else None)
        db.add(user)
        db.commit()
        return user
    return make


@pytest.fixture
def user(make_user):
    return make_user()


@pytest.fixture
def admin(make_user):
    return make_user("root@example.com", role="admin")


# ── model store ─────────────────────────────────────────────

@pytest.fixture(scope="session")
def tiny_bundles(tmp_path_factory):
    """Two tiny bundles (different seeds), built once; copy them into a store before use."""
    root = tmp_path_factory.mktemp("bundles")
    return {TINY_A: build_tiny_bundle(root, TINY_A, seed=0), TINY_B: build_tiny_bundle(root, TINY_B, seed=1)}


@pytest.fixture(scope="session")
def tiny_bundle(tiny_bundles):
    """TINY_A, loaded and verified once; treat it as read-only."""
    return load_bundle(tiny_bundles[TINY_A])


@pytest.fixture
def model_store(settings) -> ModelStore:
    """The app's (empty) model store; also empties the data directory."""
    for path in (settings.model_store, settings.data_dir):
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True)
    return ModelStore(settings.model_store)


@pytest.fixture
def install_bundle(model_store, tiny_bundles):
    def install(bundle_id=TINY_A, activate=True) -> Path:
        path = shutil.copytree(tiny_bundles[bundle_id], model_store.root / bundle_id)
        if activate:
            model_store.activate(bundle_id, actor="pytest")
        return path
    return install


# ── email ───────────────────────────────────────────────────

@pytest.fixture
def outbox(monkeypatch) -> list:
    """Emails the app sends (src/api/mail.Message), collected instead of sent."""
    from src.api import mail
    sent = []
    monkeypatch.setattr(mail, "send", sent.append)
    return sent


@pytest.fixture
def verifying(override_settings, outbox) -> list:
    """IDS_EMAIL_VERIFICATION on (with SMTP configured, so no warning); returns the outbox."""
    override_settings(email_verification=True, mail_backend="smtp", smtp_host="smtp.test")
    return outbox


# ── Celery ──────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def queued_jobs(monkeypatch) -> list[str]:
    """Upload ids the API queued for processing (instead of sending them to a broker)."""
    jobs = []
    monkeypatch.setattr(tasks, "enqueue_upload", lambda upload_id: jobs.append(str(upload_id)))
    return jobs


@pytest.fixture
def run_queued(queued_jobs, monkeypatch):
    """run_queued() processes the queued uploads as a worker would and returns each task's result."""
    monkeypatch.setattr(tasks, "_models", None)        # a fresh worker process

    def run() -> list:
        results = [tasks.process_upload.apply(args=[job]).result for job in queued_jobs]
        queued_jobs.clear()
        return results
    return run


# ── app ─────────────────────────────────────────────────────

@pytest.fixture
def app(db, model_store):
    from src.api.main import create_app
    return create_app()


@pytest.fixture
def client(app):
    """Runs the app's lifespan. https, or the Secure cookies would not be sent back."""
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def registry(settings) -> ModelRegistry:
    """The server's model registry (model_versions), as the app builds it."""
    return ModelRegistry(settings.model_store, get_sessionmaker())


@pytest.fixture
def register_bundle(db, install_bundle, registry):
    """Copy a tiny bundle into the store and register it (a rescan); activate=True also activates it."""
    def register(bundle_id=TINY_A, activate=True) -> ModelVersion:
        install_bundle(bundle_id, activate=False)
        registry.rescan(db, actor_id=None)
        version = db.scalar(select(ModelVersion).where(ModelVersion.bundle_id == bundle_id))
        if activate:
            registry.activate(db, version.id, actor_id=None)
        return version
    return register


@pytest.fixture
def active_bundle(client, register_bundle):
    """TINY_A activated in the database and loaded by the running app, as after an admin switch."""
    register_bundle(TINY_A)
    return client.app.state.models.ensure_current()
