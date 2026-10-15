"""Campus Customs MCP server.

Shared tool server for all five agents (boss, inventory, accounting,
facilities, customer service). Reads data/campus_customs_new.db only —
every value returned comes straight from the database; tools never guess.

Read tools never change the database. Agents never move money directly: they
call request_approval, which queues a payment or purchase in the approvals
table. A human then approves it through the FastAPI board (decide_approval),
and only then is the payment recorded or the purchase order raised. Every
write is validated against the database first, so nothing can pay the wrong
amount, overdraw the account, or pay a bill twice. Money coming in (a customer
deposit) is recorded by a human the same way, with record_receipt.

CAMPUS_CUSTOMS_DB overrides the database path (used for dry runs on a scratch
copy); by default the server uses data/campus_customs_new.db.
"""

import calendar
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from fastmcp import FastMCP

DB_PATH = Path(
    os.environ.get("CAMPUS_CUSTOMS_DB")
    or Path(__file__).resolve().parent.parent / "data" / "campus_customs_new.db"
)

TICKET_STATUSES = (
    "open", "in_progress", "waiting_on_approval", "waiting_on_customer", "waiting_on_vendor",
    "escalated", "resolved",
)
APPROVAL_KINDS = ("invoice", "rent", "purchase")

# The approvals queue isn't in the original database, so the server adds it on first use (and again after a reset).
APPROVALS_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER,
    kind TEXT NOT NULL,              -- invoice | rent | purchase
    ref_id INTEGER NOT NULL,         -- invoice id | lease id | vendor id
    sku TEXT, size TEXT, qty INTEGER, -- purchase only
    amount REAL NOT NULL,
    reason TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    status TEXT NOT NULL,            -- pending | approved | rejected | failed
    status_after_approval TEXT,      -- ticket status to set once approved
    created_at TEXT NOT NULL,
    decided_by TEXT, decided_at TEXT, result TEXT,
    FOREIGN KEY (ticket_id) REFERENCES tickets(id)
)"""
# Money coming in (customer deposits and payments). Also not in the original database.
RECEIPTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER,
    payer TEXT NOT NULL,
    amount REAL NOT NULL,
    account TEXT NOT NULL,
    received_at TEXT NOT NULL,       -- shop date
    memo TEXT NOT NULL,
    recorded_by TEXT NOT NULL,       -- human:<name>
    FOREIGN KEY (ticket_id) REFERENCES tickets(id)
)"""
# get_cash_position counts rent due within this many days as an obligation.
OBLIGATION_WINDOW_DAYS = 30
# Rent can be paid at most this many days before it is due (stops paying a month twice).
RENT_EARLY_WINDOW_DAYS = 7

mcp = FastMCP("campus-customs")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(APPROVALS_SCHEMA)
    conn.execute(RECEIPTS_SCHEMA)
    return conn


def _shop_today(conn: sqlite3.Connection) -> str:
    """The shop's clock lives in desk.date_today, not the real calendar."""
    return conn.execute("SELECT date_today FROM desk").fetchone()["date_today"]


