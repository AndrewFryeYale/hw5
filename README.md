# Campus Customs: multi-agent shop desk (hw5)

A team of five AI agents (**Boss, Inventory, Accounting, Facilities, Customer Service**) works the ticket queue of Campus Customs, a student shop on Chapel Street.

- **Facts:** every shop fact comes from one MCP server (`mcp_server/server.py`) over a SQLite database.
- **Money:** agents can only *request* a payment. A person approves it on the desk board, and money only moves then.
- **API:** a FastAPI backend runs the agents and exposes the desk.
- **Dashboard:** a React board shows the team working live.

The model is `gpt-5.6-luna`, called through Portkey.

The full reference (tables, tools, agents, routes, rules, results) is in [`output/harness.md`](output/harness.md).

## What's where

| Path | What it is |
|---|---|
| `data/campus_customs.db` | The original shop data. Never modified. |
| `data/campus_customs_new.db` | The working copy every write goes to. As committed, it holds the final state after the graded run: all three tickets resolved, checking at $160.00. |
| `mcp_server/` | The `campus-customs` MCP server (FastMCP, 16 tools), its README, and a smoke test. |
| `.mcp.json` | Registers the MCP server (stdio). Claude Code, the backend and the smoke test all launch it from here. |
| `backend/` | The agents (`team.py` and one file per agent), prompts in `backend/prompts/`, data types in `models.py`, the audit log writer, the command-line runner `run.py`, and the FastAPI app `main.py`. |
| `frontend/` | The React + Vite + TypeScript desk board. |
| `tests/` | 49 tests on a scratch copy of the original database. No LLM calls. |
| `output/` | The deliverables: harness, smoke evidence, expected vs. actual, design notes, resolved tickets and board, audit trail, repo URL. |
| `AI_prompts.md` | Every prompt used to build this. |

## Setup (once)

You need Python 3.12+ and Node 20.19+ (or 22.12+).

```bash
cd hw5
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env                 # then put your PORTKEY_API_KEY in .env (or export it in your shell)
cd frontend && npm install && cd ..
```

On Windows, use `venv\Scripts\python` wherever this README says `venv/bin/python`, and edit `command` in `.mcp.json` to match.

## Running it

### 1. Start from clean data (copy the original DB to the working copy)

The committed working copy is the *finished* state. For a clean run, copy the original over it while nothing is running:

```bash
cp data/campus_customs.db data/campus_customs_new.db
```

When the backend is already running, use its reset instead (step 5). It does the same copy safely.

### 2. The MCP server

You normally don't start it by hand. The backend (step 3) launches it from `.mcp.json` when it starts, and so does Claude Code when you open this folder. To start it or check it on its own:

```bash
venv/bin/python mcp_server/server.py                    # runs the server over stdio (Ctrl-C to stop)
venv/bin/python mcp_server/smoke_test.py --post-run     # launches it from .mcp.json and checks its answers against the DB
```

`mcp_server/smoke_test.py` with no flag rewrites the Problem 4 evidence in `output/mcp_smoke.json`. Only run it that way on fresh data.

### 3. Start the FastAPI backend

```bash
cd backend
../venv/bin/uvicorn main:app --reload --port 8000
```

API docs are at http://localhost:8000/docs.

### 4. Start the React board

In a second terminal:

```bash
cd frontend
npm run dev
```

Then open http://localhost:5173.

### 5. Reset the DB before a full three-ticket run

Reset before every full run, so the team starts from the original data: checking $3,400.00, three open tickets, nothing paid. Use either:
- the **Fresh start** button on the board (click it twice), or
- `curl -X POST http://localhost:8000/reset`

Both copy `campus_customs.db` over `campus_customs_new.db`. The audit trail is kept and records the reset.

Then work the tickets:

1. Pick a ticket on the board and click **Start the team**.
2. Watch the huddle while the agents work.
3. When the Boss asks for a payment, type your name on the check in the signature tray and **Sign & approve**.
4. Close tickets that are waiting on the customer with **Mark resolved**.

The graded run worked #101, then #102, then #103, and ended at $3,400.00 − $840.00 − $2,400.00 = **$160.00**.

To work every open ticket from the command line instead (approvals are still left for a person to sign on the board):

```bash
venv/bin/python backend/run.py            # or --ticket 101, or --dry-run to block all writes
```

### Tests

```bash
venv/bin/python -m pytest
```

## Rules the code enforces

- The real `.env` is never committed. The Portkey key is read from the environment and never printed or logged.
- No agent can pay or record money in. `decide_approval` and `record_receipt` are human-only and are called by the API's approve and receipt routes.
- Customer messages are drafts a person sends. Any `$` or `%` a tool didn't return, and any internal wording, is rejected.
- Every agent step, tool call and human action is appended to `output/audit_trail.json`.
