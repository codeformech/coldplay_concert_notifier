"""Tunables and environment loading. No secrets live in this file."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = REPO_ROOT / "state.json"

# --- What we watch -----------------------------------------------------------

ARTIST = "Coldplay"

# Ticketmaster Discovery country codes. Europe/UK markets the Discovery API covers.
COUNTRIES = [
    "GB", "IE", "DE", "FR", "ES", "NL",
    "IT", "BE", "SE", "DK", "NO", "PL", "AT", "CH",
]

# The year we actually care about. Any Ticketmaster event dated in this year is
# treated as high priority regardless of what the judge says about it.
TARGET_YEAR = "2027"

NEWS_QUERIES = [
    "Coldplay 2027 tour dates",
    "Coldplay tickets on sale",
    "Coldplay Music of the Spheres 2027",
]

# Google News RSS, biased to UK coverage.
NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-GB&gl=GB&ceid=GB:en"

# Ignore articles older than this. These queries return ~190 results, essentially
# all of it coverage of the September 2025 "138 more shows" tease re-reported for
# months; measured today, zero were published in the last 30 days. An actual
# announcement is by definition recent, so this filter takes the steady state to
# zero candidates — no tokens spent, no noise — while still catching real news
# with two weeks of slack for an outage.
NEWS_MAX_AGE_DAYS = 14

# SEO/affiliate pages that rank for "Coldplay 2027 tour" and invent on-sale dates.
# Dropped before they ever reach the API — the judge is the second line of defence,
# not the first.
DENYLIST_DOMAINS = {
    "coldplaytour2027.us",
    "coldplaytour.org",
    "coldplay2027.com",
    "toursetlist.com",
    "ticketsales.com",
    "tixel.com",
    "seatgeek.com",
    "vividseats.com",
    "stubhub.com",
    "viagogo.com",
    "aesplora.com",
}

# --- Judge -------------------------------------------------------------------

JUDGE_MODEL = "claude-haiku-4-5"
JUDGE_MAX_TOKENS = 4000
# Only alert at or above this confidence.
CONFIDENCE_THRESHOLD = 0.7
# Cap how many candidates go into a single judge call, so one noisy run can't
# blow up the request.
MAX_CANDIDATES_PER_RUN = 40

# --- Housekeeping ------------------------------------------------------------

# Forget seen ids after this long, so state.json cannot grow without bound.
SEEN_RETENTION_DAYS = 90

HTTP_TIMEOUT = 30
USER_AGENT = "coldplay-concert-notifier/1.0 (+https://github.com/)"


def load_dotenv(path: Path | None = None) -> None:
    """Read a local .env into os.environ without clobbering real env vars.

    Only used for local runs; on GitHub Actions the secrets arrive as env vars
    and no .env file exists.
    """
    env_path = path or (REPO_ROOT / ".env")
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(
            f"Missing required environment variable {name}. "
            "Set it in .env locally, or as a GitHub Actions secret."
        )
    return value