def _days_between(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _add_days(start: str, days: int) -> str:
    return (date.fromisoformat(start) + timedelta(days=days)).isoformat()


def _add_month(start: str) -> str:
    d = date.fromisoformat(start)
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return d.replace(year=year, month=month, day=min(d.day, calendar.monthrange(year, month)[1])).isoformat()


@mcp.tool
def check_stock(sku: str, size: str | None = None) -> dict:
    """Look up on-hand stock and pricing for a product.

    Returns each matching inventory row (sku, name, size, qty, location)
    plus the product's unit_cost and list_price. Pass `size` to get one
    size; omit it to get every size of the SKU.
    """
    with _connect() as conn:
        query = "SELECT sku, name, size, qty, location FROM inventory WHERE sku = ?"
        params: list = [sku]
        if size is not None:
            query += " AND size = ?"
            params.append(size)
        rows = [dict(r) for r in conn.execute(query, params)]
        if not rows:
            return {"error": f"No inventory found for sku={sku!r} size={size!r}."}

        price = conn.execute(
            "SELECT unit_cost, list_price FROM pricing WHERE sku = ?", (sku,)
        ).fetchone()

    return {
        "sku": sku,
        "stock": rows,
        "total_qty": sum(r["qty"] for r in rows),
        "pricing": dict(price) if price else None,
    }


@mcp.tool
def get_invoice(invoice_id: int) -> dict:
    """Look up a vendor invoice with its vendor details and overdue status.

    Returns the invoice (amount, due_date, status, description), the vendor
    it is owed to (name, specialty, lead_days), and days_overdue measured
    against the shop's date (desk.date_today). days_overdue is negative if
    the invoice is not yet due.
    """
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT i.id, i.amount, i.due_date, i.status, i.description,
                   v.id AS vendor_id, v.name AS vendor_name,
                   v.specialty AS vendor_specialty, v.lead_days AS vendor_lead_days
            FROM invoices i JOIN vendors v ON v.id = i.vendor_id
            WHERE i.id = ?
            """,
            (invoice_id,),
        ).fetchone()
        if row is None:
            return {"error": f"No invoice with id={invoice_id}."}
        today = _shop_today(conn)

    invoice = dict(row)
    invoice["shop_date"] = today
    invoice["days_overdue"] = _days_between(invoice["due_date"], today)
    return invoice


@mcp.tool
def get_lease(lease_id: int) -> dict:
    """Look up a lease and how many days remain until rent is due.

    Returns the lease (space_name, landlord, monthly_rent, next_due, notes)
    and days_until_due measured against the shop's date (desk.date_today).
    days_until_due is negative if rent is already late.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, space_name, landlord, monthly_rent, next_due, notes "
            "FROM leases WHERE id = ?",
            (lease_id,),
        ).fetchone()
        if row is None:
            return {"error": f"No lease with id={lease_id}."}
        today = _shop_today(conn)

    lease = dict(row)
    lease["shop_date"] = today
    lease["days_until_due"] = _days_between(today, lease["next_due"])
    return lease


@mcp.tool
def list_open_tickets() -> dict:
    """List every ticket that is not resolved, oldest first.

    Returns id, type, requester, subject, status and created_at for each one,
    plus the shop's date. Use get_ticket for the full record.
    """
    with _connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, type, requester, subject, status, created_at FROM tickets "
            "WHERE status != 'resolved' ORDER BY created_at"
        )]
        today = _shop_today(conn)
    return {"shop_date": today, "tickets": rows}


@mcp.tool
def list_tickets() -> dict:
    """List every ticket (open or resolved) with id, type, requester, subject,
    status, and is_resolved, oldest first."""
    with _connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, type, requester, subject, status, created_at FROM tickets ORDER BY created_at"
        )]
        today = _shop_today(conn)
    for r in rows:
        r["is_resolved"] = r["status"] == "resolved"
    return {"shop_date": today, "tickets": rows}


@mcp.tool
def get_ticket(ticket_id: int) -> dict:
    """Look up one ticket in full: type, requester, subject, product request
    (sku, size, qty), linked lease_id / invoice_id, status, notes, created_at.
    """
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            return {"error": f"No ticket with id={ticket_id}."}
        today = _shop_today(conn)
    return {**dict(row), "shop_date": today}


