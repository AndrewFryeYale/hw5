# Harness: Campus Customs multi-agent shop

Final reference for hw5. A team of five AI agents (**Boss, Inventory, Accounting, Facilities, Customer Service**) works the shop's ticket queue. Every shop fact comes from one MCP server, a human signs off on every dollar through a FastAPI desk API, and a React dashboard shows the whole thing live.

- Original data: `data/campus_customs.db`. It is never modified; `POST /reset` copies it back over the working copy.
- Working copy: `data/campus_customs_new.db`. Every write goes here, and only through the MCP server.

## Quick start

| What | Command (from `hw5/`) | Where |
|---|---|---|
| Desk API (FastAPI) | `cd backend && ../venv/bin/uvicorn main:app --reload --port 8000` | http://localhost:8000/docs |
| Dashboard (React + Vite + TS) | `cd frontend && npm install && npm run dev` | http://localhost:5173 |
| Agents from the command line | `venv/bin/python backend/run.py [--ticket N] [--dry-run]` | prints a summary to the terminal and writes `output/last_run.json` |
| MCP smoke test | `venv/bin/python mcp_server/smoke_test.py` | `output/mcp_smoke.json`; **overwrites it**, so run against the original data |
| MCP check after runs | `venv/bin/python mcp_server/smoke_test.py --post-run` | adds `post_run_check` to `output/mcp_smoke.json` (the Problem 4 evidence is kept) |
| Tests | `venv/bin/python -m pytest` | 49 tests on a scratch copy of the original DB; no LLM calls, real data untouched |

LLM calls go through Portkey (`https://api.portkey.ai/v1`, key from `PORTKEY_API_KEY`, model `gpt-5.6-luna`). The key is never printed, logged, or committed.

## System map

```
React dashboard (:5173) ──HTTP──▶ FastAPI desk API (:8000) ──┐
                                   │  runs the Boss agent      │ one stdio MCP connection
                                   ▼                           ▼
             Boss ⇄ Inventory ⇄ Accounting ⇄ Facilities ⇄ Customer Service
                     (Pydantic AI, gpt-5.6-luna via Portkey, delegate tool = full connectivity)
                                   │ every fact / write
                                   ▼
              campus-customs MCP server (FastMCP, 16 tools) ──▶ data/campus_customs_new.db
                                   │
                   every step ──▶ output/audit_trail.json (append-only)
```

## Database tables

### `desk` (1 row)
| Field | Type | Notes |
|---|---|---|
| date_today | TEXT | The shop's "today" (`2026-08-31`). |
| notes | TEXT | Free-form desk notes (currently empty). |

**Why it matters:** This is the shared clock. Every agent should use `date_today` instead of the real date when it judges what is due, overdue, or urgent.

### `inventory` (10 rows, PK = sku + size)
| Field | Type | Notes |
|---|---|---|
| sku | TEXT | Product code, e.g. `CC-TEE-WHITE`. |
| name | TEXT | Display name. |
| size | TEXT | S/M/L/XL, or OS (one size). |
| qty | INTEGER | Units on hand. |
| location | TEXT | Aisle in the shop (A–D). |

**Why it matters:** This is the Inventory agent's source of truth for stock. Customer Service needs it before promising an order, and Facilities uses `location` to find items. Two rows are already at 0: Tee S and Crest Mug.

### `pricing` (4 rows, PK = sku)
| Field | Type | Notes |
|---|---|---|
| sku | TEXT | Joins to `inventory.sku` and `tickets.sku`. |
| unit_cost | REAL | What the shop pays per unit. |
| list_price | REAL | Normal retail price. |

**Why it matters:** Accounting and the Boss use it to judge margin. The gap between `unit_cost` and `list_price` is the room available for any discount, such as the bulk-hoodie request. Customer Service quotes from `list_price`.

### `vendors` (3 rows)
| Field | Type | Notes |
|---|---|---|
| id | INTEGER | PK, referenced by `invoices.vendor_id`. |
| name | TEXT | Bulldog Print Co / Elm City Gifts / QuickShip CT. |
| specialty | TEXT | Apparel reprint / mugs and small goods / local courier. |
| lead_days | INTEGER | Days to deliver (5 / 3 / 1). |

