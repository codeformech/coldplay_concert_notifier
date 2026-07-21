"""Entry point. One run = poll, screen, alert, persist.

  python -m notifier                 # a real run
  python -m notifier --dry-run       # poll and screen, send nothing, keep state
  python -m notifier --test-telegram # prove the bot token and chat id work
  python -m notifier --reset-state   # forget everything seen so far
  python -m notifier --dry-run --fixture tests/fixture.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

from . import config, state
from .judge import judge, should_alert
from .notify import discover_chat_ids, render, send, send_test
from .sources import Candidate
from .sources import news as news_source
from .sources import ticketmaster as tm_source


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="notifier", description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be sent; send nothing, write no state")
    parser.add_argument("--get-chat-id", action="store_true",
                        help="print the chat id(s) that have messaged your bot, and exit")
    parser.add_argument("--test-telegram", action="store_true",
                        help="send a single test message and exit")
    parser.add_argument("--reset-state", action="store_true",
                        help="clear state.json and exit")
    parser.add_argument("--fixture", type=Path, default=None,
                        help="read candidates from a JSON file instead of live sources")
    return parser.parse_args(argv)


def gather(fixture: Path | None) -> list[Candidate]:
    if fixture is not None:
        raw = json.loads(fixture.read_text(encoding="utf-8"))
        return [Candidate(**item) for item in raw]

    session = requests.Session()
    candidates: list[Candidate] = []

    print("Polling Ticketmaster...")
    try:
        tm = tm_source.fetch(config.require_env("TICKETMASTER_API_KEY"), session)
        print(f"  {len(tm)} event(s)")
        candidates += tm
    except requests.RequestException as exc:
        # Losing one source should degrade the run, not kill it — the other
        # source may be carrying the announcement.
        print(f"  ticketmaster unavailable: {exc}")

    print("Polling Google News...")
    try:
        items = news_source.fetch(session)
        print(f"  {len(items)} item(s) after denylist")
        candidates += items
    except requests.RequestException as exc:
        print(f"  news unavailable: {exc}")

    return candidates


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config.load_dotenv()

    if args.reset_state:
        state.reset()
        print(f"State cleared: {config.STATE_PATH}")
        return 0

    if args.get_chat_id:
        chats = discover_chat_ids(config.require_env("TELEGRAM_BOT_TOKEN"))
        if not chats:
            print(
                "No chats found yet.\n"
                "Open https://t.me/Coldplay_notifier_bot, press Start, send it any\n"
                "message, then run this again. Telegram only reports a chat once\n"
                "the bot has received something from it."
            )
            return 1
        print("Chats that have messaged your bot:\n")
        for chat in chats:
            print(f"  TELEGRAM_CHAT_ID={chat['id']}    {chat['name']} ({chat['type']})")
        print("\nPut the matching id in .env as TELEGRAM_CHAT_ID.")
        return 0

    if args.test_telegram:
        send_test(
            config.require_env("TELEGRAM_BOT_TOKEN"),
            config.require_env("TELEGRAM_CHAT_ID"),
        )
        print("Test message sent. Check Telegram.")
        return 0

    candidates = gather(args.fixture)
    current = state.load()
    fresh = state.unseen(current, candidates)

    print(f"\n{len(candidates)} candidate(s) total, {len(fresh)} new since last run.")
    if not fresh:
        if not args.dry_run:
            state.save(current)
        print("Nothing new. (Silence is the expected output until dates drop.)")
        return 0

    # Cap here, not inside judge(). Anything beyond the cap must stay unseen so
    # the next run screens it — marking it seen would silently discard it.
    fresh.sort(key=lambda c: (not c.priority, c.source != "news"))
    batch = fresh[: config.MAX_CANDIDATES_PER_RUN]
    deferred = len(fresh) - len(batch)
    if deferred:
        print(f"Screening {len(batch)}; {deferred} deferred to the next run.")

    verdicts = judge(batch)

    alerts = [(c, verdicts.get(c.id)) for c in batch]
    to_send = [(c, v) for c, v in alerts if should_alert(c, v)]

    print(f"\n{len(to_send)} of {len(batch)} cleared the bar:\n")
    for candidate, verdict in alerts:
        mark = "ALERT " if should_alert(candidate, verdict) else "skip  "
        if verdict is not None:
            reason = (
                f"real={verdict.is_real_announcement} "
                f"europe={verdict.market_relevant} "
                f"conf={verdict.confidence:.2f}"
            )
        else:
            reason = "no verdict returned"
        flag = " [priority]" if candidate.priority else ""
        print(f"  {mark}{candidate.id}{flag} — {reason}")
        print(f"         {candidate.title[:100]}")

    if args.dry_run:
        print("\n--- messages that would be sent ---")
        for candidate, verdict in to_send:
            print("\n" + render(candidate, verdict))
        print("\nDry run: nothing sent, state unchanged.")
        return 0

    token = config.require_env("TELEGRAM_BOT_TOKEN")
    chat_id = config.require_env("TELEGRAM_CHAT_ID")

    failures: list[tuple[str, str]] = []
    for candidate, verdict in to_send:
        try:
            send(render(candidate, verdict), token, chat_id)
            print(f"  sent {candidate.id}")
        except RuntimeError as exc:
            failures.append((candidate.id, str(exc)))
            print(f"  FAILED {candidate.id}: {exc}")

    # Settled = everything we screened, minus anything whose alert failed to
    # send. A failed item stays unseen so the next run retries it; a delivered
    # or deliberately-quiet item never fires again.
    failed_ids = {item_id for item_id, _ in failures}
    settled = [c for c in batch if c.id not in failed_ids]
    state.mark_seen(current, settled)
    state.save(current)
    print(f"\nState updated: {len(current['seen'])} id(s) remembered.")

    if failures:
        raise SystemExit(
            "Telegram delivery failed:\n  "
            + "\n  ".join(f"{item_id}: {err}" for item_id, err in failures)
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