@mcp.tool
def get_cash_position(account: str = "checking") -> dict:
    """Cash balance plus what the shop owes soon and what's awaiting approval.

    Returns the account balance, every open invoice (with days_overdue), every
    lease rent due within 30 days of the shop's date (with days_until_due), the
    total of those obligations, and balance_after_obligations (balance minus
    that total). Negative balance_after_obligations means the shop can't cover
    them all. pending_approvals_total is payments already queued for a human.
    upcoming_rent lists every lease's next rent however far out it is, and
    warnings flags a next rent (outside the 30-day window) that the money left
    after obligations can't cover.
    """
    with _connect() as conn:
        acct = conn.execute(
            "SELECT name, balance, date FROM cash_accounts WHERE name = ?", (account,)
        ).fetchone()
        if acct is None:
            return {"error": f"No cash account named {account!r}."}
        today = _shop_today(conn)
        invoices = [dict(r) for r in conn.execute(
            "SELECT i.id, v.name AS vendor_name, i.amount, i.due_date, i.description "
            "FROM invoices i JOIN vendors v ON v.id = i.vendor_id WHERE i.status = 'open' "
            "ORDER BY i.due_date"
        )]
        leases = [dict(r) for r in conn.execute(
            "SELECT id, space_name, landlord, monthly_rent, next_due FROM leases ORDER BY next_due"
        )]
        pending = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS t FROM approvals WHERE status = 'pending' AND kind != 'purchase'"
        ).fetchone()["t"]
    for inv in invoices:
        inv["days_overdue"] = _days_between(inv["due_date"], today)
    rent_due = []
    for lease in leases:
        lease["days_until_due"] = _days_between(today, lease["next_due"])
        if lease["days_until_due"] <= OBLIGATION_WINDOW_DAYS:
            rent_due.append(lease)
    total = round(sum(i["amount"] for i in invoices) + sum(l["monthly_rent"] for l in rent_due), 2)
    after = round(acct["balance"] - total, 2)
    # Rent just outside the window still has to be paid; show it so a low balance isn't read as "fine".
    upcoming = [{"lease_id": l["id"], "space_name": l["space_name"], "landlord": l["landlord"],
                 "amount": l["monthly_rent"], "next_due": l["next_due"], "days_until_due": l["days_until_due"],
                 "counted_in_obligations": l["days_until_due"] <= OBLIGATION_WINDOW_DAYS} for l in leases]
    warnings = [
        f"Next rent for lease {u['lease_id']} ({u['amount']:.2f}, due {u['next_due']}, in {u['days_until_due']} "
        f"days) is more than the {after:.2f} left after current obligations."
        for u in upcoming if not u["counted_in_obligations"] and after < u["amount"]
    ]
    return {
        "shop_date": today,
        "account": acct["name"],
        "balance": acct["balance"],
        "balance_as_of": acct["date"],
        "open_invoices": invoices,
        "rent_due_within_30_days": rent_due,
        "total_obligations": total,
        "balance_after_obligations": after,
        "pending_approvals_total": round(pending, 2),
        "upcoming_rent": upcoming,
        "warnings": warnings,
    }


@mcp.tool
def list_vendors(specialty: str | None = None) -> dict:
    """List vendors (id, name, specialty, lead_days) and the date an order
    placed today would arrive (ready_date = shop date + lead_days).

    Pass `specialty` to filter with a case-insensitive substring match,
    e.g. "apparel", "mug", "courier".
    """
    with _connect() as conn:
        query, params = "SELECT id, name, specialty, lead_days FROM vendors", []
        if specialty:
            query += " WHERE lower(specialty) LIKE ?"
            params.append(f"%{specialty.lower()}%")
        rows = [dict(r) for r in conn.execute(query + " ORDER BY id", params)]
        today = _shop_today(conn)
    if not rows:
        return {"error": f"No vendor matches specialty={specialty!r}."}
    for r in rows:
        r["ready_date_if_ordered_today"] = _add_days(today, r["lead_days"])
    return {"shop_date": today, "vendors": rows}


@mcp.tool
def quote_price(sku: str, qty: int, discount_pct: float = 0.0, size: str | None = None,
                deposit_pct: float = 0.0) -> dict:
    """Price a quantity of one SKU, optionally with a percentage discount.

    Returns list and discounted unit price, order total, unit_cost, margin per
    unit and in percent, and above_cost (False if the price would be at or
    below cost). With `size`, also returns on_hand, shortfall (units that
    must be reordered) and reorder_cost (shortfall x unit_cost). With
    `deposit_pct`, returns deposit_amount (that percent of the total).
    Nothing is written; this is a calculator over the pricing table.
    """
    if qty <= 0:
        return {"error": "qty must be positive."}
    if not 0 <= discount_pct < 100 or not 0 <= deposit_pct <= 100:
        return {"error": "discount_pct must be in [0, 100) and deposit_pct in [0, 100]."}
    with _connect() as conn:
        price = conn.execute(
            "SELECT p.unit_cost, p.list_price, MIN(i.name) AS name FROM pricing p "
            "LEFT JOIN inventory i ON i.sku = p.sku WHERE p.sku = ? GROUP BY p.sku", (sku,)
        ).fetchone()
        if price is None:
            return {"error": f"No pricing for sku={sku!r}."}
        stock = None
        if size is not None:
            stock = conn.execute(
                "SELECT qty FROM inventory WHERE sku = ? AND size = ?", (sku, size)
            ).fetchone()
            if stock is None:
                return {"error": f"No inventory row for sku={sku!r} size={size!r}."}
    unit_price = round(price["list_price"] * (1 - discount_pct / 100), 2)
    total = round(unit_price * qty, 2)
    unit_margin = round(unit_price - price["unit_cost"], 2)
    out = {
        "sku": sku, "name": price["name"], "qty": qty,
        "list_unit_price": price["list_price"], "discount_pct": discount_pct,
        "unit_price": unit_price, "total": total,
        "list_total": round(price["list_price"] * qty, 2),
        "unit_cost": price["unit_cost"], "unit_margin": unit_margin,
        "margin_pct": round(100 * unit_margin / unit_price, 1) if unit_price else None,
        "above_cost": unit_margin > 0,
    }
    if stock is not None:
        shortfall = max(qty - stock["qty"], 0)
        out.update(size=size, on_hand=stock["qty"], shortfall=shortfall,
                   reorder_cost=round(shortfall * price["unit_cost"], 2))
    if deposit_pct:
        out.update(deposit_pct=deposit_pct, deposit_amount=round(total * deposit_pct / 100, 2))
    return out


