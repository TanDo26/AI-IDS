"""
/admin users, usage, uploads and audit log.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from src.api.admin import service
from src.api.db.models import AuditLog, RefreshToken, Upload, User
from tests.helpers import API, PASSWORD, bearer, flows_csv, login, upload_file

ADMIN = f"{API}/admin"
NEW_ENDPOINTS = [("get", "users"), ("patch", "users/1"), ("get", "usage"), ("get", "usage/1/daily"),
                 ("get", "uploads"), ("get", "audit")]


def actions(db) -> list[str]:
    return db.scalars(select(AuditLog.action).order_by(AuditLog.id)).all()


@pytest.mark.parametrize("method, path", NEW_ENDPOINTS)
def test_admin_only(client, user, method, path):
    kwargs = {"json": {"role": "admin"}} if method == "patch" else {}
    assert getattr(client, method)(f"{ADMIN}/{path}", **kwargs).status_code == 401
    assert getattr(client, method)(f"{ADMIN}/{path}", headers=bearer(user), **kwargs).status_code == 403


# ── users ───────────────────────────────────────────────────

@pytest.fixture
def people(make_user, admin):
    return {"admin": admin, "alice": make_user("alice@example.com"), "bob": make_user("Bob@Corp.org", "bobby"),
            "carol": make_user("carol@example.com", is_active=False)}


def names(response) -> list[str]:
    return [u["username"] for u in response.json()["items"]]


def test_list_users(client, people):
    r = client.get(f"{ADMIN}/users", headers=bearer(people["admin"]))
    assert r.json()["total"] == 4 and names(r) == ["carol", "bobby", "alice", "root"]   # newest first


@pytest.mark.parametrize("params, expected", [
    ({"q": "CORP"}, ["bobby"]),               # email, case-insensitive
    ({"q": "obb"}, ["bobby"]),                # username
    ({"q": "example"}, ["carol", "alice", "root"]),
    ({"q": "%"}, []),                         # a literal %, not a wildcard
    ({"role": "admin"}, ["root"]),
    ({"active": "false"}, ["carol"]),
    ({"page": 2, "size": 3}, ["root"]),
])
def test_list_users_filters(client, people, params, expected):
    assert names(client.get(f"{ADMIN}/users", params=params, headers=bearer(people["admin"]))) == expected


def patch(client, actor, target, **body):
    return client.patch(f"{ADMIN}/users/{target.id}", json=body, headers=bearer(actor))


def test_deactivate_ends_sessions_and_logins(client, people, db):
    alice = people["alice"]
    login(client, alice.email)
    r = patch(client, people["admin"], alice, is_active=False)
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert all(t.revoked_at is not None for t in db.scalars(select(RefreshToken)))
    assert client.get(f"{API}/auth/me", headers=bearer(alice)).status_code == 403
    assert client.post(f"{API}/auth/login", json={"email": alice.email, "password": PASSWORD}).status_code == 403

    assert patch(client, people["admin"], alice, is_active=True).json()["is_active"] is True
    login(client, alice.email)
    assert actions(db)[-2:] == ["user.deactivate", "user.reactivate"]


def test_promote_and_demote_are_audited(client, people, db):
    admin, alice = people["admin"], people["alice"]
    assert patch(client, admin, alice, role="admin").json()["role"] == "admin"
    assert client.get(f"{ADMIN}/users", headers=bearer(alice)).status_code == 200   # effective at once
    assert patch(client, admin, alice, role="user").json()["role"] == "user"
    logs = db.scalars(select(AuditLog).order_by(AuditLog.id)).all()
    assert [(l.action, l.actor_id, l.target_id, l.details["from"], l.details["to"]) for l in logs] == [
        ("user.promote", admin.id, str(alice.id), "user", "admin"),
        ("user.demote", admin.id, str(alice.id), "admin", "user")]


def test_unchanged_values_are_not_audited(client, people, db):
    r = patch(client, people["admin"], people["alice"], role="user", is_active=True)
    assert r.status_code == 200 and actions(db) == []


def test_nobody_changes_themselves(client, people):
    admin = people["admin"]
    for body in ({"role": "user"}, {"is_active": False}):
        r = patch(client, admin, admin, **body)
        assert r.status_code == 409 and "yourself" in r.json()["detail"]


def test_last_active_admin_stays(people, db):
    # Two admins demote each other at the same moment: the second request must be refused.
    # Simulated: the other admin's demotion has committed, this actor's request still runs.
    admin, alice = people["admin"], people["alice"]
    alice.role = "admin"
    db.commit()
    db.execute(update(User).where(User.id == admin.id).values(role="user"))   # "the other request"
    db.commit()
    with pytest.raises(service.AdminError, match="no active admin"):
        service.update_user(db, actor=admin, user_id=alice.id, role="user")


@pytest.mark.parametrize("body", [{}, {"role": "root"}, {"is_active": "maybe"}])
def test_bad_updates(client, people, body):
    assert patch(client, people["admin"], people["alice"], **body).status_code == 422


def test_unknown_user(client, admin):
    assert client.patch(f"{ADMIN}/users/9999", json={"role": "admin"}, headers=bearer(admin)).status_code == 404


def test_cookie_admin_needs_csrf(client, admin, people):
    login(client, admin.email)
    assert client.patch(f"{ADMIN}/users/{people['alice'].id}", json={"role": "admin"}).status_code == 403


# ── usage ───────────────────────────────────────────────────

@pytest.fixture
def activity(client, people, active_bundle, run_queued, db, settings):
    """alice: 2 completed uploads (one later deleted); bob: 1 completed + 1 failed; nothing for carol."""
    alice, bob = people["alice"], people["bob"]
    ids = {"a1": upload_file(client, alice, flows_csv()).json()["id"],
           "a2": upload_file(client, alice, flows_csv(n_copies=3)).json()["id"],
           "b1": upload_file(client, bob, flows_csv(n_copies=2)).json()["id"],
           "b2": upload_file(client, bob, flows_csv()).json()["id"]}
    bad = db.get(Upload, uuid.UUID(ids["b2"]))
    (settings.data_dir / bad.stored_path).write_bytes(b"Flow Duration,Other\n1,2\n")    # fails processing
    run_queued()
    client.delete(f"{API}/uploads/{ids['a2']}", headers=bearer(alice))
    return ids


def usage_of(response, username) -> dict:
    return next(u for u in response.json()["users"] if u["username"] == username)


def test_usage_totals(client, people, activity, db, settings):
    r = client.get(f"{ADMIN}/usage", headers=bearer(people["admin"]))
    assert r.status_code == 200
    uploads = {str(u.id): u for u in db.scalars(select(Upload))}
    alice, bob = usage_of(r, "alice"), usage_of(r, "bobby")

    a1, a2 = uploads[activity["a1"]], uploads[activity["a2"]]
    assert (alice["uploads"], alice["deleted_uploads"], alice["failed_uploads"]) == (2, 1, 0)
    assert alice["bytes"] == a1.size_bytes + a2.size_bytes                # the deleted upload still counts
    assert alice["flows"] == 4 + 12
    assert alice["processing_ms"] == a1.processing_ms + a2.processing_ms
    results = (settings.results_dir / activity["a1"] / "flows.parquet").stat().st_size
    assert alice["storage_bytes"] == a1.size_bytes + results              # the deleted one holds nothing

    assert (bob["uploads"], bob["failed_uploads"], bob["flows"]) == (2, 1, 8)
    assert usage_of(r, "carol")["uploads"] == 0                           # every user is listed
    assert [u["username"] for u in r.json()["users"]][:2] == ["alice", "bobby"]   # most bytes first
    totals = r.json()["totals"]
    assert totals["uploads"] == 4 and totals["bytes"] == sum(u.size_bytes for u in uploads.values())


def test_usage_period(client, people, activity, db):
    old = datetime.now(timezone.utc) - timedelta(days=40)
    db.execute(update(Upload).where(Upload.id == uuid.UUID(activity["a1"])).values(created_at=old))
    db.commit()
    since = (date.today() - timedelta(days=7)).isoformat()
    r = client.get(f"{ADMIN}/usage", params={"from": since}, headers=bearer(people["admin"]))
    assert r.json()["from"] == since and usage_of(r, "alice")["uploads"] == 1
    day = old.date().isoformat()
    r = client.get(f"{ADMIN}/usage", params={"from": day, "to": day}, headers=bearer(people["admin"]))
    assert usage_of(r, "alice")["uploads"] == 1 and usage_of(r, "bobby")["uploads"] == 0
    bad = client.get(f"{ADMIN}/usage", params={"from": "2026-02-02", "to": "2026-02-01"},
                     headers=bearer(people["admin"]))
    assert bad.status_code == 422


def test_daily_usage(client, people, activity, db):
    alice = people["alice"]
    today = datetime.now(timezone.utc).date()
    three_days_ago = datetime.combine(today - timedelta(days=3), datetime.min.time(), tzinfo=timezone.utc)
    db.execute(update(Upload).where(Upload.id == uuid.UUID(activity["a1"]))
               .values(created_at=three_days_ago + timedelta(hours=23, minutes=59)))
    db.commit()

    body = client.get(f"{ADMIN}/usage/{alice.id}/daily", headers=bearer(people["admin"])).json()
    assert len(body["days"]) == 30 and body["to"] == today.isoformat()
    by_day = {d["day"]: d for d in body["days"]}
    assert by_day[(today - timedelta(days=3)).isoformat()]["uploads"] == 1
    assert by_day[today.isoformat()]["uploads"] == 1 and by_day[today.isoformat()]["flows"] == 12
    assert sum(d["uploads"] for d in body["days"]) == 2


@pytest.mark.parametrize("params, status", [
    ({"from": "2026-01-01", "to": "2027-06-01"}, 422),      # > 366 days
    ({"from": "2026-02-02", "to": "2026-02-01"}, 422),
    ({"from": "2026-02-01", "to": "2026-02-03"}, 200),
])
def test_daily_usage_ranges(client, people, params, status):
    r = client.get(f"{ADMIN}/usage/{people['alice'].id}/daily", params=params, headers=bearer(people["admin"]))
    assert r.status_code == status
    if status == 200:
        assert [d["day"] for d in r.json()["days"]] == ["2026-02-01", "2026-02-02", "2026-02-03"]


def test_daily_usage_unknown_user(client, admin):
    assert client.get(f"{ADMIN}/usage/9999/daily", headers=bearer(admin)).status_code == 404


# ── uploads and audit ───────────────────────────────────────

def test_all_uploads(client, people, activity):
    headers = bearer(people["admin"])
    body = client.get(f"{ADMIN}/uploads", headers=headers).json()
    assert body["total"] == 3                                             # the deleted one is hidden
    assert {(u["owner_username"], u["id"]) for u in body["items"]} == {
        ("alice", activity["a1"]), ("bobby", activity["b1"]), ("bobby", activity["b2"])}

    with_deleted = client.get(f"{ADMIN}/uploads", params={"deleted": "true"}, headers=headers).json()
    deleted = next(u for u in with_deleted["items"] if u["id"] == activity["a2"])
    assert with_deleted["total"] == 4 and deleted["deleted_at"] is not None

    bob = client.get(f"{ADMIN}/uploads", params={"user_id": people["bob"].id, "status": "failed"},
                     headers=headers).json()
    assert [u["id"] for u in bob["items"]] == [activity["b2"]]
    page = client.get(f"{ADMIN}/uploads", params={"page": 2, "size": 2}, headers=headers).json()
    assert len(page["items"]) == 1 and page["total"] == 3


def test_audit_log(client, people, register_bundle, db):
    admin, alice = people["admin"], people["alice"]
    patch(client, admin, alice, is_active=False)
    patch(client, admin, alice, is_active=True)
    db.add(AuditLog(actor_id=None, action="user.create_admin", target_type="user", target_id="1", details={}))
    db.commit()
    register_bundle()                                                     # model.rescan + model.activate, by a CLI

    headers = bearer(admin)
    body = client.get(f"{ADMIN}/audit", headers=headers).json()
    assert [e["action"] for e in body["items"]] == ["model.activate", "model.rescan", "user.create_admin",
                                                    "user.reactivate", "user.deactivate"]
    deactivate = body["items"][-1]
    assert (deactivate["actor_email"], deactivate["target_id"], deactivate["details"]["to"]) == \
           (admin.email, str(alice.id), False)
    assert body["items"][0]["actor_id"] is None and body["items"][0]["actor_email"] is None

    def only(**params):
        return [e["action"] for e in client.get(f"{ADMIN}/audit", params=params, headers=headers).json()["items"]]
    assert only(action="user.") == ["user.create_admin", "user.reactivate", "user.deactivate"]
    assert only(action="user.deactivate") == ["user.deactivate"]
    assert only(action="user") == []                                      # exact unless it ends with '.'
    assert only(actor_id=admin.id) == ["user.reactivate", "user.deactivate"]
    assert only(target_type="user", target_id=str(alice.id)) == ["user.reactivate", "user.deactivate"]
    assert client.get(f"{ADMIN}/audit", params={"page": 2, "size": 2}, headers=headers).json()["total"] == 5
