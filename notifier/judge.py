"""The Claude Haiku pass: decide what is real, then write the alert copy.

Model notes specific to claude-haiku-4-5:
  * Do NOT pass output_config.effort — that parameter errors on Haiku 4.5.
  * Do NOT pass thinking — unnecessary for classification, and Haiku 4.5 still
    uses the old {"type": "enabled", "budget_tokens": N} shape rather than
    adaptive, so a copied-from-Opus config would 400.
  * Haiku 4.5 does support structured outputs, so messages.parse() with a
    Pydantic model gives validated objects instead of hand-parsed JSON.

Prompt caching is deliberately not used: Haiku 4.5's minimum cacheable prefix is
4096 tokens and this system prompt is far shorter, so a cache_control marker
would silently never hit.
"""

from __future__ import annotations

from datetime import datetime, timezone

import anthropic
from pydantic import BaseModel

from . import config
from .sources import Candidate


class Verdict(BaseModel):
    id: str
    is_real_announcement: bool
    market_relevant: bool
    confidence: float
    headline: str
    detail: str
    action_deadline: str | None


class Verdicts(BaseModel):
    verdicts: list[Verdict]


SYSTEM = """\
You screen news items and ticket listings for one specific purpose: telling a fan \
the moment Coldplay genuinely announces 2027 tour dates or opens ticket sales for \
a show in Europe or the UK.

Today's date is {today}.

Known background, so you can tell new information from recycled information:
- Coldplay's Music of the Spheres tour paused at Wembley on 12 September 2025.
- At that show Chris Martin said there were "138 more shows to go" and that 2027 \
dates would be announced "soon". Coverage repeating that quote is NOT a new \
announcement, no matter how recently it was published.
- As of today no 2027 dates have been officially scheduled.

Set is_real_announcement = true ONLY when the item reports at least one of:
- specific 2027 tour dates, cities, or venues, attributed to the band, their \
official channels, a promoter, or a ticketing platform;
- a concrete on-sale, presale, or registration window with a date.

Set is_real_announcement = false for:
- affiliate, resale, or SEO pages that assert on-sale dates with no official \
source. These invent plausible-sounding specifics; treat unsourced precision as \
a red flag, not as evidence.
- re-reports of the September 2025 tease, retrospectives, and "what we know so \
far" roundups that add no new dates.
- items about other artists, other years, or past shows.

Set market_relevant = true when the item concerns Europe or the UK, or is a \
worldwide announcement that would include Europe. Set it to false for \
announcements limited to other regions.

confidence is your certainty in is_real_announcement, from 0.0 to 1.0. Be \
conservative: a false alarm costs the user nothing but annoyance, while an \
unfounded alert that they act on wastes their time. Only exceed 0.7 when the \
item names an official source.

headline: one short line, under 80 characters, that would make sense as a phone \
notification.
detail: one or two sentences on what actually changed and what the user should \
do next. No hedging, no restating the headline.
action_deadline: the soonest date or datetime the user must act by, copied \
verbatim from the item if it states one. Use null if none is stated. Never guess \
a date.

Return exactly one verdict per input item, using the item's id unchanged.
"""

USER_PREAMBLE = (
    "Screen the following items. Return one verdict per item.\n\n"
    "---\n"
)


def _client() -> anthropic.Anthropic:
    # Reads ANTHROPIC_API_KEY from the environment.
    return anthropic.Anthropic()


def judge(batch: list[Candidate], client: anthropic.Anthropic | None = None) -> dict[str, Verdict]:
    """Classify a batch of candidates in a single call. Returns id -> Verdict.

    The caller is responsible for capping the batch size, because the caller is
    the only thing that can decide what to do with the leftovers — anything not
    screened here must stay unseen so a later run picks it up.
    """
    if not batch:
        return {}
    if len(batch) > config.MAX_CANDIDATES_PER_RUN:
        raise ValueError(
            f"judge() got {len(batch)} candidates, over the "
            f"{config.MAX_CANDIDATES_PER_RUN} cap; slice before calling."
        )

    client = client or _client()
    today = datetime.now(timezone.utc).strftime("%d %B %Y")
    body = USER_PREAMBLE + "\n\n---\n".join(c.as_prompt_block() for c in batch)

    try:
        response = client.messages.parse(
            model=config.JUDGE_MODEL,
            max_tokens=config.JUDGE_MAX_TOKENS,
            system=SYSTEM.format(today=today),
            messages=[{"role": "user", "content": body}],
            output_format=Verdicts,
        )
    except TypeError as exc:
        # The SDK raises a bare TypeError when it cannot resolve any credential.
        # Not hard-requiring ANTHROPIC_API_KEY here on purpose: the SDK also
        # accepts ANTHROPIC_AUTH_TOKEN and an `ant auth login` profile.
        if "authentication" not in str(exc).lower():
            raise
        raise SystemExit(
            "No Anthropic credentials found. Set ANTHROPIC_API_KEY in .env "
            "locally, or as a GitHub Actions secret."
        ) from exc
    except anthropic.AuthenticationError as exc:
        raise SystemExit(f"Anthropic rejected the credentials: {exc}") from exc

    if response.stop_reason == "refusal":
        raise RuntimeError("Haiku declined to classify this batch; nothing was sent.")
    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            "Haiku hit max_tokens before finishing. Lower MAX_CANDIDATES_PER_RUN "
            "or raise JUDGE_MAX_TOKENS in config.py."
        )

    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError("Haiku returned no parseable output; nothing was sent.")

    usage = response.usage
    print(
        f"  judge: {len(batch)} item(s), "
        f"{usage.input_tokens} in / {usage.output_tokens} out tokens"
    )

    return {v.id: _clamp(v) for v in parsed.verdicts}


def _clamp(verdict: Verdict) -> Verdict:
    # Structured outputs strip numeric bounds from the schema, so the range is
    # enforced here rather than trusted.
    verdict.confidence = max(0.0, min(1.0, verdict.confidence))
    return verdict


def should_alert(candidate: Candidate, verdict: Verdict | None) -> bool:
    """A Ticketmaster listing dated in the target year is fact, not a claim, so
    it alerts even if the judge is unsure. Everything else must clear the bar."""
    if candidate.priority:
        return True
    if verdict is None:
        return False
    return (
        verdict.is_real_announcement
        and verdict.market_relevant
        and verdict.confidence >= config.CONFIDENCE_THRESHOLD
    )