**Why it matters:** Inventory decides who to reorder from. `lead_days` tells Customer Service what delivery date it can honestly promise.

### `leases` (1 row)
| Field | Type | Notes |
|---|---|---|
| id | INTEGER | PK, referenced by `tickets.lease_id`. |
| space_name | TEXT | Chapel Street shop. |
| landlord | TEXT | Elm City Properties. |
| monthly_rent | REAL | 2400.00. |
| next_due | TEXT | `2026-09-02`. |
| notes | TEXT | Empty. |

**Why it matters:** Facilities owns the physical space and the landlord relationship. Accounting has to fund the rent. A missed rent payment puts the whole shop at risk.

### `cash_accounts` (1 row)
| Field | Type | Notes |
|---|---|---|
| name | TEXT | PK, `checking`. |
| balance | REAL | 3400.00. |
| date | TEXT | Balance as of `2026-08-31`. |

**Why it matters:** This caps what Accounting can pay. Every payment decision has to check this balance first.

### `payments` (0 rows)
| Field | Type | Notes |
|---|---|---|
| id | INTEGER | PK. |
| kind | TEXT | What was paid, e.g. invoice or rent. |
| ref_id | INTEGER | ID of the invoice or lease being paid. |
| amount | REAL | Amount paid. |
| account | TEXT | Which `cash_accounts.name` was debited. |
| paid_at | TEXT | Timestamp. |
| approved_by | TEXT | Agent or person who approved it. |

**Why it matters:** This is the money audit trail and is empty so far. Accounting writes a row here (and decrements `cash_accounts`) for every payment. `approved_by` records which agent approved it, which suggests the Boss signs off on spending.

### `invoices` (1 row)
| Field | Type | Notes |
|---|---|---|
| id | INTEGER | PK, referenced by `tickets.invoice_id`. |
| vendor_id | INTEGER | FK → `vendors.id`. |
| amount | REAL | 840.00. |
| due_date | TEXT | `2026-08-28`. |
| status | TEXT | `open`. |
| description | TEXT | "Rush reprint CC-TEE-WHITE S". |

**Why it matters:** These are bills Accounting owes. Invoice 501 is already **3 days overdue** relative to `desk.date_today`.

### `tickets` (3 rows, all `open`)
| Field | Type | Notes |
|---|---|---|
| id | INTEGER | PK. |
| type | TEXT | customer_order / rent_notice / price_override. |
| requester | TEXT | Free-text name (there is no customers table). |
| subject | TEXT | Short title. |
| sku, size, qty | TEXT/TEXT/INT | Product request. Joins to `inventory` and `pricing`. |
| lease_id | INTEGER | FK → `leases.id`. |
| invoice_id | INTEGER | FK → `invoices.id`. |
| status | TEXT | `open`. |
| notes | TEXT | The request in plain words. |
| created_at | TEXT | ISO timestamp with timezone. |

**Why it matters:** This is the work queue. Each ticket's `type` determines which agent picks it up first, and its foreign keys pull in the other tables.


### `approvals` (added in Problem 7; created by the MCP server, not in the original DB)
| Field | Type | Notes |
|---|---|---|
| id | INTEGER | PK. |
| ticket_id | INTEGER | FK → `tickets.id`. |
| kind | TEXT | `invoice` / `rent` / `purchase`. |
| ref_id | INTEGER | Invoice id, lease id, or vendor id (for a purchase). |
| sku, size, qty | TEXT/TEXT/INT | Purchase only. |
| amount | REAL | Must equal the invoice amount, the monthly rent, or qty × unit_cost. |
| reason, requested_by | TEXT | Why the Boss asked, and who asked (stamped by the system). |
| status | TEXT | `pending` / `approved` / `rejected` / `failed`. |
| status_after_approval | TEXT | The ticket status to set once a human approves. |
| created_at, decided_by, decided_at, result | TEXT | The human decision and what it did (payment row, or new PO invoice). |

