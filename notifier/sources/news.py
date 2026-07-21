"""Google News RSS — the fast but noisy source.

coldplay.com returns 403 to every non-browser client (including /robots.txt), so
press coverage is the only way to hear about an announcement before it shows up
as a Ticketmaster listing. The tradeoff is noise: the top results for
"Coldplay 2027 tour" are largely affiliate pages that invent on-sale dates.
Hence the denylist here, and the judge downstream.
"""

from __future__ import annotations

import calendar
import hashlib
import re
import time
from urllib.parse import quote_plus, urlparse

import feedparser
import requests

from .. import config
from . import Candidate

_PUBLISHER_SUFFIX = re.compile(r"\s+-\s+[^-]+$")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")


def _publisher_domain(entry) -> str:
    """Google News wraps every link in a redirect, so read the publisher off
    the <source> element instead of the href."""
    source = getattr(entry, "source", None)
    href = ""
    if source is not None:
        href = getattr(source, "href", "") or (
            source.get("href", "") if isinstance(source, dict) else ""
        )
    if not href:
        href = getattr(entry, "link", "")
    host = urlparse(href).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _is_denied(entry, domain: str) -> bool:
    if domain and any(domain == d or domain.endswith("." + d) for d in config.DENYLIST_DOMAINS):
        return True
    # Backstop: aggregators sometimes surface under a neutral host while
    # naming the spam site in the headline.
    haystack = f"{getattr(entry, 'title', '')} {getattr(entry, 'summary', '')}".lower()
    return any(d in haystack for d in config.DENYLIST_DOMAINS)


def _normalise_title(title: str) -> str:
    """Collapse a headline to a comparison key.

    Google News appends ' - Publisher' and mints a different entry id for the
    same story under each query, so keying on the entry id both duplicates
    stories across queries and risks re-alerting when Google churns its ids.
    The headline is the stable identity.
    """
    stripped = _PUBLISHER_SUFFIX.sub("", title)
    return " ".join(_NON_ALNUM.sub("", stripped.lower()).split())[:70]


def _entry_id(title: str) -> str:
    key = _normalise_title(title) or title
    return "news:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _too_old(entry) -> bool:
    """Drop stale coverage. Entries with no parseable date are kept — a feed
    quirk should never be the reason we miss the announcement."""
    published = getattr(entry, "published_parsed", None)
    if not published:
        return False
    age_days = (time.time() - calendar.timegm(published)) / 86400
    return age_days > config.NEWS_MAX_AGE_DAYS


def fetch(session: requests.Session | None = None) -> list[Candidate]:
    session = session or requests.Session()
    candidates: list[Candidate] = []
    seen_ids: set[str] = set()

    for query in config.NEWS_QUERIES:
        url = config.NEWS_RSS.format(query=quote_plus(query))
        try:
            response = session.get(
                url,
                timeout=config.HTTP_TIMEOUT,
                headers={"User-Agent": config.USER_AGENT},
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"  news: query {query!r} failed: {exc}")
            continue

        feed = feedparser.parse(response.content)
        for entry in feed.entries:
            domain = _publisher_domain(entry)
            if _is_denied(entry, domain) or _too_old(entry):
                continue

            title = getattr(entry, "title", "").strip()
            item_id = _entry_id(title)
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            summary = getattr(entry, "summary", "").strip()
            # Google News summaries are an HTML link blob; the headline carries
            # the signal, so keep the summary short rather than shipping markup.
            summary = summary[:400]

            candidates.append(
                Candidate(
                    id=item_id,
                    source="news",
                    title=title,
                    url=getattr(entry, "link", ""),
                    summary=f"Publisher: {domain or 'unknown'}. {summary}".strip(),
                    published=getattr(entry, "published", None),
                    priority=False,
                    extra={"publisher": domain, "query": query},
                )
            )

    return candidates
