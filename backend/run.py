"""Run the Campus Customs agent team over the open ticket queue.

Loop: open the MCP connection once -> list open tickets (oldest first) -> for each ticket the Boss runs
with its own budget, delegating to teammates as needed -> the next ticket's Boss sees a one-line summary of
each earlier resolution (so cash decisions account for what was already paid) -> write a run summary.
Every step is appended to output/audit_trail.json.

Run from hw5/:
    venv/bin/python backend/run.py                 # work every open ticket (queues approvals, updates tickets)
    venv/bin/python backend/run.py --ticket 103    # one ticket
    venv/bin/python backend/run.py --dry-run       # agents run, but request_approval / update_ticket are blocked
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from pydantic_ai.exceptions import UsageLimitExceeded

import audit
import team
from models import TeamDeps, TicketResolution, TicketState

RUN_SUMMARY_PATH = audit.AUDIT_PATH.with_name("last_run.json")


def ledger_line(res: TicketResolution) -> str:
    queued = "; ".join(f"approval {a.approval_id} pending: {a.kind} {a.ref_id} ${a.amount:.2f}"
                       for a in res.approvals_requested) or "no approvals requested"
    return f"#{res.ticket_id} ({res.ticket_type}) -> {res.new_status}; {queued}"


async def work_ticket(ticket_id: int, run_id: str, ledger: list[str], dry_run: bool) -> TicketResolution | None:
    state = TicketState(ticket_id=ticket_id, dry_run=dry_run)
    deps = TeamDeps(agent="boss", run_id=run_id, chain=("boss",), state=state)
    earlier = ("\nEarlier tickets this run (re-check numbers with tools before relying on them):\n- "
               + "\n- ".join(ledger)) if ledger else ""
    prompt = f"Work ticket #{ticket_id} end to end and return your TicketResolution.{earlier}"
    await audit.record("ticket_started", run_id, deps=deps)
    try:
        result = await team.run_agent("boss", prompt, deps, usage_limits=team.TICKET_LIMITS)
    except UsageLimitExceeded as exc:
        await audit.record("ticket_failed", run_id, deps=deps, reason="budget exceeded", error=str(exc),
                           approvals_already_requested=state.approvals)
        return None
    except Exception as exc:  # noqa: BLE001 - log any failure, keep working the rest of the queue
        await audit.record("ticket_failed", run_id, deps=deps, error=f"{type(exc).__name__}: {exc}",
                           approvals_already_requested=state.approvals)
        return None
    res, usage = result.output, result.usage
    await audit.record("ticket_finished", run_id, deps=deps, resolution=res.model_dump(),
                       delegations=state.delegations, requests=usage.requests, tool_calls=usage.tool_calls,
                       input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                       total_tokens=usage.total_tokens)
    return res


async def main(ticket: int | None, dry_run: bool) -> None:
    run_id = uuid.uuid4().hex[:12]
    await audit.record("run_started", run_id, model=team.MODEL_NAME, dry_run=dry_run,
                       limits_per_ticket=team.LIMITS)
    resolutions: list[TicketResolution] = []
    failed: list[int] = []
    async with team.MCP:
        if ticket is not None:
            ticket_ids = [ticket]
        else:
            queue = await team.MCP.direct_call_tool("list_open_tickets", {})
            ticket_ids = [t["id"] for t in team._as_data(queue)["tickets"]]
        ledger: list[str] = []
        for tid in ticket_ids:
            print(f"--- ticket #{tid} ---", flush=True)
            res = await work_ticket(tid, run_id, ledger, dry_run)
            if res is None:
                failed.append(tid)
                print("  failed (see audit trail)")
                continue
            resolutions.append(res)
            ledger.append(ledger_line(res))
            print(f"  {ledger[-1]}\n  {res.decision}")

    summary = {"run_id": run_id, "dry_run": dry_run, "tickets_failed": failed,
               "resolutions": [r.model_dump() for r in resolutions]}
    RUN_SUMMARY_PATH.write_text(json.dumps(summary, indent=2))
    await audit.record("run_finished", run_id, tickets_done=[r.ticket_id for r in resolutions],
                       tickets_failed=failed)
    print(f"run {run_id}: {len(resolutions)} done, {len(failed)} failed -> {RUN_SUMMARY_PATH.name}, audit_trail.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticket", type=int, help="work only this ticket id")
    parser.add_argument("--dry-run", action="store_true", help="block request_approval and update_ticket")
    args = parser.parse_args()
    asyncio.run(main(args.ticket, args.dry_run))
