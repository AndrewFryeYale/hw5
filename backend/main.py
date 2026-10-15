"""Campus Customs desk API (FastAPI).

Start it from the backend folder:
    cd backend && ../venv/bin/uvicorn main:app --reload --port 8000
Interactive docs: http://127.0.0.1:8000/docs

The API opens one connection to the campus-customs MCP server for its whole life (the same one the agents
use), and every shop fact it returns comes through MCP tools. Running a ticket starts the Boss agent in the
background and returns at once; the board polls /events to watch it work. Agents can only *request*
payments and purchases. POST /approvals/{id}/approve is the human click that actually pays, and
POST /receipts is how a person records money coming in (e.g. a customer's deposit).
Every action is appended to output/audit_trail.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import audit
import team
from run import work_ticket

HW_DIR = Path(__file__).resolve().parent.parent
ORIGINAL_DB = HW_DIR / "data" / "campus_customs.db"
# Same override the MCP server honors, so a scratch test run resets the scratch copy.
WORKING_DB = Path(os.environ.get("CAMPUS_CUSTOMS_DB") or HW_DIR / "data" / "campus_customs_new.db")

# In-memory run registry: run_id -> {ticket_id, status, started_at, finished_at, resolution, error}.
RUNS: dict[str, dict[str, Any]] = {}
_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with team.MCP:  # one MCP server process for the API and every agent run
        yield


app = FastAPI(title="Campus Customs Desk API", lifespan=lifespan)
# The desk dashboard (frontend/, `npm run dev`) is served by Vite on port 5173; only that origin may call the API.
FRONTEND_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
# Optional extra origins (comma-separated), e.g. DESK_EXTRA_ORIGINS=http://localhost:5174 for a second dev server.
FRONTEND_ORIGINS += [o.strip() for o in os.environ.get("DESK_EXTRA_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=FRONTEND_ORIGINS, allow_methods=["GET", "POST"],
                   allow_headers=["Content-Type"])


async def mcp(tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call an MCP tool; a tool-level {"error": ...} becomes a 404 (not found) or 400."""
    result = team._as_data(await team.MCP.direct_call_tool(tool, args or {}))
    if isinstance(result, dict) and "error" in result:
        code = 404 if result["error"].startswith("No ") else 400
        raise HTTPException(status_code=code, detail=result["error"])
    return result


def running_ticket_ids() -> set[int]:
    return {r["ticket_id"] for r in RUNS.values() if r["status"] == "running"}


# ---------- Tickets ----------

@app.get("/tickets")
async def list_tickets() -> dict[str, Any]:
    """Every ticket with its status and whether it is open or resolved."""
    data = await mcp("list_tickets")
    running = running_ticket_ids()
    for t in data["tickets"]:
        t["state"] = "resolved" if t["is_resolved"] else "open"
        t["agent_running"] = t["id"] in running
    return data


@app.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: int) -> dict[str, Any]:
    """One ticket in full (including its running notes), its approvals, and whether agents are on it now."""
    ticket = await mcp("get_ticket", {"ticket_id": ticket_id})
    ticket["state"] = "resolved" if ticket["status"] == "resolved" else "open"
    ticket["agent_running"] = ticket_id in running_ticket_ids()
    ticket["approvals"] = (await mcp("list_approvals", {"ticket_id": ticket_id}))["approvals"]
    ticket["receipts"] = (await mcp("list_receipts", {"ticket_id": ticket_id}))["receipts"]
    return ticket


class ResolveRequest(BaseModel):
    decided_by: str = Field("desk", description="Who is closing the ticket.")
    note: str = Field("Marked resolved at the desk.", description="Why it is resolved (appended to ticket notes).")


@app.post("/tickets/{ticket_id}/resolve")
async def resolve_ticket(ticket_id: int, body: ResolveRequest | None = None) -> dict[str, Any]:
    """A person marks a ticket resolved (e.g. the customer picked up their order). Refused while agents
    are working it or while it still has a pending approval."""
    body = body or ResolveRequest()
    if ticket_id in running_ticket_ids():
        raise HTTPException(status_code=409, detail=f"Agents are still working ticket #{ticket_id}.")
    pending = (await mcp("list_approvals", {"status": "pending", "ticket_id": ticket_id}))["approvals"]
    if pending:
        raise HTTPException(status_code=409, detail=f"Ticket #{ticket_id} has {len(pending)} approval(s) waiting; "
                                                    "approve or reject them first.")
    who = body.decided_by.strip() or "desk"
    result = await mcp("update_ticket", {"ticket_id": ticket_id, "status": "resolved", "note": body.note,
                                         "updated_by": f"human:{who}"})
    await audit.record("api_ticket_resolved", "api", ticket_id=ticket_id, decided_by=who, note=body.note)
    return result


