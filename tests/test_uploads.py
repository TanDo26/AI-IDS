"""
/uploads: type detection from content, size limits, storage, ownership, listing and deletion.
"""

import hashlib
import uuid

import pytest
from sqlalchemy import select

from src.api import ratelimit
from src.api.db.models import AuditLog, PredictionSummary, Upload
from src.api.ratelimit import UPLOADS_PER_USER, RateLimiter
from src.api.uploads.service import display_name
from src.inference.schema import JAVA_TO_TRAINING
from tests.helpers import API, bearer, csrf, flows_csv, login, upload_file as send

UPLOADS = f"{API}/uploads"
PCAP_HEADERS = {"pcap": ["d4c3b2a1", "a1b2c3d4", "4d3cb2a1", "a1b23c4d"], "pcapng": ["0a0d0d0a"]}


def csv_of_size(min_bytes: int) -> bytes:
    one = flows_csv()
    rows = one.split(b"\n", 1)[1]
    return one + rows * (min_bytes // len(rows) + 1)


def stored_files(settings) -> list:
    root = settings.uploads_dir
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


def rows(db) -> list[Upload]:
    db.expire_all()
    return list(db.scalars(select(Upload)))


# ── access ──────────────────────────────────────────────────

def test_login_required(client, active_bundle):
    assert send(client, None, flows_csv()).status_code == 401


def test_cookie_sessions_need_csrf(client, user, active_bundle):
    login(client)
    files = {"file": ("flows.csv", flows_csv(), "text/csv")}
    assert client.post(UPLOADS, files=files).status_code == 403
    assert client.post(UPLOADS, files=files, headers=csrf(client)).status_code == 201


def test_no_active_bundle(client, user):
    assert send(client, user, flows_csv()).status_code == 503


# ── accepted files ──────────────────────────────────────────

def test_csv_upload_is_stored_and_queued(client, user, active_bundle, settings, db):
    content = flows_csv()
    r = send(client, user, content, filename="../../etc/passwd.csv")
    assert r.status_code == 201
    body = r.json()
    assert (body["status"], body["progress"], body["file_type"]) == ("queued", 0, "csv")
    assert body["original_filename"] == "passwd.csv"
    assert body["size_bytes"] == len(content) and body["sha256"] == hashlib.sha256(content).hexdigest()

    [path] = stored_files(settings)
    assert path == settings.uploads_dir / str(user.id) / f"{body['id']}.csv"   # server-made name
    assert path.read_bytes() == content
    [row] = rows(db)
    assert str(row.id) == body["id"] and row.stored_path == f"uploads/{user.id}/{body['id']}.csv"


@pytest.mark.parametrize("variant", ["java_names", "bom", "crlf"])
def test_csv_variants_are_accepted(client, user, active_bundle, variant):
    if variant == "java_names":
        content = flows_csv(rename={t: j for j, t in JAVA_TO_TRAINING.items()})
    elif variant == "bom":
        content = flows_csv(bom=True)
    else:
        content = flows_csv().replace(b"\n", b"\r\n")
    assert send(client, user, content).status_code == 201


@pytest.mark.parametrize("file_type, magic", [(t, m) for t, ms in PCAP_HEADERS.items() for m in ms])
def test_pcap_when_enabled(client, user, active_bundle, override_settings, file_type, magic):
    override_settings(enable_pcap=True)
    r = send(client, user, bytes.fromhex(magic) + b"\x00" * 60, filename="capture.bin")
    assert r.status_code == 201 and r.json()["file_type"] == file_type


# ── rejected files ──────────────────────────────────────────

def test_pcap_is_off_until_the_flow_extractor_is_validated(client, user, active_bundle, settings, db):
    r = send(client, user, bytes.fromhex("d4c3b2a1") + b"\x00" * 60, filename="capture.pcap")
    assert r.status_code == 415 and "not enabled" in r.json()["detail"]
    assert stored_files(settings) == [] and rows(db) == []


@pytest.mark.parametrize("content, status", [
    (b"", 422),                                                     # empty
    (b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, 415),                     # an image, whatever its name
    (b"PK\x03\x04" + b"\x00" * 100, 415),                            # a zip
    ("Flow Duration,Total Fwd Packets\n1,2\n".encode("utf-16"), 415),
    (b"Flow Duration,Total \xe9\n1,2\n", 415),                       # Latin-1, not UTF-8
    (b"1,2,3\n4,5,6\n", 415),                                        # no header row
    (b"just some text\nmore text\n", 415),                           # one column: not a CSV
])
def test_wrong_content_is_rejected(client, user, active_bundle, settings, content, status):
    assert send(client, user, content).status_code == status
    assert stored_files(settings) == []


def test_header_without_flows(client, user, active_bundle):
    r = send(client, user, flows_csv().split(b"\n", 1)[0] + b"\n")
    assert r.status_code == 422 and "no flows" in r.json()["detail"]


def test_missing_features_are_listed(client, user, active_bundle, settings, db):
    content = flows_csv(rename={"Flow Duration": "Duration", "Flow Bytes/s": "Bytes"})
    r = send(client, user, content)
    assert r.status_code == 422
    assert sorted(r.json()["detail"]["missing"]) == ["Flow Bytes/s", "Flow Duration"]
    assert stored_files(settings) == [] and rows(db) == []


def test_size_limit_while_storing(client, user, active_bundle, override_settings, settings, db):
    override_settings(max_upload_mb=1)
    r = send(client, user, csv_of_size(1_000_001)[:1_000_001])   # within Content-Length slack
    assert r.status_code == 413
    assert stored_files(settings) == [] and rows(db) == []         # no partial file left


def test_size_limit_before_reading_the_body(client, user, active_bundle, override_settings, settings):
    override_settings(max_upload_mb=1)
    r = send(client, user, csv_of_size(1_200_000))
    assert r.status_code == 413 and r.json()["detail"] == "Uploads are limited to 1 MB"
    assert stored_files(settings) == []


def test_content_length_is_required(client, user, active_bundle):
    def chunked():
        yield b"--b\r\nContent-Disposition: form-data; name=\"file\"; filename=\"f.csv\"\r\n\r\n"
        yield flows_csv() + b"\r\n--b--\r\n"
    r = client.post(UPLOADS, content=chunked(),
                    headers={"Content-Type": "multipart/form-data; boundary=b", **bearer(user)})
    assert r.status_code == 411


def test_form_shape(client, user, active_bundle):
    headers = bearer(user)
    assert client.post(UPLOADS, files={"data": ("f.csv", flows_csv())}, headers=headers).status_code == 422
    assert client.post(UPLOADS, json={"file": "x"}, headers=headers).status_code == 422
    two = [("file", ("a.csv", flows_csv())), ("file", ("b.csv", flows_csv()))]
    assert client.post(UPLOADS, files=two, headers=headers).status_code == 400


def test_uploads_are_rate_limited(client, user, active_bundle, override_settings, monkeypatch):
    override_settings(rate_limits_enabled=True)
    limiter = RateLimiter(None)
    monkeypatch.setattr(ratelimit, "get_rate_limiter", lambda: limiter)
    allowed = int(UPLOADS_PER_USER.split("/")[0])
    for _ in range(allowed):
        assert send(client, user, flows_csv()).status_code == 201
    assert send(client, user, flows_csv()).status_code == 429


@pytest.mark.parametrize("given, shown", [
    ("flows.csv", "flows.csv"),
    ("C:\\Users\\me\\Desktop\\day1.csv", "day1.csv"),
    ("../../etc/passwd", "passwd"),
    ("bad\x00name\n.csv", "badname.csv"),
    ("", "upload"),
    (None, "upload"),
])
def test_display_name(given, shown):
    assert display_name(given) == shown


# ── listing and lookup ──────────────────────────────────────

@pytest.fixture
def uploads_of(client, active_bundle):
    def make(user, n=1) -> list[str]:
        return [send(client, user, flows_csv(), filename=f"f{i}.csv").json()["id"] for i in range(n)]
    return make


def test_list_shows_only_your_uploads_newest_first(client, user, make_user, uploads_of):
    mine = uploads_of(user, 3)
    uploads_of(make_user("bob@example.com"), 1)
    body = client.get(UPLOADS, headers=bearer(user)).json()
    assert body["total"] == 3
    assert [u["id"] for u in body["items"]] == mine[::-1]

    page = client.get(UPLOADS, params={"page": 2, "size": 2}, headers=bearer(user)).json()
    assert ([u["id"] for u in page["items"]], page["total"]) == ([mine[0]], 3)


def test_list_filters_by_status(client, user, uploads_of, db):
    first, _ = uploads_of(user, 2)
    db.get(Upload, uuid.UUID(first)).status = "failed"
    db.commit()
    body = client.get(UPLOADS, params={"status": "failed"}, headers=bearer(user)).json()
    assert [u["id"] for u in body["items"]] == [first]
    assert client.get(UPLOADS, params={"status": "bogus"}, headers=bearer(user)).status_code == 422


def test_get_is_for_the_owner_and_admins(client, user, admin, make_user, uploads_of):
    [upload_id] = uploads_of(user)
    assert client.get(f"{UPLOADS}/{upload_id}", headers=bearer(user)).json()["id"] == upload_id
    assert client.get(f"{UPLOADS}/{upload_id}", headers=bearer(admin)).status_code == 200
    # Someone else's upload looks exactly like a missing one
    other = client.get(f"{UPLOADS}/{upload_id}", headers=bearer(make_user("bob@example.com")))
    missing = client.get(f"{UPLOADS}/{uuid.uuid4()}", headers=bearer(user))
    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json()
    assert client.get(f"{UPLOADS}/not-a-uuid", headers=bearer(user)).status_code == 422


# ── deletion ────────────────────────────────────────────────

@pytest.fixture
def processed_upload(user, uploads_of, settings, db):
    """An upload with results on disk and a summary row, as the worker will leave it."""
    [upload_id] = uploads_of(user)
    results = settings.results_dir / upload_id
    results.mkdir(parents=True)
    (results / "flows.parquet").write_bytes(b"results")
    db.add(PredictionSummary(upload_id=uuid.UUID(upload_id), n_benign=1, n_known_attack=1, n_unknown=2,
                             attack_breakdown={"DDoS": 1}, inference_ms=1.0))
    db.commit()
    return upload_id


def test_delete_removes_files_and_results_but_keeps_the_row(client, user, processed_upload, settings, db):
    raw = stored_files(settings)
    assert client.delete(f"{UPLOADS}/{processed_upload}", headers=bearer(user)).status_code == 204

    assert not any(p.exists() for p in raw)
    assert not (settings.results_dir / processed_upload).exists()
    assert db.get(PredictionSummary, uuid.UUID(processed_upload)) is None
    [row] = rows(db)
    assert row.deleted_at is not None and row.raw_deleted_at is not None
    assert row.size_bytes > 0                                        # still counts for usage

    assert client.get(f"{UPLOADS}/{processed_upload}", headers=bearer(user)).status_code == 404
    assert client.get(UPLOADS, headers=bearer(user)).json()["total"] == 0
    assert client.delete(f"{UPLOADS}/{processed_upload}", headers=bearer(user)).status_code == 404


def test_others_cannot_delete(client, processed_upload, make_user, settings):
    raw = stored_files(settings)
    r = client.delete(f"{UPLOADS}/{processed_upload}", headers=bearer(make_user("bob@example.com")))
    assert r.status_code == 404
    assert all(p.exists() for p in raw) and (settings.results_dir / processed_upload).exists()


def test_admin_deletion_is_audited(client, user, admin, processed_upload, db):
    assert client.delete(f"{UPLOADS}/{processed_upload}", headers=bearer(admin)).status_code == 204
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "upload.delete"))
    assert (audit.actor_id, audit.target_id, audit.details["owner_id"]) == (admin.id, processed_upload, user.id)


def test_owner_deletion_is_not_audited(client, user, processed_upload, db):
    client.delete(f"{UPLOADS}/{processed_upload}", headers=bearer(user))
    assert db.scalar(select(AuditLog).where(AuditLog.action == "upload.delete")) is None
