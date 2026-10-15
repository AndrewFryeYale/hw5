"""Facilities agent: the shop space, the lease and landlord, aisle locations, pickup and courier logistics.

Prompt: prompts/facilities.md. MCP tools: team.AGENT_TOOLS["facilities"], plus team.delegate to reach any teammate.
Returns an AgentReport to whoever delegated to it.
"""

from models import AgentReport
from team import build_agent

AGENT = build_agent("facilities", AgentReport)
