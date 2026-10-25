"""
Small helpers shared by the tests (fixtures live in conftest.py).
"""

import pandas as pd

from src.api.auth import security
from tests.tiny_bundle import CANONICAL_FLOWS

API = "/api/v1"
PASSWORD = "correct-horse-battery"


def bearer(user) -> dict:
    """Authorization header for a user, as a script would send it."""
    return {"Authorization": f"Bearer {security.create_access_token(user.id)}"}


def csrf(client) -> dict:
    """The X-CSRF-Token header a browser would copy from the ids_csrf cookie."""
    return {security.CSRF_HEADER: client.cookies.get(security.CSRF_COOKIE)}


def cookie_header(**cookies) -> dict:
    """An explicit Cookie header; it replaces the client's cookie jar for that one request."""
    return {"Cookie": "; ".join(f"{name}={value}" for name, value in cookies.items())}


def login(client, email="alice@example.com", password=PASSWORD):
    response = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response


def flows_csv(n_copies=1, rename=None, bom=False, label=None) -> bytes:
    """The canonical flows (tests/tiny_bundle.py) as a CSV with a Src IP column, n_copies times over."""
    df = pd.DataFrame([f for f, *_ in CANONICAL_FLOWS.values()] * n_copies)
    df.insert(0, "Src IP", "10.0.0.1")
    if label is not None:
        df["Label"] = list(label) * n_copies
    text = df.rename(columns=rename or {}).to_csv(index=False)
    return ("\ufeff" if bom else "").encode("utf-8") + text.encode("utf-8")


def upload_file(client, user, content, filename="flows.csv", **kwargs):
    """POST /uploads as this user (Bearer); user=None sends no credentials."""
    headers = bearer(user) if user is not None else {}
    return client.post(f"{API}/uploads", files={"file": (filename, content, "application/octet-stream")},
                       headers=headers, **kwargs)
