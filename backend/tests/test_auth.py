from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from app.dependencies import get_current_user_id, get_settings
from app.settings import Settings


def _make_mock_request(token: str | None, x_user_id: str | None = None) -> Request:
    headers_dict = {}
    if token:
        headers_dict["Authorization"] = f"Bearer {token}"
        headers_dict["authorization"] = f"Bearer {token}"
    if x_user_id:
        headers_dict["X-User-ID"] = x_user_id
        headers_dict["x-user-id"] = x_user_id
    
    mock_request = MagicMock(spec=Request)
    mock_request.headers = headers_dict
    return mock_request


def test_firebase_auth_disabled_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    # Test that when auth is disabled, get_current_user_id falls back to unverified decode or "admin"
    monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    request = _make_mock_request(token=None)
    
    user_id = get_current_user_id(request, settings)
    assert user_id == "admin"


def test_firebase_auth_x_user_id_override(monkeypatch: pytest.MonkeyPatch) -> None:
    # Test that X-User-ID header overrides standard token validation
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "test-project")
    get_settings.cache_clear()
    settings = get_settings()
    request = _make_mock_request(token=None, x_user_id="custom-user-123")
    
    user_id = get_current_user_id(request, settings)
    assert user_id == "custom-user-123"


@patch("firebase_admin.auth.verify_id_token")
@patch("firebase_admin.initialize_app")
def test_firebase_token_verified(mock_init: MagicMock, mock_verify: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "test-project")
    get_settings.cache_clear()
    settings = get_settings()
    
    # Token length >= 50 and exactly 2 dots
    long_jwt_token = "valid_firebase_token_part1_that_is_long_enough_to_exceed_fifty_characters." + "part2_signature_part." + "part3_value"
    request = _make_mock_request(token=long_jwt_token)
    mock_verify.return_value = {"uid": "user_firebase_123"}

    user_id = get_current_user_id(request, settings)
    
    assert user_id == "user_firebase_123"
    mock_verify.assert_called_once_with(long_jwt_token)


@patch("firebase_admin.auth.verify_id_token")
@patch("firebase_admin.initialize_app")
def test_firebase_token_invalid_throws_401(mock_init: MagicMock, mock_verify: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "test-project")
    get_settings.cache_clear()
    settings = get_settings()
    
    # Token length >= 50 and exactly 2 dots
    long_jwt_token = "invalid_firebase_token_part1_that_is_long_enough_to_exceed_fifty_characters." + "part2_signature_part." + "part3_value"
    request = _make_mock_request(token=long_jwt_token)
    mock_verify.side_effect = Exception("Token expired")

    with pytest.raises(HTTPException) as exc_info:
        get_current_user_id(request, settings)
        
    assert exc_info.value.status_code == 401
    assert "Token verification failed" in exc_info.value.detail
