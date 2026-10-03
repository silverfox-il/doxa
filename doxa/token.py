"""Token expiry helpers.

Full refresh orchestration (refresh-token.yml, ``gh secret set``) lands in
milestone 5. This module holds only the pure expiry math so :mod:`doxa.alerts`
can warn ahead of time without pulling in HTTP or the ``gh`` CLI.
"""

from __future__ import annotations

import datetime as dt

# A refreshed long-lived Instagram token is valid for 60 days.
TOKEN_TTL_DAYS = 60


def days_left(refreshed_at: dt.datetime, now: dt.datetime) -> int:
    """Whole days remaining before a token refreshed at ``refreshed_at`` expires."""
    expiry = refreshed_at + dt.timedelta(days=TOKEN_TTL_DAYS)
    return (expiry - now).days
