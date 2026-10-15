"""Boss agent: the team lead. Every ticket starts here; it delegates, decides, and is the only agent that can pay bills or change a ticket.

Prompt: prompts/boss.md. MCP tools: team.AGENT_TOOLS["boss"], plus team.delegate to reach any teammate.
Returns a TicketResolution.
"""

from models import TicketResolution
from team import build_agent

AGENT = build_agent("boss", TicketResolution)
