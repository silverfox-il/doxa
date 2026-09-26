"""Instagram API client (Instagram API with Instagram Login).

Host ``graph.instagram.com`` — NOT the Facebook-Page Graph API. Checked against
Meta's docs on 2026-09-26:

* Content publishing: https://developers.facebook.com/docs/instagram-platform/content-publishing/
  (child containers -> CAROUSEL container -> poll ``status_code`` ->
  ``media_publish``; poll at most ~5 minutes; containers expire after 24 h).
* ``GET /me?fields=user_id,username`` — ``user_id`` is the professional account
  id (``<IG_ID>``) used in every publishing path.
* ``GET /<IG_ID>/content_publishing_limit?fields=quota_usage,config`` ->
  ``{"data": [{"quota_usage": n, "config": {"quota_total": ..., ...}}]}``.
* Error codes: https://developers.facebook.com/docs/instagram-api/reference/error-codes/
* Latest Graph API version: v26.0 (2026-07-29); no Instagram changes vs v25.0.

The token travels only in the ``Authorization: Bearer`` header (as in Meta's
examples), never in a URL, so it cannot leak through logged URLs or exception
messages. It is excluded from ``repr``. Nothing here prints anything.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

import requests

API_VERSION = "v26.0"
BASE_URL = f"https://graph.instagram.com/{API_VERSION}"

# status_code values of GET /{container_id}?fields=status_code
STATUS_FINISHED = "FINISHED"
STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_ERROR = "ERROR"
STATUS_EXPIRED = "EXPIRED"
STATUS_PUBLISHED = "PUBLISHED"

RETRYABLE_HTTP = {429, 500, 502, 503, 504}
# Meta error codes for throttling / temporary server trouble.
RETRYABLE_CODES = {1, 2, 4, 17, 32, 341, 613}
# Subcodes whose documented fix is "try again" (error-codes page).
RETRYABLE_SUBCODES = {2207001, 2207003, 2207008, 2207032}
# Subcodes that look retryable by code but are not: spam restriction (code 4).
FATAL_SUBCODES = {2207051, 2207050}
QUOTA_CODE = 9
QUOTA_SUBCODE = 2207042


class InstagramError(Exception):
    """Non-retryable API error (bad request, permissions, restricted account...)."""


class InstagramRetryableError(InstagramError):
    """Transient error (5xx, throttling, network) — safe to retry later."""


class QuotaExceededError(InstagramError):
    """The 24-hour publishing quota is used up."""


@dataclass
class Quota:
    usage: int
    total: int

    @property
    def exhausted(self) -> bool:
        return self.usage >= self.total

    def __str__(self) -> str:
        return f"{self.usage}/{self.total} in the last 24h"


def _error_from(resp: requests.Response, what: str) -> InstagramError:
    """Map an HTTP error response to the right exception class."""
    try:
        err = resp.json().get("error", {})
    except ValueError:
        err = {}
    code = err.get("code")
    sub = err.get("error_subcode")
    msg = err.get("error_user_msg") or err.get("message") or resp.text[:300]
    text = f"{what} -> HTTP {resp.status_code} code={code} subcode={sub}: {msg}"
    if code == QUOTA_CODE or sub == QUOTA_SUBCODE:
        return QuotaExceededError(text)
    if sub in FATAL_SUBCODES:
        return InstagramError(text)
    if (
        resp.status_code in RETRYABLE_HTTP
        or err.get("is_transient") is True
        or code in RETRYABLE_CODES
        or sub in RETRYABLE_SUBCODES
    ):
        return InstagramRetryableError(text)
    return InstagramError(text)


@dataclass
class Client:
    access_token: str = field(repr=False)
    ig_user_id: str = ""
    session: requests.Session | None = field(default=None, repr=False)
    timeout: float = 30.0

    def _session(self) -> requests.Session:
        if self.session is None:
            self.session = requests.Session()
        return self.session

    def _request(self, method: str, path: str, *, params=None, json=None) -> dict[str, Any]:
        what = f"{method} {path}"
        try:
            resp = self._session().request(
                method,
                f"{BASE_URL}{path}",
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {self.access_token}"},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            # Message names the exception type only; str(e) may echo request details.
            raise InstagramRetryableError(f"{what} -> network error: {type(e).__name__}") from None
        if not resp.ok:
            raise _error_from(resp, what)
        try:
            return resp.json()
        except ValueError:
            raise InstagramRetryableError(f"{what} -> non-JSON response") from None

    def _get(self, path: str, **params: str) -> dict[str, Any]:
        return self._request("GET", path, params=params or None)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, json=body)

    # --- account ------------------------------------------------------------

    def me(self) -> dict[str, str]:
        """``{"user_id": <IG_ID>, "username": ...}`` for the token's account."""
        out = self._get("/me", fields="user_id,username")
        return {"user_id": str(out.get("user_id", "")), "username": out.get("username", "")}

    def publishing_quota(self) -> Quota:
        out = self._get(f"/{self.ig_user_id}/content_publishing_limit", fields="quota_usage,config")
        try:
            row = out["data"][0]
            return Quota(usage=int(row["quota_usage"]), total=int(row["config"]["quota_total"]))
        except (KeyError, IndexError, TypeError, ValueError):
            raise InstagramError(f"unexpected content_publishing_limit response: {out}") from None

    # --- carousel publish flow (spec §1) --------------------------------------
    # Request bodies are built by these static methods so a dry run can log
    # exactly what a live run sends.

    @staticmethod
    def carousel_item_body(image_url: str) -> dict[str, Any]:
        return {"image_url": image_url, "is_carousel_item": True}

    @staticmethod
    def carousel_body(children: list[str], caption: str) -> dict[str, Any]:
        return {"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption}

    @staticmethod
    def publish_body(creation_id: str) -> dict[str, Any]:
        return {"creation_id": creation_id}

    def create_carousel_item(self, image_url: str) -> str:
        """Child container for one slide. Returns container id."""
        out = self._post(f"/{self.ig_user_id}/media", self.carousel_item_body(image_url))
        return str(out["id"])

    def create_carousel_container(self, children: list[str], caption: str) -> str:
        """Parent CAROUSEL container. Returns container id."""
        out = self._post(f"/{self.ig_user_id}/media", self.carousel_body(children, caption))
        return str(out["id"])

    def container_status(self, container_id: str) -> str:
        return str(self._get(f"/{container_id}", fields="status_code").get("status_code", ""))

    def wait_finished(
        self,
        container_id: str,
        *,
        timeout_s: float = 300.0,
        poll_s: float = 15.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Poll until FINISHED; raise on ERROR/EXPIRED or after ``timeout_s``."""
        deadline = clock() + timeout_s
        while True:
            code = self.container_status(container_id)
            if code == STATUS_FINISHED:
                return
            if code in (STATUS_ERROR, STATUS_EXPIRED):
                raise InstagramError(f"container {container_id} status {code}")
            if clock() >= deadline:
                raise InstagramRetryableError(
                    f"container {container_id} still {code or 'unknown'} after {timeout_s:.0f}s"
                )
            sleep(poll_s)

    def publish(self, creation_id: str) -> str:
        """Publish a FINISHED container. Returns the new media id."""
        out = self._post(f"/{self.ig_user_id}/media_publish", self.publish_body(creation_id))
        return str(out["id"])

    def get_media(self, media_id: str) -> dict[str, Any]:
        return self._get(f"/{media_id}", fields="id,permalink,timestamp")

    def recent_media(self, limit: int = 25) -> list[dict[str, Any]]:
        """Newest posts on the account (for crash recovery / idempotency)."""
        out = self._get(
            f"/{self.ig_user_id}/media",
            fields="id,caption,permalink,timestamp",
            limit=str(limit),
        )
        return list(out.get("data", []))


T = TypeVar("T")


def with_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[int, Exception], None] | None = None,
) -> T:
    """Call ``fn``; retry :class:`InstagramRetryableError` with exponential backoff.

    Only for calls that are safe to repeat (GETs, container creation — an extra
    container just expires unused). Never wrap ``media_publish``.
    """
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except InstagramRetryableError as e:
            if attempt == attempts:
                raise
            if on_retry:
                on_retry(attempt, e)
            sleep(base_delay * 2 ** (attempt - 1))
    raise AssertionError("unreachable")
