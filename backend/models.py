"""Data types shared by the Campus Customs agent team.

- AgentReport: what every specialist (inventory, accounting, facilities, customer service) hands back
  when another agent delegates to it.
- TicketResolution: what the Boss returns for each ticket once it has decided and acted.
- TeamDeps / TicketState: per-run context passed to every agent and tool (who is running, the delegation
  chain, budgets, and what the MCP server has returned so far).
- AuditEntry: one row of output/audit_trail.json.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

AgentName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]
AGENT_NAMES: tuple[AgentName, ...] = ("boss", "inventory", "accounting", "facilities", "customer_service")

TicketStatus = Literal["open", "in_progress", "waiting_on_approval", "waiting_on_customer", "waiting_on_vendor", "escalated", "resolved"]

AuditEvent = Literal[
    "run_started", "run_finished",
    "ticket_started", "ticket_finished", "ticket_failed",
    "agent_started", "agent_finished",
    "delegation", "delegation_blocked",
    "mcp_tool_call", "mcp_tool_blocked",
    "output_rejected",
    "api_ticket_run", "api_approval_decided", "api_database_reset", "api_ticket_resolved",
    "api_receipt_recorded",
]


# ---------- Agent outputs ----------

class Fact(BaseModel):
    """One shop fact an agent relied on, with the MCP tool it came from."""

    name: str = Field(description="What the value is, e.g. 'CC-HOOD-NAVY M on hand'.")
    value: str = Field(description="The value exactly as the tool returned it.")
    source_tool: str = Field(description="The MCP tool that returned it, e.g. 'check_stock'.")


class AgentReport(BaseModel):
    """A specialist's answer to a delegated request."""

    agent: AgentName
    summary: str = Field(description="Two to four sentences answering the request.")
    facts: list[Fact] = Field(default_factory=list, description="Only the facts the summary depends on.")
    recommended_actions: list[str] = Field(
        default_factory=list, description="Concrete next steps, each one sentence, in priority order.")
    needs_boss_approval: bool = Field(
        default=False, description="True if any recommended action spends money, changes a price or commits the shop.")
    blockers: list[str] = Field(default_factory=list, description="Anything stopping the work, e.g. an unpaid vendor.")
    customer_message_draft: str | None = Field(
        default=None, description="Customer service only: a draft reply to the customer. Never sent automatically.")


class ApprovalRequested(BaseModel):
    """A payment or purchase the Boss queued with request_approval (copied from the tool result).
    Nothing is paid until a human approves it on the board."""

    approval_id: int
    kind: Literal["invoice", "rent", "purchase"]
    ref_id: int
    amount: float


class TicketResolution(BaseModel):
    """The Boss's final word on one ticket."""

    ticket_id: int
    ticket_type: str
    decision: str = Field(description="What was decided and why, in three to five sentences.")
    agents_consulted: list[AgentName] = Field(default_factory=list)
    approvals_requested: list[ApprovalRequested] = Field(
        default_factory=list, description="Only approvals request_approval actually queued on this ticket.")
    price_approved: str | None = Field(
        default=None, description="For price overrides: the approved unit price, discount and total, or null.")
    new_status: TicketStatus
    customer_message: str | None = Field(
        default=None, description="Final draft for the requester. Queued for human review, never auto-sent.")
    needs_human: bool = Field(description="True if a person must approve or act before this ticket can close.")
    human_reasons: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)


# ---------- Run context ----------

@dataclass
class TicketState:
    """Shared by every agent working on the same ticket (the Boss and everyone it delegates to)."""

    ticket_id: int | None
    dry_run: bool = False
    delegations: int = 0
    # Every number any MCP tool has returned on this ticket, used to check customer drafts for invented prices.
    seen_numbers: set[float] = field(default_factory=set)
    # Successful request_approval results, used to check the Boss's approvals_requested claims.
    approvals: list[dict[str, Any]] = field(default_factory=list)
    agents_used: set[str] = field(default_factory=set)


@dataclass
class TeamDeps:
    """Passed to every agent run. `chain` is the delegation path, e.g. ('boss', 'customer_service')."""

    agent: AgentName
    run_id: str
    chain: tuple[AgentName, ...]
    state: TicketState


# ---------- Audit ----------

class AuditEntry(BaseModel):
    """One line of output/audit_trail.json."""

    seq: int
    ts: str
    run_id: str
    event: AuditEvent
    agent: AgentName | None = None
    ticket_id: int | None = None
    chain: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
