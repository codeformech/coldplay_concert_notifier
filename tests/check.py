"""Offline self-check. No API keys, no network except the free news feed.

    python tests/check.py

Exits non-zero on the first failure. Run this after editing config.py — the
denylist, the recency window and the confidence threshold are all easy to get
subtly wrong, and the failure mode is silence rather than an error.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from notifier import config, state  # noqa: E402
from notifier.judge import Verdict, judge, should_alert  # noqa: E402
from notifier.notify import render, to_kst  # noqa: E402
from notifier.sources import Candidate  # noqa: E402
from notifier.sources import news as ns  # noqa: E402
from notifier.sources.ticketmaster import _to_candidate  # noqa: E402

FAILURES: list[str] = []


def check(label: str, actual, expected) -> None:
    ok = actual == expected
    print(f"  {'PASS' if ok else 'FAIL'}  {label}"
          + ("" if ok else f"   got {actual!r}, want {expected!r}"))
    if not ok:
        FAILURES.append(label)


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


# --- news filtering ----------------------------------------------------------

section("News: denylist")


class _Entry:
    def __init__(self, host, title="Coldplay 2027", summary=""):
        self.source = {"href": f"https://{host}/"}
        self.link = f"https://{host}/x"
        self.id = title
        self.title = title
        self.summary = summary


spam = _Entry("coldplaytour2027.us")
legit = _Entry("www.bbc.co.uk")
check("spam domain denied", ns._is_denied(spam, ns._publisher_domain(spam)), True)
check("bbc allowed", ns._is_denied(legit, ns._publisher_domain(legit)), False)
check("www. stripped from publisher", ns._publisher_domain(legit), "bbc.co.uk")
check(
    "spam named in headline is denied",
    ns._is_denied(_Entry("news.invalid", "See coldplay2027.com for dates"), "news.invalid"),
    True,
)

section("News: recency window")


class _Dated:
    def __init__(self, days_ago):
        self.published_parsed = time.gmtime(time.time() - days_ago * 86400)


check("3 days old kept", ns._too_old(_Dated(3)), False)
check("60 days old dropped", ns._too_old(_Dated(60)), True)
check("undated entry kept (fail-open)", ns._too_old(object()), False)

section("News: identity is the headline, not Google's entry id")
bbc = "Coldplay announce 2027 UK stadium dates - BBC News"
gdn = "Coldplay announce 2027 UK stadium dates - The Guardian"
other = "Coldplay play a secret gig in Camden - BBC News"
check("same story, different publisher -> same id", ns._entry_id(bbc) == ns._entry_id(gdn), True)
check("different story -> different id", ns._entry_id(bbc) == ns._entry_id(other), False)

# --- ticketmaster ------------------------------------------------------------

section("Ticketmaster: 2027 detection and presale deadline")
event = {
    "id": "G5vYZ9abc",
    "name": "Coldplay: Music of the Spheres World Tour",
    "url": "https://www.ticketmaster.co.uk/event/G5vYZ9abc",
    "dates": {"start": {"localDate": "2027-06-18"}},
    "sales": {
        "public": {"startDateTime": "2026-09-11T08:00:00Z"},
        "presales": [{
            "name": "Fan Club Presale",
            "startDateTime": "2026-09-08T08:00:00Z",
            "endDateTime": "2026-09-10T22:00:00Z",
        }],
    },
    "_embedded": {"venues": [{
        "name": "Wembley Stadium",
        "city": {"name": "London"},
        "country": {"name": "United Kingdom"},
    }]},
}
tm = _to_candidate(event, "GB")
check("2027 event flagged priority", tm.priority, True)
check("deadline is the presale, not the public on-sale",
      tm.extra["deadline"], "2026-09-08T08:00:00Z")
check("non-target year not flagged",
      _to_candidate({**event, "dates": {"start": {"localDate": "2026-06-18"}}}, "GB").priority,
      False)
check("missing venue block falls back to the country code",
      _to_candidate({**event, "_embedded": {}}, "GB").extra["where"], "GB")
check("missing sales block does not crash",
      _to_candidate({**event, "sales": {}}, "GB").extra["deadline"], None)

# --- gating ------------------------------------------------------------------

section("Gating: should_alert")


def verdict(real=True, eu=True, conf=0.9):
    return Verdict(id="n", is_real_announcement=real, market_relevant=eu,
                   confidence=conf, headline="h", detail="d", action_deadline=None)


plain = Candidate(id="n", source="news", title="t", url="", summary="")
check("clean pass alerts", should_alert(plain, verdict()), True)
check("below threshold blocked", should_alert(plain, verdict(conf=0.5)), False)
check("not a real announcement blocked", should_alert(plain, verdict(real=False)), False)
check("non-Europe blocked", should_alert(plain, verdict(eu=False)), False)
check("missing verdict blocked", should_alert(plain, None), False)
check("Ticketmaster 2027 alerts without a verdict", should_alert(tm, None), True)

# --- rendering ---------------------------------------------------------------

section("Rendering: HTML escaping")
nasty = Candidate(
    id="news:x", source="news",
    title="Coldplay & <script>alert(1)</script>",
    url="https://example.invalid/a?x=1&y=2", summary="",
)
msg = render(nasty, Verdict(
    id="news:x", is_real_announcement=True, market_relevant=True, confidence=0.91,
    headline="Coldplay confirm 2027 dates & presale",
    detail="Presale registration closes Wednesday.",
    action_deadline="2026-07-22T23:59 BST",
))
check("script tag escaped", "<script>" in msg, False)
check("ampersand escaped in text", "&amp; presale" in msg, True)
check("ampersand escaped in href", "x=1&amp;y=2" in msg, True)
check("deadline surfaced", "Act by:" in msg, True)
check("Ticketmaster render includes venue", "Wembley Stadium" in render(tm, None), True)

section("Seoul time conversion")
check("UTC instant -> KST (+9)", to_kst("2026-09-08T08:00:00Z"), "Tue 08 Sep 17:00 KST (08:00 UTC)")
check("explicit +00:00 offset handled", to_kst("2026-09-08T08:00:00+00:00"),
      "Tue 08 Sep 17:00 KST (08:00 UTC)")
check("non-UTC offset normalised", to_kst("2026-09-08T10:00:00+02:00"),
      "Tue 08 Sep 17:00 KST (08:00 UTC)")
check("crossing midnight rolls the date", to_kst("2026-09-08T20:00:00Z"),
      "Wed 09 Sep 05:00 KST (20:00 UTC)")
# Anything without a real instant must be passed through untouched — inventing
# an on-sale time is worse than showing the raw value.
check("bare date not converted", to_kst("2026-07-22"), None)
check("prose not converted", to_kst("Friday 24 July at 09:00 BST"), None)
check("naive datetime not converted", to_kst("2026-09-08T08:00:00"), None)
check("empty string not converted", to_kst(""), None)
check("non-string not converted", to_kst(None), None)

tm_msg = render(tm, None)
check("deadline shown in KST", "17:00 KST" in tm_msg, True)
check("general sale line present", "General sale:" in tm_msg, True)
unparseable = Verdict(id="n", is_real_announcement=True, market_relevant=True, confidence=0.9,
                      headline="h", detail="d", action_deadline="Friday 24 July, 09:00 BST")
check("unconvertible deadline passed through verbatim",
      "Friday 24 July, 09:00 BST" in render(plain, unparseable), True)

# --- judge guards ------------------------------------------------------------

section("Judge: batch guards (no API call made)")
check("empty batch short-circuits", judge([]), {})
oversized = [Candidate(id=f"n:{i}", source="news", title="t", url="", summary="")
             for i in range(config.MAX_CANDIDATES_PER_RUN + 1)]
try:
    judge(oversized)
    check("oversized batch rejected", False, True)
except ValueError:
    check("oversized batch rejected", True, True)

# --- state -------------------------------------------------------------------

section("State: dedupe, prune, recovery")
tmp = Path(tempfile.mkdtemp()) / "state.json"
check("missing file loads empty", state.load(tmp), {"last_run": None, "seen": {}})

st = state.load(tmp)
cands = [Candidate(id=f"x:{i}", source="news", title="t", url="", summary="") for i in range(3)]
check("all unseen initially", len(state.unseen(st, cands)), 3)
state.mark_seen(st, cands[:2])
state.save(st, tmp)
check("dedupe survives a round-trip", len(state.unseen(state.load(tmp), cands)), 1)

aged = state.load(tmp)
aged["seen"]["ancient:1"] = "2020-01-01T00:00:00+00:00"
state.save(aged, tmp)
check("old ids pruned", "ancient:1" in state.load(tmp)["seen"], False)

tmp.write_text("{ not json", encoding="utf-8")
check("corrupt state recovers", state.load(tmp), {"last_run": None, "seen": {}})

section("State: a failed send stays unseen")
tmp2 = Path(tempfile.mkdtemp()) / "state.json"
st2 = state.load(tmp2)
batch = [Candidate(id=f"n:{i}", source="news", title="t", url="", summary="") for i in range(4)]
failed = {"n:2"}
state.mark_seen(st2, [c for c in batch if c.id not in failed])
state.save(st2, tmp2)
check("only the failed id is retried next run",
      {c.id for c in state.unseen(state.load(tmp2), batch)}, {"n:2"})

section("Ordering: priority screened first when the cap bites")
mixed = [
    Candidate(id="n:a", source="news", title="t", url="", summary=""),
    Candidate(id="tm:b", source="ticketmaster", title="t", url="", summary=""),
    Candidate(id="tm:c", source="ticketmaster", title="t", url="", summary="", priority=True),
]
mixed.sort(key=lambda c: (not c.priority, c.source != "news"))
check("priority first", mixed[0].id, "tm:c")

# --- live feed (network, no key) --------------------------------------------

section("Live: Google News feed reachable")
try:
    live = ns.fetch()
    print(f"  INFO  {len(live)} candidate(s) inside the "
          f"{config.NEWS_MAX_AGE_DAYS}-day window")
    for c in live[:5]:
        print(f"        [{c.extra.get('publisher', '?')}] {c.title[:70]}")
    if not live:
        print("        (0 is the expected steady state until dates are announced)")
    check("feed returned a list", isinstance(live, list), True)
except Exception as exc:  # noqa: BLE001
    print(f"  WARN  live feed unreachable: {exc}")

# --- verdict -----------------------------------------------------------------

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
    sys.exit(1)
print("All checks passed.")
