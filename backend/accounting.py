"""Accounting agent: invoices, cash position, rent funding, margins, discounts and deposits. It recommends payments; only the Boss records them.

Prompt: prompts/accounting.md. MCP tools: team.AGENT_TOOLS["accounting"], plus team.delegate to reach any teammate.
Returns an AgentReport to whoever delegated to it.
"""

from models import AgentReport
from team import build_agent

AGENT = build_agent("accounting", AgentReport)
