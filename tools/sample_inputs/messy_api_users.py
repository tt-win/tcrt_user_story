"""API smoke for /api/users — pytest + requests.

This is a pure API suite: no browser, no Page Object. The pomify skill
should detect 'no UI' and pass it through as `tests/api/test_*.py`
without emitting any `pages/` files.
"""
import pytest
import requests

API = "https://api.acme.test/v1"


def test_list_users_returns_200_and_array():
    r = requests.get(API + "/users", timeout=5)
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text!r}"
    body = r.json()
    assert isinstance(body, list), f"expected list, got {type(body).__name__}"


def test_create_user_persists_and_can_be_fetched():
    payload = {
        "email": f"new+{int(__import__('time').time())}@example.com",
        "name": "Test User",
        "role": "viewer",
    }
    r = requests.post(API + "/users", json=payload, timeout=5)
    assert r.status_code == 201, f"expected 201, got {r.status_code}: {r.text!r}"
    created = r.json()
    assert created["email"] == payload["email"]
    assert created["role"] == "viewer"

    # fetch by id
    r2 = requests.get(API + f"/users/{created['id']}", timeout=5)
    assert r2.status_code == 200
    assert r2.json()["id"] == created["id"]


def test_create_user_rejects_invalid_email_with_422():
    r = requests.post(
        API + "/users",
        json={"email": "not-an-email", "name": "Bad", "role": "viewer"},
        timeout=5,
    )
    assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text!r}"
    body = r.json()
    assert "email" in str(body).lower(), f"expected 'email' in error body, got: {body!r}"


def test_delete_user_returns_404_when_already_gone():
    # try to delete a non-existent user
    r = requests.delete(API + "/users/9999999", timeout=5)
    assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text!r}"


def test_health_endpoint():
    r = requests.get(API + "/health", timeout=5)
    assert r.status_code == 200
    assert r.json().get("status") == "ok"
