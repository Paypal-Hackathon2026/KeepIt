from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.routes import auth as auth_routes


@pytest.fixture
def client():
    return TestClient(app, follow_redirects=False)


def _begin_login(client, monkeypatch):
    monkeypatch.setattr(
        auth_routes.paypal_auth,
        "build_login_url",
        lambda state: f"https://paypal.test/login?state={state}",
    )
    response = client.get("/auth/paypal/login")
    assert response.status_code == 307
    return parse_qs(urlsplit(response.headers["location"]).query)["state"][0]


def test_auth_callback_rejects_missing_state(client, monkeypatch):
    _begin_login(client, monkeypatch)
    exchange_code = Mock()
    monkeypatch.setattr(auth_routes.paypal_auth, "exchange_code", exchange_code)

    response = client.get("/auth/callback", params={"code": "auth-code"})

    assert response.status_code == 200
    assert response.json() == {"error": "Invalid state"}
    exchange_code.assert_not_called()


def test_auth_callback_rejects_wrong_state(client, monkeypatch):
    _begin_login(client, monkeypatch)
    exchange_code = Mock()
    monkeypatch.setattr(auth_routes.paypal_auth, "exchange_code", exchange_code)

    response = client.get(
        "/auth/callback",
        params={"code": "auth-code", "state": "wrong-state"},
    )

    assert response.status_code == 200
    assert response.json() == {"error": "Invalid state"}
    exchange_code.assert_not_called()


def test_auth_callback_paypal_error_returns_failure(client):
    response = client.get(
        "/auth/callback",
        params={"error": "access_denied"},
    )

    assert response.status_code == 200
    assert response.json() == {"error": "Login was cancelled or failed"}


def test_auth_callback_success_sets_profile_in_session(client, monkeypatch):
    state = _begin_login(client, monkeypatch)
    profile = {"id": "profile-1", "display_name": "Test User"}
    exchange_code = Mock(return_value="access-token")
    get_user_info = Mock(
        return_value={
            "payer_id": "payer-1",
            "name": "Test User",
            "emails": [
                {"value": "secondary@example.com", "primary": False},
                {"value": "primary@example.com", "primary": True},
            ],
        }
    )
    get_or_create_profile = Mock(return_value=profile)
    get_profile = Mock(return_value=profile)
    monkeypatch.setattr(auth_routes.paypal_auth, "exchange_code", exchange_code)
    monkeypatch.setattr(auth_routes.paypal_auth, "get_user_info", get_user_info)
    monkeypatch.setattr(auth_routes.profiles, "get_or_create_profile", get_or_create_profile)
    monkeypatch.setattr(auth_routes.profiles, "get_profile", get_profile)

    response = client.get(
        "/auth/callback",
        params={"code": "auth-code", "state": state},
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/challenges"
    exchange_code.assert_called_once_with("auth-code")
    get_user_info.assert_called_once_with("access-token")
    get_or_create_profile.assert_called_once_with(
        paypal_user_id="payer-1",
        display_name="Test User",
        paypal_email="primary@example.com",
    )

    me_response = client.get("/api/me")
    assert me_response.status_code == 200
    assert me_response.json() == profile
    get_profile.assert_called_once_with("profile-1")


def test_current_user_without_session_redirects_to_login(client):
    response = client.get("/api/me")

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/paypal/login"
