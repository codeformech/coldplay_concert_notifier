"""Dedupe state, persisted as a git-committed JSON file.

Committing this back each run also keeps the repo active, which matters because
GitHub disables scheduled workflows in repos untouched for 60 days.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load(path: Path | None = None) -> dict:
    state_path = path or config.STATE_PATH
    if not state_path.is_file():
        return {"last_run": None, "seen": {}}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # A corrupt state file should not wedge the watcher forever. Starting
        # over costs us one round of duplicate alerts, which is the safe failure.
        return {"last_run": None, "seen": {}}
    data.setdefault("seen", {})
    data.setdefault("last_run", None)
    if not isinstance(data["seen"], dict):
        data["seen"] = {}
    return data


def save(state: dict, path: Path | None = None) -> None:
    state_path = path or config.STATE_PATH
    state = dict(state)
    state["last_run"] = _now().isoformat(timespec="seconds")
    state["seen"] = _prune(state.get("seen", {}))
    state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _prune(seen: dict) -> dict:
    cutoff = _now() - timedelta(days=config.SEEN_RETENTION_DAYS)
    kept = {}
    for item_id, first_seen in seen.items():
        try:
            when = datetime.fromisoformat(first_seen)
        except (TypeError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when >= cutoff:
            kept[item_id] = first_seen
    return kept


def unseen(state: dict, candidates: list) -> list:
    seen = state.get("seen", {})
    return [c for c in candidates if c.id not in seen]


def mark_seen(state: dict, candidates: list) -> None:
    stamp = _now().isoformat(timespec="seconds")
    seen = state.setdefault("seen", {})
    for c in candidates:
        seen.setdefault(c.id, stamp)


def reset(path: Path | None = None) -> None:
    save({"last_run": None, "seen": {}}, path)
