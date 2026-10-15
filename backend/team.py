"""Shared wiring for the five Campus Customs agents.

- MODEL: gpt-5.6-luna through Portkey (OpenAI-compatible), key from PORTKEY_API_KEY.
- MCP: one connection to the campus-customs MCP server, launched exactly as .mcp.json describes. Every
  shop fact the agents see comes through it. Each agent gets a filtered view with only its own tools.
- audit_mcp_call: wraps every MCP call. It blocks tools the calling agent isn't allowed, blocks writes in
  dry-run mode, stamps write tools with the real calling agent (requested_by / updated_by can't be
  spoofed), and appends the call and its result to output/audit_trail.json. Agents can only *request*
  payments and purchases; a human approves them through the board (main.py -> decide_approval).
- delegate: the one tool every agent has for handing work to any teammate (full connectivity). Guarded
  against self-calls, cycles, depth and a per-ticket budget, and it shares the ticket's token budget.
- build_agent: what boss.py, inventory.py, accounting.py, facilities.py and customer_service.py call.
"""

from __future__ import annotations

import importlib
import json
import os
import re
from pathlib import Path
from typing import Any

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from dotenv import load_dotenv
from fastmcp.client.transports import StdioTransport
from openai import AsyncOpenAI
from pydantic_ai import Agent, ModelRetry, RunContext, Tool
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import UsageLimits

import audit
from models import AGENT_NAMES, AgentName, AgentReport, TeamDeps, TicketResolution

BACKEND_DIR = Path(__file__).resolve().parent
HW_DIR = BACKEND_DIR.parent
PROMPTS_DIR = BACKEND_DIR / "prompts"
MCP_CONFIG_PATH = HW_DIR / ".mcp.json"
MCP_SERVER_NAME = "campus-customs"

# PORTKEY_API_KEY may already be in the environment; otherwise read it from a .env (hw5/ or repo root).
load_dotenv(HW_DIR / ".env")
load_dotenv(HW_DIR.parent / ".env")

PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
MODEL_NAME = os.environ.get("PORTKEY_MODEL", "gpt-5.6-luna")

# ---------- Budgets (token / loop guardrails) ----------
MAX_DELEGATION_DEPTH = 3      # boss -> customer_service -> inventory is as deep as it goes
MAX_DELEGATIONS_PER_TICKET = 8
MAX_OUTPUT_TOKENS_PER_RESPONSE = 3_000
# One budget per ticket, shared by the Boss and every agent it delegates to.
TICKET_LIMITS = UsageLimits(request_limit=40, tool_calls_limit=60, total_tokens_limit=250_000)  # mirrored in LIMITS
LIMITS = {"request_limit": 40, "tool_calls_limit": 60, "total_tokens_limit": 250_000,
          "max_delegation_depth": MAX_DELEGATION_DEPTH, "max_delegations_per_ticket": MAX_DELEGATIONS_PER_TICKET,
          "max_output_tokens_per_response": MAX_OUTPUT_TOKENS_PER_RESPONSE}
MODEL_SETTINGS = ModelSettings(max_tokens=MAX_OUTPUT_TOKENS_PER_RESPONSE)

# ---------- Which MCP tools each agent may use ----------
# decide_approval and record_receipt are deliberately in nobody's list: only a human, through the board
# (main.py), can approve a payment or record money coming in.
WRITE_TOOLS = {"request_approval", "update_ticket"}
WRITER_FIELD = {"request_approval": "requested_by", "update_ticket": "updated_by"}
AGENT_TOOLS: dict[AgentName, set[str]] = {
    "boss": {"list_open_tickets", "get_ticket", "get_cash_position", "list_payments", "list_approvals",
             "list_receipts", "request_approval", "update_ticket"},
    "inventory": {"get_ticket", "check_stock", "list_vendors", "get_invoice", "quote_price"},
    "accounting": {"get_ticket", "get_invoice", "get_lease", "get_cash_position", "list_payments",
                   "list_approvals", "list_receipts", "quote_price", "list_vendors"},
    "facilities": {"get_ticket", "get_lease", "check_stock", "list_vendors"},
    "customer_service": {"get_ticket", "check_stock", "quote_price", "list_vendors"},
}