@mcp.tool
def list_payments(kind: str | None = None, ref_id: int | None = None) -> dict:
    """List payments already made (id, kind, ref_id, amount, account, paid_at,
    approved_by). Filter by kind ("invoice" or "rent") and/or ref_id. Check
    this before paying so nothing is paid twice.
    """
    with _connect() as conn:
        query, params, where = "SELECT * FROM payments", [], []
        if kind:
            where.append("kind = ?"); params.append(kind)
        if ref_id is not None:
            where.append("ref_id = ?"); params.append(ref_id)
        if where:
            query += " WHERE " + " AND ".join(where)
        rows = [dict(r) for r in conn.execute(query + " ORDER BY id", params)]
    return {"payments": rows}


def _check_payment(conn: sqlite3.Connection, kind: str, ref_id: int, amount: float) -> str | None:
    """Why an invoice/rent payment can't be made right now, or None if it can."""
    today = _shop_today(conn)
    if kind == "invoice":
        inv = conn.execute("SELECT amount, status FROM invoices WHERE id = ?", (ref_id,)).fetchone()
        if inv is None:
            return f"No invoice with id={ref_id}."
        if inv["status"] != "open":
            return f"Invoice {ref_id} is {inv['status']!r}, not open; nothing to pay."
        owed = inv["amount"]
    else:
        lease = conn.execute("SELECT monthly_rent, next_due FROM leases WHERE id = ?", (ref_id,)).fetchone()
        if lease is None:
            return f"No lease with id={ref_id}."
        days_until_due = _days_between(today, lease["next_due"])
        if days_until_due > RENT_EARLY_WINDOW_DAYS:
            return (f"Rent for lease {ref_id} isn't due until {lease['next_due']} ({days_until_due} days); "
                    f"it can only be paid within {RENT_EARLY_WINDOW_DAYS} days of the due date.")
        owed = lease["monthly_rent"]
    if abs(amount - owed) > 0.005:
        return f"Amount {amount} doesn't match the {owed} owed; use the exact amount."
    return None


def _check_purchase(conn: sqlite3.Connection, vendor_id: int, sku: str | None, size: str | None,
                    qty: int | None, amount: float) -> str | None:
    """Why a purchase order can't be raised, or None if it can. Amount must be qty x unit_cost."""
    if not sku or not size or not qty or qty <= 0:
        return "A purchase needs sku, size and a positive qty."
    if conn.execute("SELECT 1 FROM vendors WHERE id = ?", (vendor_id,)).fetchone() is None:
        return f"No vendor with id={vendor_id}."
    if conn.execute("SELECT 1 FROM inventory WHERE sku = ? AND size = ?", (sku, size)).fetchone() is None:
        return f"No inventory row for sku={sku!r} size={size!r}."
    price = conn.execute("SELECT unit_cost FROM pricing WHERE sku = ?", (sku,)).fetchone()
    if price is None:
        return f"No pricing for sku={sku!r}."
    cost = round(qty * price["unit_cost"], 2)
    if abs(amount - cost) > 0.005:
        return f"Amount {amount} doesn't match qty x unit_cost = {cost}."
    return None


