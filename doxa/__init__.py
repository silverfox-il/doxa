"""DOXA — Instagram carousel publisher for @the_silver_fox_men.

A small, git-based queue that renders Hebrew RTL carousels and publishes one per
day from GitHub Actions. See DOXA_SPEC.md for the full build spec.
"""

__version__ = "0.1.0"

# Instagram account handle shown on the final slide and in issues.
IG_HANDLE = "@the_silver_fox_men"

# Timezone used for all scheduling decisions (publish_at is local Israel time).
TIMEZONE = "Asia/Jerusalem"
