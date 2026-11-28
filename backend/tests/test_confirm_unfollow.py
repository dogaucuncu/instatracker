"""confirms_unfollow: Instagram's answer, or an honest "don't know".

Run from the backend directory:  py -3.10 -m pytest tests -q
A stub stands in for the client, so nothing touches the network.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from instagrapi.exceptions import ClientError, PleaseWaitFewMinutes  # noqa: E402
from services import instagram_service as svc  # noqa: E402


class _Stub:
    delay_range = [0, 0]

    def __init__(self, reply):
        self._reply = reply

    def navigate(self, module):
        pass

    def private_request(self, endpoint, **kwargs):
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


@pytest.fixture
def client(monkeypatch):
    def install(reply):
        monkeypatch.setattr(svc, "_client", _Stub(reply))
    return install


def test_answers_true_when_they_no_longer_follow(client):
    client({"status": "ok", "followed_by": False})
    assert svc.confirms_unfollow("1", "ayse") is True


def test_answers_false_when_they_still_follow(client):
    client({"status": "ok", "followed_by": True})
    assert svc.confirms_unfollow("1", "ayse") is False


def test_unusable_reply_is_unknown_not_a_departure(client):
    client({"status": "ok"})
    assert svc.confirms_unfollow("1", "ayse") is None


def test_ordinary_error_is_unknown(client):
    client(ClientError("something odd"))
    assert svc.confirms_unfollow("1", "ayse") is None


def test_throttle_stops_the_scan_instead_of_becoming_unknown(client):
    """Regression: the check went through instagrapi's user_friendship_v1(),
    which returns None for any ClientError. A throttle is one, so "slow down"
    read as "could not verify" and the scan kept sending requests."""
    client(PleaseWaitFewMinutes("Please wait a few minutes"))
    with pytest.raises(PleaseWaitFewMinutes):
        svc.confirms_unfollow("1", "ayse")


# ── check_user_status ────────────────────────────────────────────────────────
from instagrapi.exceptions import (  # noqa: E402
    ChallengeRequired, LoginRequired, PrivateAccount, SentryBlock, UserNotFound,
)


class _InfoStub(_Stub):
    def user_info_v1(self, pk):
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


@pytest.fixture
def info_client(monkeypatch):
    def install(reply):
        monkeypatch.setattr(svc, "_client", _InfoStub(reply))
    return install


@pytest.mark.parametrize("signal", [
    PleaseWaitFewMinutes("Please wait a few minutes"),
    LoginRequired("login_required"),
    ChallengeRequired("challenge_required"),
    SentryBlock("sentry_block"),
])
def test_stop_signals_are_not_read_as_a_block(info_client, signal):
    """Regression: these are all PrivateError subclasses, and the PrivateError
    branch answered "blocked". A throttle or an expired session in the middle
    of a scan turned everyone still to be checked into a false block."""
    info_client(signal)
    with pytest.raises(type(signal)):
        svc.check_user_status("1", "ayse")


def test_missing_account_is_deactivated(info_client):
    info_client(UserNotFound("user not found"))
    assert svc.check_user_status("1", "ayse") == "deactivated"


def test_private_account_we_cannot_see_is_blocked(info_client):
    info_client(PrivateAccount("private"))
    assert svc.check_user_status("1", "ayse") == "blocked"


def test_visible_account_is_active(info_client):
    info_client(object())
    assert svc.check_user_status("1", "ayse") == "active"