def _pay(conn: sqlite3.Connection, kind: str, ref_id: int, amount: float, approved_by: str,
         account: str) -> dict:
    """Record an invoice/rent payment. Caller has already validated it with _check_payment."""
    today = _shop_today(conn)
    acct = conn.execute("SELECT balance FROM cash_accounts WHERE name = ?", (account,)).fetchone()
    if acct is None:
        return {"error": f"No cash account named {account!r}."}
    if acct["balance"] < amount:
        return {"error": f"Insufficient funds: {account} has {acct['balance']}, payment needs {amount}."}
    cur = conn.execute(
        "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) VALUES (?, ?, ?, ?, ?, ?)",
        (kind, ref_id, amount, account, today, approved_by),
    )
    new_balance = round(acct["balance"] - amount, 2)
    conn.execute("UPDATE cash_accounts SET balance = ?, date = ? WHERE name = ?", (new_balance, today, account))
    if kind == "invoice":
        conn.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (ref_id,))
        effect = {"invoice_status": "paid"}
    else:
        lease = conn.execute("SELECT next_due FROM leases WHERE id = ?", (ref_id,)).fetchone()
        next_due = _add_month(lease["next_due"])
        conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (next_due, ref_id))
        effect = {"lease_next_due": next_due}
    payment = dict(conn.execute("SELECT * FROM payments WHERE id = ?", (cur.lastrowid,)).fetchone())
    return {"payment": payment, "account": account, "new_balance": new_balance, **effect}


def _raise_purchase_order(conn: sqlite3.Connection, approval: sqlite3.Row) -> dict:
    """An approved purchase becomes an open vendor invoice due when the goods arrive (no cash moves yet)."""
    today = _shop_today(conn)
    vendor = conn.execute("SELECT name, lead_days FROM vendors WHERE id = ?", (approval["ref_id"],)).fetchone()
    due = _add_days(today, vendor["lead_days"])
    cur = conn.execute(
        "INSERT INTO invoices (vendor_id, amount, due_date, status, description) VALUES (?, ?, ?, 'open', ?)",
        (approval["ref_id"], approval["amount"], due,
         f"PO from approval {approval['id']}: {approval['qty']} x {approval['sku']} {approval['size']}"),
    )
    return {"invoice_id": cur.lastrowid, "vendor": vendor["name"], "amount": approval["amount"],
            "due_date": due, "expected_arrival": due}


def _approval(conn: sqlite3.Connection, approval_id: int) -> dict:
    return dict(conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone())


@mcp.tool
def request_approval(kind: str, ref_id: int, amount: float, reason: str, requested_by: str,
                     ticket_id: int | None = None, status_after_approval: str | None = None,
                     sku: str | None = None, size: str | None = None, qty: int | None = None) -> dict:
    """WRITE (queue only). Ask a human to approve a payment or purchase. Nothing is paid yet.

    kind="invoice" (ref_id = invoice id), kind="rent" (ref_id = lease id), or
    kind="purchase" (ref_id = vendor id, plus sku, size, qty; amount must be
    qty x unit_cost). Refused if the amount doesn't match the record, the bill
    isn't payable, the same item already has a pending request, or cash
    minus already-pending payments can't cover it. status_after_approval is
    the ticket status to set once a human approves.
    """
    if kind not in APPROVAL_KINDS:
        return {"error": f"kind must be one of {', '.join(APPROVAL_KINDS)}."}
    if not reason.strip() or not requested_by.strip():
        return {"error": "reason and requested_by are required."}
    if status_after_approval is not None and status_after_approval not in TICKET_STATUSES:
        return {"error": f"status_after_approval must be one of {', '.join(TICKET_STATUSES)}."}
    with _connect() as conn:
        if ticket_id is not None and conn.execute(
                "SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone() is None:
            return {"error": f"No ticket with id={ticket_id}."}
        problem = (_check_purchase(conn, ref_id, sku, size, qty, amount) if kind == "purchase"
                   else _check_payment(conn, kind, ref_id, amount))
        if problem:
            return {"error": problem}
        dup = conn.execute(
            "SELECT id FROM approvals WHERE kind = ? AND ref_id = ? AND status = 'pending' "
            "AND (kind != 'purchase' OR (sku = ? AND size = ?))", (kind, ref_id, sku, size)
        ).fetchone()
        if dup:
            return {"error": f"Approval {dup['id']} for this {kind} is already pending."}
        if kind != "purchase":
            balance = conn.execute("SELECT balance FROM cash_accounts WHERE name = 'checking'").fetchone()["balance"]
            pending = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) AS t FROM approvals WHERE status = 'pending' AND kind != 'purchase'"
            ).fetchone()["t"]
            if balance - pending < amount:
                return {"error": f"Checking has {balance} and {pending} is already pending approval; "
                                 f"{amount} more can't be covered."}
        cur = conn.execute(
            "INSERT INTO approvals (ticket_id, kind, ref_id, sku, size, qty, amount, reason, requested_by, "
            "status, status_after_approval, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (ticket_id, kind, ref_id, sku, size, qty, round(amount, 2), reason.strip(), requested_by,
             status_after_approval, _shop_today(conn)),
        )
        return {"approval": _approval(conn, cur.lastrowid)}


