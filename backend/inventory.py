"""Inventory agent: stock on hand, shortfalls, size alternatives, reorders and vendor lead times.

Prompt: prompts/inventory.md. MCP tools: team.AGENT_TOOLS["inventory"], plus team.delegate to reach any teammate.
Returns an AgentReport to whoever delegated to it.
"""

from models import AgentReport
from team import build_agent

AGENT = build_agent("inventory", AgentReport)
