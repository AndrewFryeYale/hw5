"""Agent guardrails in backend/team.py, tested without calling the model."""

import asyncio
from types import SimpleNamespace

import pytest

import server
import team
from models import TeamDeps, TicketState

HUMAN_ONLY = {"decide_approval", "record_receipt"}


def ctx(agent="boss", chain=("boss",), dry_run=False, delegations=0):
    state = TicketState(ticket_id=101, dry_run=dry_run, delegations=delegations)
    return SimpleNamespace(deps=TeamDeps(agent=agent, run_id="test", chain=chain, state=state))


def test_no_agent_can_approve_or_record_money():
    for agent, tools in team.AGENT_TOOLS.items():
        assert not tools & HUMAN_ONLY, agent
        if agent != "boss":
            assert not tools & team.WRITE_TOOLS, agent


def test_every_allowed_tool_exists_on_the_server():
    for tools in team.AGENT_TOOLS.values():
        for name in tools:
            assert callable(getattr(server, name, None)), name


def test_tool_outside_an_agents_list_is_blocked():
    called = []

    async def call_tool(name, args):
        called.append(name)
        return {}

    out = asyncio.run(team.audit_mcp_call(ctx("inventory", ("boss", "inventory")), call_tool, "request_approval", {}))
    assert "error" in out and called == []


def test_writer_is_stamped_with_the_real_agent():
    seen = {}

    async def call_tool(name, args):
        seen.update(args)
        return {"ticket": {"id": 101}}

    asyncio.run(team.audit_mcp_call(ctx(), call_tool, "update_ticket",
                                    {"ticket_id": 101, "status": "open", "note": "x", "updated_by": "accounting"}))
    assert seen["updated_by"] == "boss"


def test_dry_run_blocks_writes():
    async def call_tool(name, args):
        raise AssertionError("write reached the server in a dry run")

    out = asyncio.run(team.audit_mcp_call(ctx(dry_run=True), call_tool, "request_approval", {"amount": 840}))
    assert "Dry run" in out["error"]


@pytest.mark.parametrize("agent, chain, to_agent, delegations, why", [
    ("boss", ("boss",), "boss", 0, "yourself"),
    ("inventory", ("boss", "inventory"), "boss", 0, "already working"),
    ("accounting", ("boss", "customer_service", "accounting"), "facilities", 0, "depth limit"),
    ("boss", ("boss",), "inventory", team.MAX_DELEGATIONS_PER_TICKET, "used its"),
])
def test_delegation_guards(agent, chain, to_agent, delegations, why):
    out = asyncio.run(team.delegate(ctx(agent, chain, delegations=delegations), to_agent, "help"))
    assert why in out["error"]


def test_invented_numbers_are_caught():
    seen = {46.4, 928.0, 464.0, 20.0, 1160.0}
    assert team.unverified_numbers("20% off: $46.40 each, $928.00 total, $464.00 deposit (was $1,160.00).", seen) == []
    assert team.unverified_numbers("Only $45.00 each, 25% off!", seen) == ["$45.00", "25%"]


@pytest.mark.parametrize("text", [
    "Your rent payment is pending approval.",
    "We paid invoice 501.",
    "The reprint waits until the invoice is processed.",
    "Our margin is thin on this one.",
    "The CC-TEE-WHITE is out.",
    "Here is a draft reply.",
])
def test_internal_wording_never_reaches_a_customer(text):
    assert "internal wording" in team.message_problems(text, set())


def test_a_clean_message_passes():
    msg = "Hello Tauhid, the Classic Bulldog Tee is out in size S. Sizes M, L and XL are in stock. Campus Customs"
    assert team.message_problems(msg, set()) is None
