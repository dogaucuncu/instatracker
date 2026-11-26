"""App-build handling regression tests.

Run from the backend directory:  py -3.10 -m pytest tests -q
They use a throwaway session file and never touch the network.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from services import instagram_service as svc  # noqa: E402

OLD_SESSION = {
    "uuids": {
        "phone_id": "11111111-1111-1111-1111-111111111111",
        "uuid": "22222222-2222-2222-2222-222222222222",
        "client_session_id": "33333333-3333-3333-3333-333333333333",
        "advertising_id": "44444444-4444-4444-4444-444444444444",
        "android_device_id": "android-abcdef1234567890",
        "request_id": "55555555-5555-5555-5555-555555555555",
        "tray_session_id": "66666666-6666-6666-6666-666666666666",
    },
    "mid": "MIDVALUE",
    "ig_u_rur": None,
    "ig_www_claim": "0",
    "authorization_data": {"ds_user_id": "42", "sessionid": "42%3Aabc%3A1"},
    "cookies": {},
    "last_login": 1700000000.0,
    # An old saved profile: the app build here is stale on purpose, so the
    # tests can check that it is migrated onto the configured one.
    "device_settings": {
        "app_version": "309.0.0.40.113",
        "android_version": 34,
        "android_release": "14",
        "dpi": "510dpi",
        "resolution": "1080x2113",
        "manufacturer": "samsung",
        "device": "dm2q",
        "model": "SM-S916B",
        "cpu": "qcom",
        "version_code": "536988425",
    },
    "user_agent": (
        "Instagram 309.0.0.40.113 Android (34/14; 510dpi; 1080x2113; samsung; "
        "SM-S916B; dm2q; qcom; tr_TR; 536988425)"
    ),
    "country": "TR",
    "country_code": 90,
    "locale": "tr_TR",
    "timezone_offset": 10800,
}


@pytest.fixture
def old_session(monkeypatch, tmp_path):
    path = tmp_path / "session.json"
    path.write_text(json.dumps(OLD_SESSION))
    monkeypatch.setattr(svc, "SESSION_FILE", path)
    monkeypatch.setattr(svc, "_client", None)
    return path


def _expected_ua_part():
    return f"Instagram {config.IG_DEVICE['app_version']} Android"


def test_new_client_moves_old_session_to_configured_build(old_session):
    cl = svc._new_client()

    assert cl.user_agent.startswith(_expected_ua_part())
    assert cl.user_agent.endswith(f"{config.IG_DEVICE['version_code']})")
    assert cl.base_headers["User-Agent"] == cl.user_agent

    saved = json.loads(old_session.read_text())
    assert saved["device_settings"]["app_version"] == config.IG_DEVICE["app_version"]
    assert saved["device_settings"]["version_code"] == config.IG_DEVICE["version_code"]
    assert saved["user_agent"] == cl.user_agent


def test_sync_keeps_identity_and_login_data(old_session):
    cl = svc._new_client()

    assert cl.phone_id == OLD_SESSION["uuids"]["phone_id"]
    assert cl.android_device_id == OLD_SESSION["uuids"]["android_device_id"]
    saved = json.loads(old_session.read_text())
    assert saved["authorization_data"] == OLD_SESSION["authorization_data"]
    assert saved["last_login"] == OLD_SESSION["last_login"]
    assert saved["uuids"] == OLD_SESSION["uuids"]


def test_sync_is_idempotent(old_session):
    cl = svc._new_client()
    assert svc._sync_app_version(cl) is False


def test_load_session_uses_configured_build(old_session, monkeypatch):
    monkeypatch.setattr(svc.HardenedClient, "get_timeline_feed", lambda self, *a, **k: {})

    assert svc.load_session() is True
    assert svc._client.user_agent.startswith(_expected_ua_part())
    assert int(svc._client.user_id) == 42


@pytest.mark.parametrize(
    "message, error_type, expected",
    [
        ("Kullandığın Instagram sürümü güncel değil. Instagram'a giriş yapmak için lütfen uygulamanı yeni sürüme yükselt.", "", True),
        ("Please update the app to continue", "", True),
        ("whatever", "needs_upgrade", True),
        ("whatever", "update_required", True),
        ("Girdiğin şifre yanlış.", "bad_password", False),
        ("", "", False),
    ],
)
def test_version_rejection_detection(message, error_type, expected):
    assert svc._is_version_rejection(message, error_type) is expected


class _StubClient:
    user_agent = "stub"

    def __init__(self, error, last_json):
        self._error = error
        self.last_json = last_json
        self.last_response = None

    def login(self, *args, **kwargs):
        raise self._error


def test_login_explains_version_rejection(monkeypatch):
    raw = "Kullandığın Instagram sürümü güncel değil."
    monkeypatch.setattr(
        svc, "_new_client", lambda: _StubClient(Exception(raw), {"message": raw, "status": "fail"})
    )

    result = svc.login("someone", "secret")

    assert result["status"] == "error"
    assert "instagrapi" in result["message"]
    assert raw in result["message"]


def test_login_explains_typed_needs_upgrade_error(monkeypatch):
    raw = "Kullandığın Instagram sürümü güncel değil."
    error = svc.ClientNeedsUpgradeError(raw)
    monkeypatch.setattr(svc, "_new_client", lambda: _StubClient(error, {"error_type": "needs_upgrade"}))

    result = svc.login("someone", "secret")

    assert result["status"] == "error"
    assert "instagrapi" in result["message"]
    assert raw in result["message"]


def test_login_leaves_other_errors_untouched(monkeypatch):
    monkeypatch.setattr(svc, "_new_client", lambda: _StubClient(Exception("boom"), {}))

    assert svc.login("someone", "secret") == {"status": "error", "message": "boom"}
