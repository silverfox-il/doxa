"""Instagram API client against a fake HTTP session (no network)."""

from __future__ import annotations

import pytest
import requests

from doxa import instagram
from doxa.instagram import (
    Client,
    InstagramError,
    InstagramRetryableError,
    QuotaExceededError,
    with_retry,
)

TOKEN = "IGAA-secret-token-value"


class FakeResp:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        self.calls.append(
            {"method": method, "url": url, "params": params, "json": json, "headers": headers}
        )
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def client(*responses):
    session = FakeSession(*responses)
    return Client(access_token=TOKEN, ig_user_id="17841400000000000", session=session), session


def err(status, code=None, subcode=None, transient=None, msg="boom"):
    e = {"message": msg, "code": code, "error_subcode": subcode}
    if transient is not None:
        e["is_transient"] = transient
    return FakeResp(status, {"error": e})


# --- request shape ------------------------------------------------------------


def test_token_only_in_bearer_header_never_in_url_or_body():
    c, s = client(FakeResp(json_data={"id": "c1"}), FakeResp(json_data={"status_code": "FINISHED"}))
    c.create_carousel_item("https://raw.githubusercontent.com/o/r/sha/queue/x/slides/1.jpg")
    c.container_status("c1")
    for call in s.calls:
        assert call["headers"] == {"Authorization": f"Bearer {TOKEN}"}
        assert TOKEN not in call["url"]
        assert TOKEN not in str(call["params"]) and TOKEN not in str(call["json"])
    assert TOKEN not in repr(c)


def test_versioned_host():
    c, s = client(FakeResp(json_data={"user_id": "1", "username": "u"}))
    c.me()
    assert s.calls[0]["url"] == "https://graph.instagram.com/v26.0/me"
    assert s.calls[0]["params"] == {"fields": "user_id,username"}


def test_carousel_flow_payloads():
    c, s = client(
        FakeResp(json_data={"id": "child1"}),
        FakeResp(json_data={"id": "parent"}),
        FakeResp(json_data={"id": "media9"}),
        FakeResp(json_data={"id": "media9", "permalink": "https://www.instagram.com/p/X/"}),
    )
    assert c.create_carousel_item("https://x/1.jpg") == "child1"
    assert c.create_carousel_container(["c1", "c2"], "כיתוב") == "parent"
    assert c.publish("parent") == "media9"
    assert c.get_media("media9")["permalink"].endswith("/p/X/")
    child, parent, pub, media = s.calls
    assert child["method"] == "POST" and child["url"].endswith("/17841400000000000/media")
    assert child["json"] == {"image_url": "https://x/1.jpg", "is_carousel_item": True}
    assert parent["json"] == {"media_type": "CAROUSEL", "children": "c1,c2", "caption": "כיתוב"}
    assert pub["url"].endswith("/17841400000000000/media_publish")
    assert pub["json"] == {"creation_id": "parent"}
    assert media["params"] == {"fields": "id,permalink,timestamp"}


def test_me_and_quota():
    c, _ = client(
        FakeResp(json_data={"user_id": 17841400000000000, "username": "the_silver_fox_men"}),
        FakeResp(json_data={"data": [{"quota_usage": 3, "config": {"quota_total": 100}}]}),
    )
    assert c.me() == {"user_id": "17841400000000000", "username": "the_silver_fox_men"}
    q = c.publishing_quota()
    assert (q.usage, q.total, q.exhausted, str(q)) == (3, 100, False, "3/100 in the last 24h")


def test_quota_bad_shape_is_an_error():
    c, _ = client(FakeResp(json_data={"data": []}))
    with pytest.raises(InstagramError, match="unexpected content_publishing_limit"):
        c.publishing_quota()


# --- error classification -------------------------------------------------------


@pytest.mark.parametrize(
    "resp,exc",
    [
        (err(503), InstagramRetryableError),
        (err(429), InstagramRetryableError),
        (err(400, code=4), InstagramRetryableError),  # app-level throttling
        (err(400, code=-1, subcode=2207001), InstagramRetryableError),  # server error
        (err(400, code=-2, subcode=2207003), InstagramRetryableError),  # slow download
        (err(400, code=100, transient=True), InstagramRetryableError),
        (err(400, code=4, subcode=2207051), InstagramError),  # spam restriction
        (err(400, code=25, subcode=2207050), InstagramError),  # restricted account
        (err(400, code=9004, subcode=2207052), InstagramError),  # URL not fetchable
        (err(400, code=190), InstagramError),  # bad token
        (err(400, code=9, subcode=2207042), QuotaExceededError),
    ],
)
def test_error_classification(resp, exc):
    c, _ = client(resp)
    with pytest.raises(InstagramError) as info:
        c.publish("p")
    assert type(info.value) is exc


def test_error_message_is_useful_and_token_free():
    c, _ = client(err(400, code=190, msg="Invalid OAuth access token"))
    with pytest.raises(InstagramError) as info:
        c.me()
    assert "code=190" in str(info.value) and "Invalid OAuth" in str(info.value)
    assert TOKEN not in str(info.value)


def test_network_error_is_retryable_and_token_free():
    c, _ = client(requests.ConnectionError(f"https://x?access_token={TOKEN}"))
    with pytest.raises(InstagramRetryableError) as info:
        c.me()
    assert TOKEN not in str(info.value)
    assert info.value.__cause__ is None  # original exception (with URL) not chained


# --- polling --------------------------------------------------------------------


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_wait_finished_polls_until_finished():
    clock = Clock()
    c, s = client(
        FakeResp(json_data={"status_code": "IN_PROGRESS"}),
        FakeResp(json_data={"status_code": "FINISHED"}),
    )
    c.wait_finished("cid", poll_s=15, sleep=clock.sleep, clock=clock)
    assert len(s.calls) == 2 and clock.t == 15


@pytest.mark.parametrize("code", ["ERROR", "EXPIRED"])
def test_wait_finished_fails_on_error(code):
    c, _ = client(FakeResp(json_data={"status_code": code}))
    with pytest.raises(InstagramError, match=code):
        c.wait_finished("cid", sleep=lambda s: None)


def test_wait_finished_times_out_after_five_minutes():
    clock = Clock()
    c, s = client(*[FakeResp(json_data={"status_code": "IN_PROGRESS"})] * 30)
    with pytest.raises(InstagramRetryableError, match="after 300s"):
        c.wait_finished("cid", poll_s=15, sleep=clock.sleep, clock=clock)
    assert len(s.calls) == 21  # t = 0, 15, ..., 300


# --- retry ----------------------------------------------------------------------


def test_with_retry_backs_off_then_succeeds():
    delays, calls = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise InstagramRetryableError("503")
        return "ok"

    assert with_retry(flaky, sleep=delays.append) == "ok"
    assert delays == [5.0, 10.0]


def test_with_retry_gives_up_after_three():
    calls = []

    def down():
        calls.append(1)
        raise InstagramRetryableError("503")

    with pytest.raises(InstagramRetryableError):
        with_retry(down, sleep=lambda s: None)
    assert len(calls) == 3


def test_with_retry_does_not_retry_fatal_errors():
    calls = []

    def bad():
        calls.append(1)
        raise InstagramError("400")

    with pytest.raises(InstagramError):
        with_retry(bad, sleep=lambda s: None)
    assert len(calls) == 1


def test_module_has_no_print_calls():
    import inspect

    assert "print(" not in inspect.getsource(instagram)