**Why it matters:** this is the line between the agents and the money. Agents can only add `pending` rows. Only a human click turns one into a payment.

### `receipts` (added in Problem 10; created by the MCP server, not in the original DB)
| Field | Type | Notes |
|---|---|---|
| id | INTEGER | PK. |
| ticket_id | INTEGER | FK → `tickets.id` (optional). |
| payer | TEXT | Who paid, e.g. "Yale AI Club". |
| amount | REAL | Dollars received (must be positive). |
| account | TEXT | `checking`. |
| received_at | TEXT | Shop date. |
| memo | TEXT | What it was for, e.g. "Deposit". |
| recorded_by | TEXT | `human:<name>`. |

**Why it matters:** money coming in. Before Problem 10 the database could only lose money, so a customer's deposit (the thing #103's reorder waits for) had nowhere to go. Only a person records a receipt, and checking goes up by exactly that amount.

Ticket statuses used by the system: `open`, `in_progress`, `waiting_on_approval`, `waiting_on_customer`, `waiting_on_vendor`, `escalated`, `resolved`.

## The three open tickets and how they connect

### #101 `customer_order`: Tauhid Zaman wants 1 Bulldog Tee, size S
- `inventory`: CC-TEE-WHITE S has **qty 0** (Aisle B), so the order can't be filled from stock.
- `invoice_id = 501`: a rush reprint of Tee S from **Bulldog Print Co** (vendor 1, 5 lead days) for $840. The invoice is **open and was due 2026-08-28**, so it's overdue.
- `pricing`: the tee sells for $28 and costs $8.
- **Agents involved:** Customer Service (customer), Inventory (stock and reprint), Accounting (overdue vendor bill). The reprint is likely held up until the vendor is paid.

### #102 `rent_notice`: Elm City Properties, rent due
- `lease_id = 1`: the Chapel Street shop costs $2,400 and is due **2026-09-02** (2 days after `date_today`).
- **Agents involved:** Facilities (landlord and space) and Accounting (payment).

### #103 `price_override`: Yale AI Club wants 20 Basic Hoodies, size M, with a bulk discount
- `inventory`: CC-HOOD-NAVY M has **only 8** on hand (32 across all sizes). Filling the order needs 12 more, most likely reprinted through Bulldog Print Co (5 days).
- `pricing`: list $58 and cost $22. At list price, 20 hoodies come to $1,160. Any discount has to stay above the $22 cost.
- **Agents involved:** Customer Service (customer), Inventory (shortfall), Accounting (margin), and the Boss (approving a price override is a policy decision).

### Cross-ticket tension: cash
- Checking holds **$3,400**.
- Invoice 501 ($840) plus rent ($2,400) comes to **$3,240**, which would leave **$160**.
- Both bills can be paid, but barely. A further reprint for #103 can't be funded until the hoodie order brings in money (for example, through a deposit).
- No single agent sees this whole picture, which is why the Boss and full connectivity between agents matter.

---

## MCP server: `campus-customs` (`mcp_server/server.py`)

- **Framework:** FastMCP, over stdio. `.mcp.json` registers it, and Claude Code, the agents (`backend/team.py`) and the desk API all launch it from that file. There is one connection per API process, shared by every agent.
- **Database:** `data/campus_customs_new.db`. `CAMPUS_CUSTOMS_DB` overrides the path for scratch tests.
- **No invented data:** every value is a SQL read. A missing record returns `{"error": ...}`, never a guess.
- **Shop clock:** all date math uses `desk.date_today` (2026-08-31), returned as `shop_date`. The tools compute `days_overdue`, `days_until_due` and `ready_date_if_ordered_today`, so agents never do date arithmetic.
- **Tools do the money math too:** `quote_price` and `get_cash_position` return totals, margins, deposits and balances.
- **Evidence:** `output/mcp_smoke.json` holds the Problem 4 connection test, checked value by value against a direct SQLite read (including calls made from Claude Code itself) on the pre-run data. Its `post_run_check` section re-checks 7 facts against the database after the final runs ($160.00, invoice 501 paid, lease next_due 2026-10-02, all tickets resolved); all match. `tests/` covers the tools on a scratch copy.
- **Docs:** `mcp_server/README.md`.

