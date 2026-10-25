"""
Admin: users, usage, all uploads, the audit log. (Model versions: src/api/runtime/model_registry.py.)

Usage is computed from `uploads`, deleted uploads included: users can delete their files, not
the record of having sent them. Days are UTC.
"""

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.orm import Session

from src.api.auth.service import revoke_all_sessions
from src.api.db.models import AuditLog, Upload, User
from src.api.settings import Settings
from src.api.uploads.processing import RESULTS_FILE
from src.api.uploads.service import results_dir

DEFAULT_DAILY_DAYS = 30
MAX_DAILY_DAYS = 366


class AdminError(Exception):
    """Maps to an HTTP error: status + message."""

    def __init__(self, status: int, message: str):
        self.status, self.message = status, message
        super().__init__(message)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _utc_day(dt: datetime) -> date:
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).date()


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def _page(db: Session, query: Select, page: int, size: int) -> tuple[list, int]:
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    return list(db.execute(query.offset((page - 1) * size).limit(size)).all()), total


# ── users ───────────────────────────────────────────────────

def list_users(db: Session, q: str | None, role: str | None, active: bool | None,
               page: int, size: int) -> tuple[list[User], int]:
    query = select(User)
    if q:
        query = query.where(or_(User.email.icontains(q, autoescape=True), User.username.icontains(q, autoescape=True)))
    if role is not None:
        query = query.where(User.role == role)
    if active is not None:
        query = query.where(User.is_active.is_(active))
    rows, total = _page(db, query.order_by(User.created_at.desc(), User.id.desc()), page, size)
    return [row[0] for row in rows], total


def update_user(db: Session, actor: User, user_id: int, is_active: bool | None = None,
                role: str | None = None) -> User:
    """Activate/deactivate and promote/demote, each change audited. Deactivation ends the user's sessions."""
    target = db.get(User, user_id)
    if target is None:
        raise AdminError(404, f"No user {user_id}")
    changes = [(field, getattr(target, field), new) for field, new in (("role", role), ("is_active", is_active))
               if new is not None and new != getattr(target, field)]
    if not changes:
        return target
    if target.id == actor.id:
        raise AdminError(409, "You can't change your own role or deactivate yourself; ask another admin")

    if target.role == "admin" and target.is_active and (role == "user" or is_active is False):
        # Lock every active admin (in id order, so two admins demoting each other can't deadlock);
        # the second of two such requests then sees the first one's change and is refused
        admins = db.scalars(select(User).where(User.role == "admin", User.is_active.is_(True))
                            .order_by(User.id).with_for_update()).all()
        if not any(a.id != target.id for a in admins):
            raise AdminError(409, "That would leave no active admin")

    for field, old, new in changes:
        setattr(target, field, new)
        action = {"role": "user.promote" if new == "admin" else "user.demote",
                  "is_active": "user.reactivate" if new else "user.deactivate"}[field]
        db.add(AuditLog(actor_id=actor.id, action=action, target_type="user", target_id=str(target.id),
                        details={"email": target.email, "from": old, "to": new}))
    if is_active is False:
        revoke_all_sessions(db, target.id)
    db.commit()
    return target


# ── usage ───────────────────────────────────────────────────

def _in_range(query: Select, start: date | None, end: date | None) -> Select:
    if start is not None:
        query = query.where(Upload.created_at >= _midnight(start))
    if end is not None:
        query = query.where(Upload.created_at < _midnight(end + timedelta(days=1)))
    return query


def _results_bytes(settings: Settings, upload_id) -> int:
    path = results_dir(settings, upload_id) / RESULTS_FILE
    try:
        return path.stat().st_size
    except OSError:
        return 0