class RunRequest(BaseModel):
    dry_run: bool = Field(False, description="Block request_approval and update_ticket for this run.")


async def _run_ticket(run_id: str, ticket_id: int, dry_run: bool) -> None:
    run = RUNS[run_id]
    try:
        res = await work_ticket(ticket_id, run_id, ledger=[], dry_run=dry_run)
        run.update(status="finished" if res else "failed", resolution=res.model_dump() if res else None,
                   error=None if res else "see audit trail (ticket_failed)")
    except Exception as exc:  # noqa: BLE001 - surface any failure on /runs instead of losing it in a task
        run.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    run["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")


@app.post("/tickets/{ticket_id}/run", status_code=202)
async def run_ticket(ticket_id: int, body: RunRequest | None = None,
                     wait: bool = Query(False, description="Block until the agents finish")) -> dict[str, Any]:
    """Start the Boss agent (and whoever it delegates to) on one ticket."""
    await mcp("get_ticket", {"ticket_id": ticket_id})  # 404 if it doesn't exist
    if ticket_id in running_ticket_ids():
        raise HTTPException(status_code=409, detail=f"Agents are already working ticket #{ticket_id}.")
    dry_run = bool(body and body.dry_run)
    run_id = uuid.uuid4().hex[:12]
    RUNS[run_id] = {"run_id": run_id, "ticket_id": ticket_id, "status": "running", "dry_run": dry_run,
                    "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "finished_at": None, "resolution": None, "error": None}
    await audit.record("api_ticket_run", run_id, ticket_id=ticket_id, dry_run=dry_run)
    task = asyncio.create_task(_run_ticket(run_id, ticket_id, dry_run))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    if wait:
        await task
    return RUNS[run_id]


@app.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    """Status of one agent run (running / finished / failed) and the Boss's resolution."""
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail=f"No run {run_id} since the server started.")
    return RUNS[run_id]


# ---------- Agent events (for the board to poll) ----------

def _event_view(e: dict[str, Any]) -> dict[str, Any]:
    """One audit entry -> what the board shows: who, what they said, which tool they used."""
    d, ev = e["details"], e["event"]
    view = {k: e.get(k) for k in ("seq", "ts", "run_id", "event", "agent", "ticket_id", "chain")}
    if ev == "agent_started":
        view["said"] = d.get("prompt")
    elif ev == "agent_finished":
        out = d.get("output") or {}
        out = out if isinstance(out, dict) else {}
        view["said"] = out.get("decision") or out.get("summary")
        view["customer_message"] = out.get("customer_message") or out.get("customer_message_draft")
        view["tokens"] = d.get("tokens_incl_delegations")
    elif ev in ("delegation", "delegation_blocked"):
        view.update(said=f"-> {d.get('to_agent')}: {d.get('request')}", to_agent=d.get("to_agent"),
                    request=d.get("request"), blocked_reason=d.get("reason"))
    elif ev in ("mcp_tool_call", "mcp_tool_blocked"):
        view.update(tool=d.get("tool"), args=d.get("args"), ok=d.get("ok", False), write=d.get("write", False),
                    result=d.get("result"), blocked_reason=d.get("reason"))
    elif ev == "ticket_finished":
        r = d.get("resolution") or {}
        view.update(said=r.get("decision"), status=r.get("new_status"), tokens=d.get("total_tokens"))
    else:
        view["details"] = d
    return {k: v for k, v in view.items() if v is not None}


