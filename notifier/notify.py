"""Telegram delivery.

HTML parse mode rather than Markdown: headlines routinely contain characters
that Markdown treats as syntax, and escaping three characters for HTML is more
predictable than escaping Markdown's dozen.
"""

from __future__ import annotations

import html
import time

import requests

from . import config
from .judge import Verdict
from .sources import Candidate

API = "https://api.telegram.org/bot{token}/sendMessage"


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def _esc_attr(text: str) -> str:
    return html.escape(text or "", quote=True)


def render(candidate: Candidate, verdict: Verdict | None) -> str:
    if candidate.priority:
        header = "🎟️ <b>Coldplay 2027 — Ticketmaster listing is live</b>"
    else:
        header = "🎵 <b>Coldplay 2027 — possible announcement</b>"

    lines = [header, ""]

    if verdict is not None:
        lines.append(f"<b>{_esc(verdict.headline)}</b>")
        lines.append(_esc(verdict.detail))
    else:
        lines.append(f"<b>{_esc(candidate.title)}</b>")

    deadline = None
    if verdict is not None and verdict.action_deadline:
        deadline = verdict.action_deadline
    elif candidate.extra.get("deadline"):
        deadline = candidate.extra["deadline"]
    if deadline:
        lines += ["", f"⏰ <b>Act by:</b> {_esc(str(deadline))}"]

    if candidate.source == "ticketmaster":
        where = candidate.extra.get("where")
        event_date = candidate.extra.get("event_date")
        sales = candidate.extra.get("sales")
        if event_date:
            lines.append(f"📅 <b>Show:</b> {_esc(event_date)}")
        if where:
            lines.append(f"📍 {_esc(where)}")
        if sales:
            lines.append(f"🎫 {_esc(sales)}")

    if candidate.url:
        lines += ["", f'<a href="{_esc_attr(candidate.url)}">Open link</a>']

    footer = f"<i>source: {_esc(candidate.source)}"
    if verdict is not None and not candidate.priority:
        footer += f" · confidence {verdict.confidence:.0%}"
    footer += "</i>"
    lines += ["", footer]

    return "\n".join(lines)


def send(text: str, token: str, chat_id: str, session: requests.Session | None = None) -> None:
    """Post one message. Retries once, then raises — a broken token should show
    up as a red workflow run, not as silence."""
    session = session or requests.Session()
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    last_error: Exception | None = None
    for attempt in (1, 2):
        try:
            response = session.post(
                API.format(token=token), json=payload, timeout=config.HTTP_TIMEOUT
            )
            if response.ok:
                return
            last_error = RuntimeError(
                f"Telegram returned {response.status_code}: {response.text[:300]}"
            )
        except requests.RequestException as exc:
            last_error = exc
        if attempt == 1:
            time.sleep(2)

    raise RuntimeError(f"Telegram send failed after 2 attempts: {last_error}")


def send_test(token: str, chat_id: str) -> None:
    send(
        "✅ <b>Coldplay notifier is wired up.</b>\n\n"
        "This is a test message. If you can read it, the bot token and chat id "
        "are both correct and alerts will reach you.",
        token,
        chat_id,
    )