### Tools (16)
| Tool | R/W | Tables | Used by | Ticket it serves |
|---|---|---|---|---|
| `check_stock(sku, size?)` | R | inventory, pricing | inventory, facilities, customer_service | #101 (S = 0, alternatives), #103 (M = 8) |
| `get_invoice(invoice_id)` | R | invoices, vendors, desk | inventory, accounting | #101 (invoice 501, 3 days overdue) |
| `get_lease(lease_id)` | R | leases, desk | accounting, facilities | #102 (verify "due in 2 days") |
| `list_open_tickets()` | R | tickets, desk | boss, run.py | queue |
| `list_tickets()` | R | tickets, desk | API `/tickets` | dashboard queue |
| `get_ticket(ticket_id)` | R | tickets, desk | all agents, API | every ticket |
| `get_cash_position(account?)` | R | cash_accounts, invoices, vendors, leases, approvals, desk | boss, accounting, API `/cash` | #101/#102 cash priority, #103 reorder funding. Also `upcoming_rent` (every lease's next rent, even past the 30-day window) and `warnings` (next rent the cash can't cover) |
| `list_vendors(specialty?)` | R | vendors, desk | inventory, accounting, facilities, customer_service | #101/#103 ready dates |
| `quote_price(sku, qty, discount_pct?, size?, deposit_pct?)` | R | pricing, inventory | inventory, accounting, customer_service | #103 discount, margin, deposit, shortfall |
| `list_payments(kind?, ref_id?)` | R | payments | boss, accounting | no double payment |
| `list_approvals(status?, ticket_id?)` | R | approvals | boss, accounting, API `/approvals` | no duplicate requests |
| `list_receipts(ticket_id?)` | R | receipts | boss, accounting, API `/receipts` | #103: has the club's deposit arrived before the reorder? |
| `request_approval(kind, ref_id, amount, reason, requested_by, ticket_id?, status_after_approval?, sku?, size?, qty?)` | **W** (queue only) | approvals (validates against invoices, leases, vendors, pricing, inventory, cash_accounts) | **boss only** | #101 invoice, #102 rent |
| `decide_approval(approval_id, decision, decided_by)` | **W** | approvals, payments, cash_accounts, invoices, leases, tickets | **humans only**, via API approve/reject; no agent has it | the actual payment |
| `record_receipt(amount, payer, memo, recorded_by, ticket_id?)` | **W** | receipts, cash_accounts, tickets | **humans only**, via API `POST /receipts`; no agent has it | money in, e.g. #103's $464.00 deposit |
| `update_ticket(ticket_id, status, note, updated_by)` | **W** | tickets, desk | **boss only**, plus API `/resolve` for humans | status and notes log |

The agents also have one non-MCP tool: `delegate(to_agent, request)`. It hands work to a teammate and returns their report. It holds no shop data.

---

## Agents (`backend/`)

Five Pydantic AI agents on `gpt-5.6-luna` through Portkey. Each has a detailed prompt in `backend/prompts/<agent>.md`: role, ground rules, tools, workflow, policies, output format and token habits.