def usage(db: Session, settings: Settings, start: date | None, end: date | None) -> list[dict]:
    """Per user, uploads created in [start, end] (all time when open): counts, bytes, flows, processing
    time; plus storage used right now (raw files not purged or deleted + result files)."""
    if start and end and start > end:
        raise AdminError(422, "'from' is after 'to'")
    sums = {r.user_id: r for r in db.execute(_in_range(
        select(Upload.user_id,
               func.count(Upload.id).label("uploads"),
               func.sum(case((Upload.status == "failed", 1), else_=0)).label("failed"),
               func.sum(case((Upload.deleted_at.is_not(None), 1), else_=0)).label("deleted"),
               func.coalesce(func.sum(Upload.size_bytes), 0).label("bytes"),
               func.coalesce(func.sum(Upload.n_flows), 0).label("flows"),
               func.coalesce(func.sum(Upload.processing_ms), 0).label("processing_ms"))
        .group_by(Upload.user_id), start, end))}

    storage: dict[int, int] = {}
    for user_id, upload_id, size, raw_gone, status, deleted in db.execute(
            select(Upload.user_id, Upload.id, Upload.size_bytes, Upload.raw_deleted_at.is_not(None),
                   Upload.status, Upload.deleted_at.is_not(None))):
        used = (0 if raw_gone else size) + (_results_bytes(settings, upload_id)
                                            if status == "completed" and not deleted else 0)
        storage[user_id] = storage.get(user_id, 0) + used

    rows = []
    for user in db.scalars(select(User)):
        s = sums.get(user.id)
        rows.append({
            "user_id": user.id, "email": user.email, "username": user.username, "role": user.role,
            "is_active": user.is_active,
            "uploads": s.uploads if s else 0, "failed_uploads": int(s.failed) if s else 0,
            "deleted_uploads": int(s.deleted) if s else 0, "bytes": int(s.bytes) if s else 0,
            "flows": int(s.flows) if s else 0, "processing_ms": int(s.processing_ms) if s else 0,
            "storage_bytes": storage.get(user.id, 0),
        })
    rows.sort(key=lambda r: (-r["bytes"], r["user_id"]))
    return rows


def daily_usage(db: Session, user_id: int, start: date | None, end: date | None) -> tuple[date, date, list[dict]]:
    """One entry per UTC day in [start, end], zero-filled; defaults to the last 30 days."""
    if db.get(User, user_id) is None:
        raise AdminError(404, f"No user {user_id}")
    end = end or _today()
    start = start or end - timedelta(days=DEFAULT_DAILY_DAYS - 1)
    if start > end:
        raise AdminError(422, "'from' is after 'to'")
    if (end - start).days + 1 > MAX_DAILY_DAYS:
        raise AdminError(422, f"At most {MAX_DAILY_DAYS} days at a time")

    days = {start + timedelta(days=i): {"uploads": 0, "bytes": 0, "flows": 0, "processing_ms": 0}
            for i in range((end - start).days + 1)}
    for created_at, size, flows, ms in db.execute(_in_range(
            select(Upload.created_at, Upload.size_bytes, Upload.n_flows, Upload.processing_ms)
            .where(Upload.user_id == user_id), start, end)):
        day = days.get(_utc_day(created_at))
        if day is not None:
            day["uploads"] += 1
            day["bytes"] += size
            day["flows"] += flows or 0
            day["processing_ms"] += ms or 0
    return start, end, [{"day": d, **v} for d, v in days.items()]


# ── uploads and audit ───────────────────────────────────────

def list_uploads(db: Session, page: int, size: int, user_id: int | None, status: str | None,
                 include_deleted: bool) -> tuple[list[tuple[Upload, str, str]], int]:
    query = select(Upload, User.email, User.username).join(User, Upload.user_id == User.id)
    if user_id is not None:
        query = query.where(Upload.user_id == user_id)
    if status is not None:
        query = query.where(Upload.status == status)
    if not include_deleted:
        query = query.where(Upload.deleted_at.is_(None))
    return _page(db, query.order_by(Upload.created_at.desc(), Upload.id), page, size)


def list_audit(db: Session, page: int, size: int, action: str | None, actor_id: int | None,
               target_type: str | None, target_id: str | None) -> tuple[list[tuple[AuditLog, str | None]], int]:
    """Newest first. `action` ending in '.' matches a family, e.g. 'user.'."""
    query = select(AuditLog, User.email).outerjoin(User, AuditLog.actor_id == User.id)
    if action:
        query = query.where(AuditLog.action.startswith(action, autoescape=True) if action.endswith(".")
                            else AuditLog.action == action)
    if actor_id is not None:
        query = query.where(AuditLog.actor_id == actor_id)
    if target_type:
        query = query.where(AuditLog.target_type == target_type)
    if target_id:
        query = query.where(AuditLog.target_id == target_id)
    return _page(db, query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()), page, size)
