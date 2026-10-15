"""
Schema: the Alembic migrations match the ORM models, and the database enforces its rules.
"""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from src.api.db.models import AuditLog, Base, ModelVersion, PredictionSummary, Upload, User


def test_migrations_match_models(database):
    with database.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == [], "models changed without a migration: run alembic revision --autogenerate"


def _version(bundle_id, status):
    return ModelVersion(bundle_id=bundle_id, path=f"/models/{bundle_id}", status=status, manifest={})


def test_only_one_active_model_version(db):
    db.add_all([_version("a", "active"), _version("b", "available"), _version("c", "available")])
    db.commit()
    db.add(_version("d", "active"))
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize("model, field, value", [
    (User, "role", "root"),
    (ModelVersion, "status", "deleted"),
])
def test_check_constraints(db, model, field, value):
    if model is User:
        row = User(email="x@example.com", username="x", password_hash="h", role=value)
    else:
        row = _version("x", value)
    db.add(row)
    with pytest.raises(IntegrityError):
        db.commit()


def test_emails_are_unique(db, user):
    db.add(User(email=user.email, username="someone-else", password_hash="h"))
    with pytest.raises(IntegrityError):
        db.commit()


def _upload(user_id):
    return Upload(user_id=user_id, original_filename="flows.csv", stored_path="/data/x.csv",
                  file_type="csv", size_bytes=10, sha256="0" * 64)


def test_foreign_keys_are_enforced(db):
    db.add(_upload(user_id=12345))
    with pytest.raises(IntegrityError):
        db.commit()


def test_deleting_an_upload_deletes_its_summary(db, user):
    upload = _upload(user.id)
    db.add(upload)
    db.flush()
    db.add(PredictionSummary(upload_id=upload.id, n_benign=1, n_known_attack=0, n_unknown=0,
                             attack_breakdown={}, inference_ms=1.0))
    db.commit()
    db.expunge_all()   # the database must cascade, not the ORM's identity map

    db.execute(delete(Upload))
    db.commit()
    assert db.scalar(select(func.count()).select_from(PredictionSummary)) == 0


def test_deleting_a_user_keeps_their_audit_rows(db, admin):
    db.add(AuditLog(actor_id=admin.id, action="user.deactivate", target_type="user", target_id="1", details={}))
    db.commit()
    db.execute(delete(User))
    db.commit()
    assert db.scalar(select(AuditLog.actor_id)) is None