| Agent | File / prompt | Job | Output | MCP tools | Tables it reaches |
|---|---|---|---|---|---|
| **Boss** | `boss.py` / `prompts/boss.md` | Triage and route each ticket (lean plan first), decide, request payment or purchase approvals, set ticket status. The only agent that writes, and it still can't pay. | `TicketResolution` | `get_ticket`, `list_open_tickets`, `get_cash_position`, `list_payments`, `list_approvals`, `list_receipts`, **`request_approval`**, **`update_ticket`** | tickets, desk, cash_accounts, invoices, vendors, leases, payments, approvals, receipts |
| **Inventory** | `inventory.py` / `prompts/inventory.md` | Stock, shortfalls, size alternatives, reorder vendor and ready date, vendor bills blocking a reorder. | `AgentReport` | `get_ticket`, `check_stock`, `list_vendors`, `get_invoice`, `quote_price` | tickets, inventory, pricing, vendors, invoices, desk |
| **Accounting** | `accounting.py` / `prompts/accounting.md` | Cash position, payment priority, verifying bills, discount margin and deposit. Recommends only. | `AgentReport` | `get_ticket`, `get_invoice`, `get_lease`, `get_cash_position`, `list_payments`, `list_approvals`, `list_receipts`, `quote_price`, `list_vendors` | tickets, invoices, vendors, leases, cash_accounts, payments, approvals, receipts, pricing, inventory, desk |
| **Facilities** | `facilities.py` / `prompts/facilities.md` | Lease and landlord checks (including scam-style notices), aisle locations, pickup and courier. | `AgentReport` | `get_ticket`, `get_lease`, `check_stock`, `list_vendors` | tickets, leases, inventory, pricing, vendors, desk |
| **Customer Service** | `customer_service.py` / `prompts/customer_service.md` | Drafts every message to a customer or landlord, using only tool-backed numbers. | `AgentReport` with `customer_message_draft` | `get_ticket`, `check_stock`, `quote_price`, `list_vendors` | tickets, inventory, pricing, vendors, desk |

### Supporting files
| File | Role |
|---|---|
| `backend/models.py` | Data types: `AgentReport`, `Fact`, `TicketResolution`, `ApprovalRequested`, `TeamDeps` / `TicketState` (run context), `AuditEntry`. |
| `backend/team.py` | Portkey model, the shared MCP connection, per-agent tool filters, the audit hook on every MCP call, `delegate`, output validators, budgets, `build_agent`. |
| `backend/audit.py` | Appends to `output/audit_trail.json`. |
| `backend/run.py` | The command-line ticket loop (`work_ticket` is also what the API runs). |
| `backend/main.py` | FastAPI desk API (below). |

### Agent loop and delegation
1. **One ticket = one Boss run** with its own budget. The Boss reads the ticket (`get_ticket`), delegates focused questions, decides, queues approvals if the policy allows, calls `update_ticket` once, and returns a `TicketResolution`.
2. **Inside each agent:** Pydantic AI loops model → tool calls → model until it produces its typed output. Output validators can reject it (up to 2 retries).
3. **Full connectivity:** every agent has `delegate` and can reach any of the other four. The teammate runs with its own prompt and tools and returns an `AgentReport`.
4. **Loop guards:**
   - no delegating to yourself, or to anyone above you in the chain (no cycles)
   - at most 3 agents deep; at the bottom of the chain `delegate` is hidden from the model
   - at most 8 delegations per ticket
   - every agent on a ticket shares one usage budget