@mcp.tool
def list_approvals(status: str | None = None, ticket_id: int | None = None) -> dict:
    """List approval requests (pending, approved, rejected or failed), newest first.
    Filter by status and/or ticket_id."""
    with _connect() as conn:
        query, params, where = "SELECT * FROM approvals", [], []
        if status:
            where.append("status = ?"); params.append(status)
        if ticket_id is not None:
            where.append("ticket_id = ?"); params.append(ticket_id)
        if where:
            query += " WHERE " + " AND ".join(where)
        rows = [dict(r) for r in conn.execute(query + " ORDER BY id DESC", params)]
    return {"approvals": rows}


@mcp.tool
def decide_approval(approval_id: int, decision: str, decided_by: str, account: str = "checking") -> dict:
    """HUMAN ONLY (called by the board after a person clicks Approve/Reject; no agent has this tool).

    decision="approved": re-validates, then pays the invoice/rent (payments row,
    lower balance, invoice paid or lease next_due +1 month) or raises the
    purchase as an open vendor invoice, and sets the linked ticket to
    status_after_approval. decision="rejected": marks it rejected and
    escalates the ticket. Either way a dated note is added to the ticket.
    """
    import json

    if decision not in ("approved", "rejected"):
        return {"error": "decision must be 'approved' or 'rejected'."}
    if not decided_by.strip():
        return {"error": "decided_by is required."}
    with _connect() as conn:
        row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if row is None:
            return {"error": f"No approval with id={approval_id}."}
        if row["status"] != "pending":
            return {"error": f"Approval {approval_id} is already {row['status']}."}
        today = _shop_today(conn)
        label = (f"{row['qty']} x {row['sku']} {row['size']} from vendor {row['ref_id']}" if row["kind"] == "purchase"
                 else f"{row['kind']} {row['ref_id']}")

        if decision == "rejected":
            status, result, ticket_status = "rejected", {"rejected": True}, "escalated"
            note = f"Approval {approval_id} REJECTED: {label} ${row['amount']:.2f}."
        else:
            if row["kind"] == "purchase":
                problem = _check_purchase(conn, row["ref_id"], row["sku"], row["size"], row["qty"], row["amount"])
                result = {"error": problem} if problem else _raise_purchase_order(conn, row)
            else:
                problem = _check_payment(conn, row["kind"], row["ref_id"], row["amount"])
                result = {"error": problem} if problem else _pay(
                    conn, row["kind"], row["ref_id"], row["amount"], f"human:{decided_by}", account)
            ok = "error" not in result
            status = "approved" if ok else "failed"
            ticket_status = row["status_after_approval"] if ok else "escalated"
            note = (f"Approval {approval_id} APPROVED by {decided_by}: {label} ${row['amount']:.2f}." if ok
                    else f"Approval {approval_id} FAILED on approval: {result['error']}")

        conn.execute("UPDATE approvals SET status = ?, decided_by = ?, decided_at = ?, result = ? WHERE id = ?",
                     (status, decided_by, today, json.dumps(result), approval_id))
        ticket = None
        if row["ticket_id"] is not None:
            t = conn.execute("SELECT status, notes FROM tickets WHERE id = ?", (row["ticket_id"],)).fetchone()
            entry = f"[{today} human:{decided_by}] {note}"
            conn.execute("UPDATE tickets SET status = ?, notes = ? WHERE id = ?",
                         (ticket_status or t["status"], f"{t['notes']}\n{entry}" if t["notes"] else entry,
                          row["ticket_id"]))
            ticket = dict(conn.execute("SELECT id, status FROM tickets WHERE id = ?", (row["ticket_id"],)).fetchone())
        return {"approval": _approval(conn, approval_id), "result": result, "ticket": ticket}