TEAM_ROLES = {
    "boss": "final decisions, requesting payment/purchase approvals from a human, ticket status changes",
    "inventory": "stock on hand, shortfalls, size alternatives, reorders and vendor lead times",
    "accounting": "invoices, cash position, rent funding, margins, discounts and deposits",
    "facilities": "the shop space, the lease and landlord, aisle locations, pickup and courier logistics",
    "customer_service": "talking to customers: drafts every message to a requester",
}


# ---------- Model ----------

def build_model() -> OpenAIChatModel:
    client = AsyncOpenAI(base_url=PORTKEY_BASE_URL, api_key=os.environ["PORTKEY_API_KEY"])
    return OpenAIChatModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


MODEL = build_model()


# ---------- MCP ----------

def _collect_numbers(value: Any, out: set[float]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        out.add(round(float(value), 2))
    elif isinstance(value, dict):
        for v in value.values():
            _collect_numbers(v, out)
    elif isinstance(value, list):
        for v in value:
            _collect_numbers(v, out)


def _as_data(result: Any) -> Any:
    if isinstance(result, str):
        try:
            return json.loads(result)
        except ValueError:
            return result
    return result


async def audit_mcp_call(ctx: RunContext[TeamDeps], call_tool, name: str, args: dict[str, Any]) -> Any:
    deps = ctx.deps
    if name not in AGENT_TOOLS[deps.agent]:
        await audit.record("mcp_tool_blocked", deps.run_id, deps=deps, tool=name, args=args,
                           reason="tool not allowed for this agent")
        return {"error": f"{name} is not one of {deps.agent}'s tools. Delegate to the right teammate."}
    if name in WRITE_TOOLS:
        if deps.state.dry_run:
            await audit.record("mcp_tool_blocked", deps.run_id, deps=deps, tool=name, args=args, reason="dry run")
            return {"error": "Dry run: writes are disabled. Report what you would have done instead."}
        # The writer is always the agent actually making the call, whatever the model typed.
        args = {**args, WRITER_FIELD[name]: deps.agent}

    result = _as_data(await call_tool(name, args))
    ok = not (isinstance(result, dict) and "error" in result)
    _collect_numbers(result, deps.state.seen_numbers)
    if name == "request_approval" and ok:
        deps.state.approvals.append(result["approval"])
    await audit.record("mcp_tool_call", deps.run_id, deps=deps, tool=name, args=args, ok=ok, result=result,
                       write=name in WRITE_TOOLS)
    return result


def _from_hw_dir(path: str) -> str:
    """.mcp.json paths are relative to hw5/ (so a fresh clone works); make them absolute for any working dir."""
    return str(HW_DIR / path) if not Path(path).is_absolute() and (HW_DIR / path).exists() else path


def _mcp_transport() -> StdioTransport:
    """Launch the server from .mcp.json; CAMPUS_CUSTOMS_DB (if set) is passed through for scratch runs."""
    server = json.loads(MCP_CONFIG_PATH.read_text())["mcpServers"][MCP_SERVER_NAME]
    env = dict(server.get("env") or {})
    if os.environ.get("CAMPUS_CUSTOMS_DB"):
        env["CAMPUS_CUSTOMS_DB"] = os.environ["CAMPUS_CUSTOMS_DB"]
    return StdioTransport(command=_from_hw_dir(server["command"]),
                          args=[_from_hw_dir(a) for a in server.get("args") or []], env=env, cwd=str(HW_DIR))


# One connection for the whole team; run.py opens it once with `async with team.MCP:`.
MCP = MCPToolset(_mcp_transport(), id=MCP_SERVER_NAME, process_tool_call=audit_mcp_call)


def mcp_tools_for(agent: AgentName):
    allowed = AGENT_TOOLS[agent]
    return MCP.filtered(lambda ctx, tool_def: tool_def.name in allowed)


# ---------- Delegation (full connectivity) ----------

def get_agent(name: AgentName) -> Agent[TeamDeps, Any]:
    """Look up a teammate's agent (imported lazily so agent modules can delegate to each other)."""
    return importlib.import_module(name).AGENT


async def delegate(ctx: RunContext[TeamDeps], to_agent: AgentName, request: str) -> dict[str, Any]:
    """Hand a focused sub-task to a teammate and get their structured report back.

    Teammates:
    - boss: final decisions, requesting payment/purchase approvals from a human, ticket status changes.
    - inventory: stock on hand, shortfalls, size alternatives, reorders and vendor lead times.
    - accounting: invoices, cash position, rent funding, margins, discounts and deposits.
    - facilities: the shop space, lease and landlord, aisle locations, pickup and courier logistics.
    - customer_service: drafts every message to a customer or other requester.

    Args:
        to_agent: The teammate to ask. Never yourself, never someone already in the delegation chain.
        request: One specific question or task with the ids they need (sku, size, qty, invoice or lease id)
            and what you already know, so they don't re-fetch it. Ask for exactly what you need back.
    """
    deps, state = ctx.deps, ctx.deps.state
    reason = None
    if to_agent == deps.agent:
        reason = "you can't delegate to yourself; do it with your own tools"
    elif to_agent in deps.chain:
        reason = (f"{to_agent} is already working on this ticket above you in the chain "
                  f"({' -> '.join(deps.chain)}); put what you need from them in your report instead")
    elif len(deps.chain) >= MAX_DELEGATION_DEPTH:
        reason = f"delegation depth limit ({MAX_DELEGATION_DEPTH}) reached; answer with what you have"
    elif state.delegations >= MAX_DELEGATIONS_PER_TICKET:
        reason = f"this ticket used its {MAX_DELEGATIONS_PER_TICKET} delegations; answer with what you have"
    if reason:
        await audit.record("delegation_blocked", deps.run_id, deps=deps, to_agent=to_agent, request=request,
                           reason=reason)
        return {"error": reason}

    state.delegations += 1
    child = TeamDeps(agent=to_agent, run_id=deps.run_id, chain=(*deps.chain, to_agent), state=state)
    await audit.record("delegation", deps.run_id, deps=deps, to_agent=to_agent, request=request)
    prompt = f"Ticket #{state.ticket_id}. Request from {deps.agent}: {request}"
    result = await run_agent(to_agent, prompt, child, usage=ctx.usage, usage_limits=ctx.usage_limits)
    return result.output.model_dump(exclude_defaults=True)


async def _hide_delegate_at_depth_limit(ctx: RunContext[TeamDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    # At the bottom of the chain the tool would only ever refuse, so don't spend tokens describing it.
    return None if len(ctx.deps.chain) >= MAX_DELEGATION_DEPTH else tool_def


DELEGATE_TOOL = Tool(delegate, prepare=_hide_delegate_at_depth_limit)


async def run_agent(name: AgentName, prompt: str, deps: TeamDeps, **run_kwargs: Any) -> Any:
    """Run one agent and audit its start and finish (with the tokens it used)."""
    usage = run_kwargs.get("usage")
    before = usage.total_tokens if usage else 0
    deps.state.agents_used.add(name)
    await audit.record("agent_started", deps.run_id, deps=deps, prompt=prompt)
    result = await get_agent(name).run(prompt, deps=deps, **run_kwargs)
    used = result.usage
    await audit.record("agent_finished", deps.run_id, deps=deps, output=result.output.model_dump(),
                       tokens_incl_delegations=used.total_tokens - before, requests_so_far=used.requests)
    return result


# ---------- Output checks (no invented numbers) ----------

MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s?%")


def unverified_numbers(text: str | None, seen: set[float]) -> list[str]:
    """Dollar amounts and percentages in `text` that no MCP tool returned during this ticket."""
    if not text:
        return []
    found = [m.group(0) for m in MONEY.finditer(text) if round(float(m.group(1).replace(",", "")), 2) not in seen]
    found += [m.group(0) for m in PERCENT.finditer(text) if round(float(m.group(1)), 2) not in seen]
    return found


# Team-facing phrases that must never reach a customer (the approved draft is sent word for word).
# Also the shop's internal finances: a customer never hears about vendor invoices, overdue bills or margins.
INTERNAL_NOTE = re.compile(r"\b(draft|queued|human review|team member|review and send|pending approval|"
                           r"ticket #?\d+|lease \d+|invoices?|overdue|margins?|unit cost|sku|CC-[A-Z]+-[A-Z]+)\b",
                           re.IGNORECASE)


def message_problems(text: str | None, seen: set[float]) -> str | None:
    """Why a customer-facing message can't go out as written, or None if it's fine."""
    bad = unverified_numbers(text, seen)
    if bad:
        return (f"it has amounts no tool returned: {bad}. Get them from quote_price / check_stock "
                "(or delegate to accounting) or leave them out")
    notes = sorted({m.group(0) for m in INTERNAL_NOTE.finditer(text or "")})
    if notes:
        return (f"it contains internal wording {notes}. The recipient reads it word for word: remove notes "
                "about review/drafts and internal ids or codes (use product names)")
    return None


async def _reject(ctx: RunContext[TeamDeps], reason: str) -> None:
    await audit.record("output_rejected", ctx.deps.run_id, deps=ctx.deps, reason=reason)
    raise ModelRetry(reason)


async def check_report(ctx: RunContext[TeamDeps], report: AgentReport) -> AgentReport:
    report.agent = ctx.deps.agent
    problem = message_problems(report.customer_message_draft, ctx.deps.state.seen_numbers)
    if problem:
        await _reject(ctx, f"customer_message_draft can't be used: {problem}.")
    return report


async def check_resolution(ctx: RunContext[TeamDeps], res: TicketResolution) -> TicketResolution:
    state = ctx.deps.state
    actual = {(a["id"], a["kind"], a["ref_id"], round(a["amount"], 2)) for a in state.approvals}
    claimed = {(a.approval_id, a.kind, a.ref_id, round(a.amount, 2)) for a in res.approvals_requested}
    if claimed != actual:
        await _reject(ctx, f"approvals_requested must list exactly the approvals request_approval queued on this "
                           f"ticket as (approval_id, kind, ref_id, amount): {sorted(actual) or 'none'}.")
    problem = message_problems(res.customer_message, state.seen_numbers)
    if problem:
        await _reject(ctx, f"customer_message can't be used: {problem}.")
    res.agents_consulted = sorted(a for a in state.agents_used if a != "boss")
    return res


# ---------- Agent factory ----------

def build_agent(name: AgentName, output_type: type) -> Agent[TeamDeps, Any]:
    agent = Agent(
        MODEL,
        name=name,
        deps_type=TeamDeps,
        output_type=output_type,
        instructions=(PROMPTS_DIR / f"{name}.md").read_text(),
        toolsets=[mcp_tools_for(name)],
        tools=[DELEGATE_TOOL],
        model_settings=MODEL_SETTINGS,
        retries=2,
    )

    @agent.instructions
    def delegation_context(ctx: RunContext[TeamDeps]) -> str:
        chain = " -> ".join(ctx.deps.chain)
        others = [a for a in AGENT_NAMES if a not in ctx.deps.chain]
        can = ", ".join(others) if len(ctx.deps.chain) < MAX_DELEGATION_DEPTH else "nobody (depth limit)"
        mode = " DRY RUN: write tools are disabled." if ctx.deps.state.dry_run else ""
        return f"Current delegation chain: {chain}. You can delegate to: {can}.{mode}"

    agent.output_validator(check_resolution if output_type is TicketResolution else check_report)
    return agent
