"""Customer Service agent: every message to a customer or other requester. It drafts; a person approves before anything is sent.

Prompt: prompts/customer_service.md. MCP tools: team.AGENT_TOOLS["customer_service"], plus team.delegate to reach any teammate.
Returns an AgentReport (with customer_message_draft) to whoever delegated to it.
"""

from models import AgentReport
from team import build_agent

AGENT = build_agent("customer_service", AgentReport)
