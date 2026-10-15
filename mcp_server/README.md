# campus-customs MCP server

A FastMCP server (`server.py`) shared by all five Campus Customs agents (boss, inventory, accounting, facilities, customer service) and by Claude Code.

- **Database:** reads `data/campus_customs_new.db`, resolved relative to the file. Set `CAMPUS_CUSTOMS_DB` to point at a scratch copy instead.
- **No invented data:** every value comes from SQL. A lookup that finds nothing returns `{"error": ...}`.
- **Shop clock:** all date math uses `desk.date_today`, which tools return as `shop_date`, not the real date.

## Run / connect

```bash
venv/bin/python mcp_server/server.py        # stdio
venv/bin/python mcp_server/smoke_test.py    # launches it from .mcp.json, checks results against SQLite -> output/mcp_smoke.json
venv/bin/python mcp_server/smoke_test.py --post-run   # re-checks against the DB as it is now; adds "post_run_check" only
venv/bin/python -m pytest                    # 49 tests on a scratch copy of the original DB (tests/)
```

`.mcp.json` at the project root registers it as `campus-customs` (stdio). Claude Code and `backend/team.py` both launch it from that file.

## Tools (16)

| Tool | R/W | Returns | Tables |
|---|---|---|---|
| `check_stock(sku, size=None)` | R | Inventory rows (sku, name, size, qty, location), `total_qty`, `pricing` (unit_cost, list_price). Omit `size` for every size. | inventory, pricing |
| `get_invoice(invoice_id)` | R | Amount, due_date, status, description, vendor (name, specialty, lead_days), `days_overdue` (negative = not yet due). | invoices, vendors, desk |
| `get_lease(lease_id)` | R | space_name, landlord, monthly_rent, next_due, notes, `days_until_due` (negative = late). | leases, desk |
| `list_open_tickets()` | R | Every ticket not `resolved`, oldest first: id, type, requester, subject, status, created_at. | tickets, desk |
| `list_tickets()` | R | Every ticket (open or resolved) with status and `is_resolved`. | tickets, desk |
| `get_ticket(ticket_id)` | R | The full ticket row plus `shop_date`. | tickets, desk |
| `get_cash_position(account="checking")` | R | Balance, open invoices (with `days_overdue`), rent due within 30 days (with `days_until_due`), `total_obligations`, `balance_after_obligations`, `pending_approvals_total`, `upcoming_rent` (every lease's next rent however far out, with `counted_in_obligations`), and `warnings` (a next rent outside the 30-day window that the money left after obligations can't cover). | cash_accounts, invoices, vendors, leases, approvals, desk |
| `list_vendors(specialty=None)` | R | id, name, specialty, lead_days, `ready_date_if_ordered_today`. `specialty` is a case-insensitive substring ("apparel", "mug", "courier"). | vendors, desk |
| `quote_price(sku, qty, discount_pct=0, size=None, deposit_pct=0)` | R | list/unit price, total, list_total, unit_cost, unit_margin, margin_pct, `above_cost`. With `size`: on_hand, shortfall, reorder_cost. With `deposit_pct`: deposit_amount. A calculator; writes nothing. | pricing, inventory |
| `list_payments(kind=None, ref_id=None)` | R | Payments already made, optionally filtered by kind and ref_id. | payments |
| `list_approvals(status=None, ticket_id=None)` | R | Approval requests (pending / approved / rejected / failed), newest first. | approvals |
| `list_receipts(ticket_id=None)` | R | Money received (payer, amount, account, received_at, memo, recorded_by), oldest first, and `total`. Use it to confirm a deposit arrived before a reorder. | receipts |
| `request_approval(kind, ref_id, amount, reason, requested_by, ticket_id=None, status_after_approval=None, sku=None, size=None, qty=None)` | **W** (queue only) | Queues a payment (`invoice`: ref_id = invoice id; `rent`: ref_id = lease id) or a `purchase` (ref_id = vendor id, plus sku/size/qty) for a human. **Nothing is paid.** | approvals (validates against invoices, leases, vendors, pricing, inventory, cash_accounts) |
| `decide_approval(approval_id, decision, decided_by, account="checking")` | **W** | **Human only** (called by the desk API's approve/reject routes; no agent has it). `approved`: re-validates, then pays (payments row, lower balance, invoice `paid` or lease `next_due` +1 month) or raises the purchase as an open vendor invoice due on arrival, and sets the ticket to `status_after_approval`. `rejected`: nothing is paid and the ticket is escalated. | approvals, payments, cash_accounts, invoices, leases, tickets |
| `record_receipt(amount, payer, memo, recorded_by, ticket_id=None, account="checking")` | **W** | **Human only** (called by the desk API's `POST /receipts`; no agent has it). Adds a receipts row, raises the balance by exactly `amount`, and notes it on the linked ticket (status unchanged). Refuses a non-positive amount, a blank payer, memo or recorder, and an unknown ticket. | receipts, cash_accounts, tickets |
| `update_ticket(ticket_id, status, note, updated_by)` | **W** | Sets the status (open, in_progress, waiting_on_approval, waiting_on_customer, waiting_on_vendor, escalated, resolved) and appends `"[<shop_date> <updated_by>] <note>"` to the notes. | tickets, desk |

The `approvals` and `receipts` tables aren't in the original database. The server creates them on first connection, and again after a reset.

## Write safeguards

`request_approval` refuses, and `decide_approval` re-checks at approval time:
- an amount that doesn't exactly match the invoice amount or monthly rent, or, for a purchase, qty × unit_cost
- an invoice that isn't `open`, so nothing is paid twice
- rent more than 7 days before `next_due`
- a duplicate pending request for the same bill or item
- a payment that the balance, minus other pending payments, can't cover (approval also refuses an overdraft)

`decide_approval` also refuses an approval that is already decided, so a double click can't pay twice.

`update_ticket` refuses an unknown status, an empty note, or an empty `updated_by`.

On the agent side, `backend/team.py` gives `request_approval` and `update_ticket` to the Boss only and stamps `requested_by` / `updated_by` with the agent that actually made the call. No agent gets `decide_approval` or `record_receipt`: money only moves, in or out, when a person acts on the desk board. Every call is logged to `output/audit_trail.json`.