@app.get("/events")
async def recent_events(since: int = Query(0, description="Only events with seq greater than this"),
                        limit: int = Query(50, ge=1, le=500),
                        ticket_id: int | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Recent agent events: what each agent said, delegations, and every MCP tool call. Poll with
    since=<latest_seq> to get only new ones."""
    entries = json.loads(audit.AUDIT_PATH.read_text()) if audit.AUDIT_PATH.exists() else []
    picked = [e for e in entries if e["seq"] > since
              and (ticket_id is None or e.get("ticket_id") == ticket_id)
              and (run_id is None or e.get("run_id") == run_id)]
    resets = [e["seq"] for e in entries if e["event"] == "api_database_reset"]
    return {"latest_seq": entries[-1]["seq"] if entries else 0,
            "last_reset_seq": resets[-1] if resets else 0,  # runs before this happened on data since wiped
            "events": [_event_view(e) for e in picked[-limit:]]}


# ---------- Human approvals ----------

@app.get("/approvals")
async def list_approvals(status: str | None = Query("pending"), ticket_id: int | None = None) -> dict[str, Any]:
    """Payments and purchases the agents asked for (default: those waiting for a human)."""
    args: dict[str, Any] = {"status": status} if status else {}
    if ticket_id is not None:
        args["ticket_id"] = ticket_id
    return await mcp("list_approvals", args)


class Decision(BaseModel):
    decided_by: str = Field("desk", description="Who clicked the button (written to the payment and ticket).")


async def _decide(approval_id: int, decision: str, body: Decision | None) -> dict[str, Any]:
    who = (body.decided_by if body else "desk").strip() or "desk"
    result = await mcp("decide_approval", {"approval_id": approval_id, "decision": decision, "decided_by": who})
    await audit.record("api_approval_decided", "api", ticket_id=result["approval"].get("ticket_id"),
                       approval_id=approval_id, decision=decision, decided_by=who, result=result)
    return result


@app.post("/approvals/{approval_id}/approve")
async def approve(approval_id: int, body: Decision | None = None) -> dict[str, Any]:
    """The human Approve click: pays the invoice/rent or raises the purchase order, then updates the ticket."""
    return await _decide(approval_id, "approved", body)


@app.post("/approvals/{approval_id}/reject")
async def reject(approval_id: int, body: Decision | None = None) -> dict[str, Any]:
    """The human Reject click: nothing is paid and the ticket is escalated."""
    return await _decide(approval_id, "rejected", body)


# ---------- Cash ----------

@app.get("/cash")
async def cash() -> dict[str, Any]:
    """Current checking balance (cash_accounts) plus what's pending approval and still owed."""
    pos = await mcp("get_cash_position", {"account": "checking"})
    return {k: pos[k] for k in ("account", "balance", "balance_as_of", "shop_date", "pending_approvals_total",
                                "total_obligations", "balance_after_obligations", "upcoming_rent", "warnings")}


# ---------- Money in ----------

class ReceiptRequest(BaseModel):
    amount: float = Field(gt=0, description="Dollars received.")
    payer: str = Field(min_length=1, description="Who paid, e.g. 'Yale AI Club'.")
    memo: str = Field("Deposit", min_length=1, description="What it was for.")
    received_by: str = Field("desk", description="Who at the desk recorded it (written to the receipt and ticket).")
    ticket_id: int | None = Field(None, description="The ticket the money belongs to, if any.")


@app.post("/receipts")
async def record_receipt(body: ReceiptRequest) -> dict[str, Any]:
    """A person records money received (e.g. a customer's deposit): checking goes up by exactly that amount."""
    who = body.received_by.strip() or "desk"
    args: dict[str, Any] = {"amount": body.amount, "payer": body.payer, "memo": body.memo,
                            "recorded_by": f"human:{who}"}
    if body.ticket_id is not None:
        args["ticket_id"] = body.ticket_id
    result = await mcp("record_receipt", args)
    await audit.record("api_receipt_recorded", "api", ticket_id=body.ticket_id, amount=result["receipt"]["amount"],
                       payer=body.payer, received_by=who, result=result)
    return result


@app.get("/receipts")
async def list_receipts(ticket_id: int | None = None) -> dict[str, Any]:
    """Money received so far, optionally for one ticket."""
    return await mcp("list_receipts", {"ticket_id": ticket_id} if ticket_id is not None else {})


# ---------- Reset ----------

@app.post("/reset")
async def reset_database() -> dict[str, Any]:
    """Restore data/campus_customs_new.db from the untouched original for a fresh run. Clears payments,
    approvals, receipts and ticket notes. The audit trail is kept (append-only) and records the reset."""
    if running_ticket_ids():
        raise HTTPException(status_code=409, detail="An agent run is in progress; wait for it to finish.")
    # SQLite's backup API copies page by page under a lock, so the MCP server never reads a half-copied file.
    with closing(sqlite3.connect(ORIGINAL_DB)) as src, closing(sqlite3.connect(WORKING_DB)) as dst:
        src.backup(dst)
    RUNS.clear()
    await audit.record("api_database_reset", "api", source=ORIGINAL_DB.name, target=WORKING_DB.name)
    return {"reset": True, "tickets": (await list_tickets())["tickets"], "cash": await cash()}