@mcp.tool
def record_receipt(amount: float, payer: str, memo: str, recorded_by: str, ticket_id: int | None = None,
                   account: str = "checking") -> dict:
    """HUMAN ONLY (called by the board when a person records money received; no agent has this tool).

    Records money coming in, such as a customer's deposit: adds a receipts row,
    raises the account balance by exactly `amount`, and appends a dated note to
    the linked ticket (its status doesn't change). Amount must be positive.
    """
    amount = round(float(amount), 2)
    if amount <= 0:
        return {"error": "amount must be positive."}
    if not payer.strip() or not memo.strip() or not recorded_by.strip():
        return {"error": "payer, memo and recorded_by are required."}
    with _connect() as conn:
        acct = conn.execute("SELECT balance FROM cash_accounts WHERE name = ?", (account,)).fetchone()
        if acct is None:
            return {"error": f"No cash account named {account!r}."}
        ticket = None
        if ticket_id is not None:
            ticket = conn.execute("SELECT notes FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
            if ticket is None:
                return {"error": f"No ticket with id={ticket_id}."}
        today = _shop_today(conn)
        cur = conn.execute(
            "INSERT INTO receipts (ticket_id, payer, amount, account, received_at, memo, recorded_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticket_id, payer.strip(), amount, account, today, memo.strip(), recorded_by.strip()),
        )
        new_balance = round(acct["balance"] + amount, 2)
        conn.execute("UPDATE cash_accounts SET balance = ?, date = ? WHERE name = ?", (new_balance, today, account))
        if ticket is not None:
            entry = f"[{today} {recorded_by.strip()}] Received ${amount:.2f} from {payer.strip()}: {memo.strip()}."
            conn.execute("UPDATE tickets SET notes = ? WHERE id = ?",
                         (f"{ticket['notes']}\n{entry}" if ticket["notes"] else entry, ticket_id))
        receipt = dict(conn.execute("SELECT * FROM receipts WHERE id = ?", (cur.lastrowid,)).fetchone())
    return {"receipt": receipt, "account": account, "new_balance": new_balance}


@mcp.tool
def list_receipts(ticket_id: int | None = None) -> dict:
    """List money received (id, ticket_id, payer, amount, account, received_at,
    memo, recorded_by), oldest first, with the total. Filter by ticket_id, e.g.
    to confirm a customer's deposit arrived before a reorder is requested."""
    with _connect() as conn:
        query, params = "SELECT * FROM receipts", []
        if ticket_id is not None:
            query += " WHERE ticket_id = ?"
            params.append(ticket_id)
        rows = [dict(r) for r in conn.execute(query + " ORDER BY id", params)]
    return {"receipts": rows, "total": round(sum(r["amount"] for r in rows), 2)}


@mcp.tool
def update_ticket(ticket_id: int, status: str, note: str, updated_by: str) -> dict:
    """WRITE. Set a ticket's status and append a dated note to its notes.

    status must be one of: open, in_progress, waiting_on_approval,
    waiting_on_customer, waiting_on_vendor, escalated, resolved. The note is appended as
    "[<shop date> <updated_by>] <note>"; earlier notes are kept.
    """
    if status not in TICKET_STATUSES:
        return {"error": f"status must be one of {', '.join(TICKET_STATUSES)}."}
    if not note.strip() or not updated_by.strip():
        return {"error": "note and updated_by are required."}
    with _connect() as conn:
        row = conn.execute("SELECT notes FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            return {"error": f"No ticket with id={ticket_id}."}
        today = _shop_today(conn)
        entry = f"[{today} {updated_by}] {note.strip()}"
        notes = f"{row['notes']}\n{entry}" if row["notes"] else entry
        conn.execute("UPDATE tickets SET status = ?, notes = ? WHERE id = ?", (status, notes, ticket_id))
        updated = dict(conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone())
    return {"ticket": updated}


if __name__ == "__main__":
    mcp.run()