5. **Specialists report up:** a specialist reaches the Boss by returning `needs_boss_approval=true` in its report. The Boss is always the root of the chain.
6. **Lean routing (Problem 10):** the Boss prompt's routing table is a lean plan per ticket type with "add a teammate only if…" conditions, not a list of everyone who might help:
   - `customer_order`: Inventory, then the Boss checks cash itself, then Customer Service
   - `rent_notice`: Accounting only (Facilities only if the lease doesn't match the notice)
   - `price_override`: Accounting's one `quote_price`, then Customer Service
   Customer Service always goes last, with the decision and the customer-safe facts pasted in, so it drafts without lookups or delegation.

---

## Desk API routes (`backend/main.py`, FastAPI on :8000)

- `GET /tickets`: every ticket with its status, `state` (open/resolved), and whether agents are working on it.
- `GET /tickets/{ticket_id}`: one ticket in full, with its notes log, its approvals, its receipts, and whether it's running.
- `POST /tickets/{ticket_id}/run`: starts the Boss agent (and its delegates) on that ticket in the background. `?wait=true` blocks; body `{"dry_run": true}` blocks writes; returns 409 if already running.
- `GET /runs/{run_id}`: whether a run is running, finished or failed, plus the Boss's `TicketResolution`.
- `GET /events?since=&limit=&ticket_id=&run_id=`: what each agent said, every delegation and every MCP tool call, for the board to poll. Also returns `latest_seq` and `last_reset_seq`.
- `GET /approvals?status=pending&ticket_id=`: payments and purchases the agents asked for that are waiting for a human.
- `POST /approvals/{approval_id}/approve`: the human Approve click (body `{"decided_by": "name"}`). It pays the invoice or rent, or raises the purchase order, then moves the ticket to its `status_after_approval`.
- `POST /approvals/{approval_id}/reject`: the human Reject click. Nothing is paid and the ticket is escalated.
- `POST /tickets/{ticket_id}/resolve`: a person closes a ticket with a note. Refused while agents run or while a check is unsigned.
- `GET /cash`: the checking balance from `cash_accounts`, plus the pending-approval total, the balance after obligations, every lease's next rent and any warnings.
- `POST /receipts`: a person records money received (body `{"amount", "payer", "memo", "received_by", "ticket_id"?}`). Checking goes up by exactly that amount, and the ticket log notes it.
- `GET /receipts?ticket_id=`: money received so far.
- `POST /reset`: restores `campus_customs_new.db` from the original `campus_customs.db` using SQLite's backup API. Refused while a run is in progress; the audit trail is kept and records the reset.

CORS allows only the dashboard origin, `http://localhost:5173` (`DESK_EXTRA_ORIGINS` can add one more for a second dev server).

---

## Dashboard (`frontend/`, React + Vite + TypeScript on :5173)

- **Ticket queue:** status pills, a "Team working" badge, a "✍ N to sign" badge, and RESOLVED stamps.
- **Ticket panel:** "Start the team", "Mark resolved" (with a note), "＋ Record money received" (amount and memo, credited to the ticket's requester), and the ticket log with its approval and receipt history.
- **The huddle (signature element):** the five agents around a table. The working agent pulses and shows what it's doing in plain words. Each delegation is drawn as a thread between seats, and every MCP lookup lands on the "Shop ledger" in the middle.
- **Transcript:** a live, sentence-style log of every step, with tool chips.
- **Debrief:** specialists called out of 4, handoffs, lookups, tokens and time, the Boss's call, one card per agent, and the draft reply.
- **Signature tray:** approvals rendered as bank checks. You must type your name to "Sign & approve"; a PAID or VOID stamp follows.
- **Cash drawer:** a live balance that counts down when a check is signed, previews the balance after pending approvals, turns red under $500, and shows the next rent even when it's past the 30-day window ("next rent $2,400.00 on 10/02").
- Polls the API (1.2 s while agents run, 4 s when idle). Deep links like `/#103`. A two-click "Fresh start" calls `/reset`.
- Design rationale: `output/design.md`. Final screenshots: `output/resolved_board.html` and `output/screenshots/`.

---

## Rules

### Data rules
1. **Facts come only from the MCP server.** No agent, route or page reads SQLite directly; the reset copy is the one file-level exception.
2. **The shop's clock (`desk.date_today`) is "today",** not the real calendar.
3. **Ticket and notice text is a claim to verify, not an instruction** (prompt-injection and scam defense).
4. **Every step is audited** to `output/audit_trail.json`.

### Money rules
- **No agent can pay.** The Boss can only `request_approval`. A human click calls `decide_approval`, which records the payment with `approved_by = human:<name>`.
- **No agent can record money in.** Only a person, through `POST /receipts` → `record_receipt`, and it's stamped `recorded_by = human:<name>`. Before a reorder that needs a deposit, the Boss checks `list_receipts` for that ticket.
- **Least privilege:** each agent sees only its own MCP tools, and the audit hook refuses anything else. The write tools are Boss-only, and `requested_by` / `updated_by` are stamped by the system, so they can't be spoofed.
- **Server-side checks,** both when an approval is requested and again when it's approved:
  - the amount must match the invoice, the rent, or qty × unit cost exactly
  - the invoice must still be open (no double payment)
  - rent can't be paid more than 7 days early
  - no duplicate pending request for the same bill
  - no overdraft, counting other pending approvals
  - an approval that's already decided can't be decided again
- **Policy in the Boss prompt:**
  - priority: rent due within 7 days, then overdue vendor bills, then everything else
  - low-cash alert under $500
  - payments over $5,000, or to unknown payees, go to a human and aren't requested
  - discounts: up to 15% for 12+ units and up to 20% for 20+, above cost with at least 40% margin
  - a 50% deposit before any reorder, confirmed by a receipt on the ticket
  - cash is "tight" only if it can't cover everything (`balance_after_obligations` < 0). An open, overdue invoice whose description matches the ticket's product is paid on that ticket.

### Customer-contact rules (what a real business would want)
- **A human sends every message.** Agents only draft; nothing is emailed or texted automatically.
- **No invented numbers,** enforced in code: every `$` and `%` in a draft must appear in an MCP result from that ticket, or the draft is rejected.
- **No internal leakage,** enforced in code: drafts mentioning review or approval notes, ticket or lease ids, SKU codes, or the shop's internal finances ("invoice", "overdue", "margin", "unit cost") are rejected. The prompts also bar costs, the cash balance, vendor bills and other customers, and the Boss pastes only customer-safe facts into Customer Service's request.
- **Honest dates and offers:** restock dates come from vendor lead times ("around …"), and discounts are only ones the Boss approved. Drafts never say something "was paid" before a human approves it.
- **Privacy:** agents never ask for card numbers, passwords or student IDs.
- **Escalation:** complaints, legal or safety issues, conflicting data or policy exceptions set `needs_human` or `escalated`.

### Token-efficiency rules
- **Small model:** `gpt-5.6-luna` for all five agents.
- **Fewer tool schemas:** each agent sees only its 4–8 MCP tools plus one `delegate` tool, and `delegate` is hidden at the depth limit.
- **Tools do the math** (`quote_price`, `get_cash_position`, `list_vendors`), saving round trips and avoiding arithmetic errors.
- **Compact handoffs:** typed reports, not transcripts. Prompts say: one complete question per teammate, pass ids along, don't re-fetch, don't call specialists with nothing to add.
- **Lean routing:** a lean plan per ticket type with "add only if…" conditions. Customer Service goes last with the facts pasted in. Inventory makes one `check_stock` without a size. The Boss relies on `request_approval`'s own duplicate checks.
- **Hard caps per ticket, shared by every agent on it:** 40 requests, 60 tool calls, 250k tokens, 3,000 output tokens per response, 8 delegations, depth 3.
- **Measured:**

  | Run | Agent runs | Delegations | MCP calls | Tokens |
  |---|---|---|---|---|
  | Lean plan (Problem 6) | 3 | 5 | 17 | – |
  | Problem 9 (old routing table) | 4 | 13 | 53 | ≈ 199k |
  | Final (Problem 10 prompts) | 3 | 5 | 18 | ≈ 128k |

  Lookups now match the plan. Tokens are the next thing to cut: the Boss's long prompt is re-sent on each of its model requests and is now most of the bill (about 42k of #101's 54k).

---

## Audit trail (`output/audit_trail.json`)

- **One JSON array that only grows.** It is rewritten after every append, so a crash loses nothing logged so far.
- **Every entry has:** `seq`, `ts`, `run_id`, `event`, `agent`, `ticket_id`, the delegation `chain`, and `details`.
- **Events:**
  - `run_started` / `run_finished`
  - `ticket_started` / `ticket_finished` / `ticket_failed`
  - `agent_started` / `agent_finished` (with the agent's output and token usage)
  - `delegation` / `delegation_blocked`
  - `mcp_tool_call` (with args and result) / `mcp_tool_blocked`
  - `output_rejected`
  - human actions from the API: `api_ticket_run`, `api_approval_decided`, `api_ticket_resolved`, `api_receipt_recorded`, `api_database_reset`
- **What it contains:**
  - seq 1–82: the Problem 5 runs (from before the approval flow existed)
  - seq 83: the reset
  - seq 84–200: the Problem 9 runs (old routing table)
  - seq 201: reset; seq 202–219: a first run of #101 with the new prompts, discarded because its reply told the customer about "the invoice" (the guardrail was tightened)
  - seq 220: the reset before the final runs
  - seq 221–272: the final runs and human actions (Problem 10)

---

## Final run: after `POST /reset` (audit seq 220), with the Problem 10 prompts

| Ticket | Boss called first | Delegations | MCP calls | Human action | Final status | Cash |
|---|---|---|---|---|---|---|
| #101 tee | Inventory | boss→inventory, boss→customer_service | 7 | approved #1, invoice 501, $840.00; marked resolved after the reply was sent | resolved | $3,400.00 → $2,560.00 |
| #102 rent | Accounting | boss→accounting | 7 | approved #2, rent lease 1, $2,400.00 | resolved (through the approval) | $2,560.00 → $160.00 |
| #103 hoodies | Accounting | boss→accounting, boss→customer_service | 4 | marked resolved after the quote was sent (20% off, $46.40/unit, $928.00, $464.00 deposit) | resolved | no change |

**Cash check:** $3,400.00 − $840.00 − $2,400.00 − $0.00 = **$160.00**. That equals `cash_accounts.balance` and the `payments` table: 2 rows totalling $3,240.00, both `approved_by human:andrew`. The `receipts` table is empty. This matches the expected ledger in `output/desk_tickets.html` line for line, including the order.

**Compared with Problem 9:**
- Problem 9 took 4 agent runs, 13 delegations and 53 MCP calls. On #101's first run the Boss declined to request invoice 501 "because rent was due", even though cash covered both bills.
- The final run has 1 run per ticket, 5 delegations and 18 MCP calls, the same as the Problem 6 plan.
- #101 and #103 still end at `waiting_on_customer` by design, since agents can't hear back from real customers. A person closed them with notes recording what is still pending outside the system.

**Details:**
- `output/desk_tickets.html`: expected vs actual per ticket, the cash tab and reflections.
- `output/resolved_tickets.json`: a per-ticket record.
- `output/resolved_board.html`: screenshots of the final board.

## Tests (`tests/`, `venv/bin/python -m pytest`)

49 tests. They run on a scratch copy of `data/campus_customs.db` with a scratch audit trail (`tests/conftest.py`), make no LLM calls, and never touch the working database.

| File | What it proves |
|---|---|
| `test_mcp_reads.py` | The read tools return exactly the database's values for #101, #102 and #103, return errors instead of guesses for unknown ids, and never write. |
| `test_money.py` | Requesting moves no money. A human approval moves exactly the approved amount, once, with `approved_by = human:<name>`. The Problem 9 math ties out ($3,400.00 − $840.00 − $2,400.00 = $160.00). Wrong amounts, duplicates, double payments, early rent and overdrafts are refused. Rejections pay nothing. Purchases raise a PO without moving cash. Next month's rent is visible. Receipts add exactly their amount. |
| `test_guardrails.py` | No agent has `decide_approval` or `record_receipt`, and only the Boss has write tools. Tools outside an agent's list are blocked. Writers are stamped with the real agent. Dry runs block writes. Delegation guards work (self, cycle, depth, budget). Invented $ and % are caught, and so is internal wording in customer messages. |
| `test_api.py` | The desk API end to end over a real MCP server process: tickets, cash, approve and reject clicks, money in, resolve guards, and reset. |

## Output files

| File | What it is |
|---|---|
| `output/harness.md` | This document. |
| `output/mcp_smoke.json` | Problem 4 MCP connection and value check, plus a `post_run_check` against the final database. |
| `output/audit_trail.json` | Append-only log of every agent, tool and human action. |
| `output/last_run.json` | Last command-line `run.py` summary (Problem 5). |
| `output/desk_tickets.html` | Expected (Problem 6) vs actual (final run, with Problem 9 for comparison) per ticket, cash, reflections. |
| `output/design.md` | Dashboard design choices. |
| `output/resolved_tickets.json` | Final status, outcome, agent contributions and human approvals per ticket. |
| `output/resolved_board.html`, `output/screenshots/` | Screenshots of the final React board for each resolved ticket. |
| `output/github_url.txt` | The public GitHub repo URL. |
