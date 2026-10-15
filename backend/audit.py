"""Append-only audit trail at output/audit_trail.json.

The file is one JSON array. Every run appends to it (earlier runs are kept); each entry is a
models.AuditEntry. The file is rewritten after every append so the trail is complete even if a run
crashes partway through.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models import AuditEntry, TeamDeps

# AUDIT_TRAIL_PATH overrides the location (used for scratch test runs).
AUDIT_PATH = Path(os.environ.get("AUDIT_TRAIL_PATH")
                  or Path(__file__).resolve().parent.parent / "output" / "audit_trail.json")
MAX_FIELD_CHARS = 4000  # long tool results are truncated in the trail, never in what the agent sees

_lock = asyncio.Lock()


def _load() -> list[dict[str, Any]]:
    if not AUDIT_PATH.exists() or not AUDIT_PATH.read_text().strip():
        return []
    return json.loads(AUDIT_PATH.read_text())


def _trim(value: Any) -> Any:
    text = json.dumps(value, default=str)
    if len(text) <= MAX_FIELD_CHARS:
        return value
    return text[:MAX_FIELD_CHARS] + "...[truncated]"


async def record(event: str, run_id: str, *, deps: TeamDeps | None = None, agent: str | None = None,
                 ticket_id: int | None = None, **details: Any) -> None:
    """Append one entry. Pass `deps` to fill agent / ticket / chain from the running agent."""
    async with _lock:
        entries = _load()
        entry = AuditEntry(
            seq=len(entries) + 1,
            ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            run_id=run_id,
            event=event,
            agent=deps.agent if deps else agent,
            ticket_id=deps.state.ticket_id if deps else ticket_id,
            chain=list(deps.chain) if deps else [],
            details={k: _trim(v) for k, v in details.items()},
        )
        entries.append(entry.model_dump())
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        AUDIT_PATH.write_text(json.dumps(entries, indent=2, default=str))
