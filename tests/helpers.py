"""
Small helpers shared by the tests (fixtures live in conftest.py).
"""

from src.api.auth import security

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
