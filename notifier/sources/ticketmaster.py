"""Ticketmaster Discovery API v2 — the authoritative source.

Free key from developer.ticketmaster.com: 5000 calls/day, 5 req/s. We use
roughly 15 calls per run, so ~720/day at a 30-minute cadence.
"""

from __future__ import annotations

import time

import requests

from .. import config
from . import Candidate

BASE = "https://app.ticketmaster.com/discovery/v2"


def _get(session: requests.Session, path: str, params: dict) -> dict:
    response = session.get(
        f"{BASE}/{path}",
        params=params,
        timeout=config.HTTP_TIMEOUT,
        headers={"User-Agent": config.USER_AGENT},
    )
    response.raise_for_status()
    return response.json()


def resolve_attraction_id(api_key: str, session: requests.Session) -> str | None:
    """Look the artist up by name rather than hardcoding an id.

    Ticketmaster attraction ids are opaque and do change; resolving each run
    costs one call and removes a whole class of silent breakage.
    """
    data = _get(
        session,
        "attractions.json",
        {"apikey": api_key, "keyword": config.ARTIST, "classificationName": "music"},
    )
    attractions = data.get("_embedded", {}).get("attractions", [])
    for attraction in attractions:
        if attraction.get("name", "").strip().lower() == config.ARTIST.lower():
            return attraction.get("id")
    # No exact name match — fall back to the top hit rather than giving up,
    # but only if there was one at all.
    return attractions[0].get("id") if attractions else None


def _format_sales(sales: dict) -> tuple[str, str | None]:
    """Render the sales windows into prose, and pull out the soonest deadline.

    The presale registration window is usually the real deadline — weeks before
    the public on-sale — so it gets surfaced first.
    """
    parts: list[str] = []
    soonest: str | None = None

    public = (sales or {}).get("public") or {}
    public_start = public.get("startDateTime")
    if public_start:
        parts.append(f"public on-sale starts {public_start}")
        soonest = public_start

    for presale in (sales or {}).get("presales") or []:
        name = presale.get("name", "presale")
        start = presale.get("startDateTime")
        end = presale.get("endDateTime")
        window = " to ".join(x for x in (start, end) if x)
        parts.append(f"presale '{name}' {window}".strip())
        if start and (soonest is None or start < soonest):
            soonest = start

    return "; ".join(parts) if parts else "no sales dates published yet", soonest


def fetch(api_key: str, session: requests.Session | None = None) -> list[Candidate]:
    session = session or requests.Session()

    attraction_id = resolve_attraction_id(api_key, session)
    if not attraction_id:
        # Not an error: Ticketmaster genuinely has no Coldplay attraction record
        # in some states of the world. Nothing to report.
        return []

    candidates: list[Candidate] = []
    seen_event_ids: set[str] = set()

    for country in config.COUNTRIES:
        try:
            data = _get(
                session,
                "events.json",
                {
                    "apikey": api_key,
                    "attractionId": attraction_id,
                    "countryCode": country,
                    "size": 100,
                    "sort": "date,asc",
                },
            )
        except requests.HTTPError as exc:
            # One bad country should not sink the whole run.
            print(f"  ticketmaster: {country} failed: {exc}")
            continue
        finally:
            time.sleep(0.25)  # stay well under the 5 req/s limit

        for event in data.get("_embedded", {}).get("events", []):
            event_id = event.get("id")
            if not event_id or event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)
            candidates.append(_to_candidate(event, country))

    return candidates


def _to_candidate(event: dict, country: str) -> Candidate:
    event_id = event["id"]
    name = event.get("name", config.ARTIST)
    local_date = (event.get("dates", {}).get("start") or {}).get("localDate", "")

    venues = (event.get("_embedded") or {}).get("venues") or []
    venue = venues[0] if venues else {}
    venue_name = venue.get("name", "")
    city = (venue.get("city") or {}).get("name", "")
    country_name = (venue.get("country") or {}).get("name", country)
    where = ", ".join(x for x in (venue_name, city, country_name) if x)

    sales_text, deadline = _format_sales(event.get("sales", {}))

    return Candidate(
        id=f"tm:{event_id}",
        source="ticketmaster",
        title=f"{name} — {local_date or 'date TBA'} — {where or country}",
        url=event.get("url", ""),
        summary=f"Ticketmaster listing. Event date {local_date or 'TBA'}. {sales_text}.",
        published=local_date or None,
        priority=local_date.startswith(config.TARGET_YEAR),
        extra={
            "event_date": local_date,
            "where": where,
            "country": country,
            "sales": sales_text,
            "deadline": deadline,
        },
    )
