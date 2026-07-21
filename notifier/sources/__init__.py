"""Source adapters. Each one yields Candidates in a shared shape."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Candidate:
    """One thing worth looking at, from any source."""

    id: str
    source: str  # "ticketmaster" | "news"
    title: str
    url: str
    summary: str
    published: str | None = None
    # Set by the source when it already knows this matters (e.g. a Ticketmaster
    # event dated in the target year). Priority candidates skip the
    # is-this-real gate — the API is authoritative, unlike a news headline.
    priority: bool = False
    extra: dict = field(default_factory=dict)

    def as_prompt_block(self) -> str:
        lines = [
            f"id: {self.id}",
            f"source: {self.source}",
            f"title: {self.title}",
            f"url: {self.url}",
        ]
        if self.published:
            lines.append(f"published: {self.published}")
        if self.summary:
            lines.append(f"summary: {self.summary}")
        return "\n".join(lines)
