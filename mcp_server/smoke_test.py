"""Smoke test for the campus-customs MCP server.

Launches the server exactly as .mcp.json describes (stdio), lists its tools,
calls each one with a ticket-driven prompt, and checks every returned value
against a direct SQLite read of data/campus_customs_new.db.
Writes the evidence to output/mcp_smoke.json.

Run from hw5/:
    venv/bin/python mcp_server/smoke_test.py              # Problem 4 check (rewrites the file; run on fresh data)
    venv/bin/python mcp_server/smoke_test.py --post-run   # re-check against the database as it is now, after
                                                          # the agents and humans changed it; only adds/replaces
                                                          # the "post_run_check" section, the Problem 4 evidence stays
"""

import asyncio
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from fastmcp import Client

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "campus_customs_new.db"
MCP_CONFIG = json.loads((ROOT / ".mcp.json").read_text())
# .mcp.json paths are relative to hw5/; resolve them so the test runs from any working directory.
_server = MCP_CONFIG["mcpServers"]["campus-customs"]
_server["command"] = str(ROOT / _server["command"]) if (ROOT / _server["command"]).exists() else _server["command"]
_server["args"] = [str(ROOT / a) if (ROOT / a).exists() else a for a in _server.get("args", [])]
OUT_PATH = ROOT / "output" / "mcp_smoke.json"

CASES = [
    {
        "ticket": 101,
        "prompt": "Ticket #101: Tauhid Zaman wants a Classic Bulldog Tee in size S. "
                  "Do we have any in stock, where is it, and what does it cost?",
        "tool": "check_stock",
        "args": {"sku": "CC-TEE-WHITE", "size": "S"},
    },
    {
        "ticket": 101,
        "prompt": "Ticket #101 links to invoice 501. Who is it owed to, how much, "
                  "and is it overdue?",
        "tool": "get_invoice",
        "args": {"invoice_id": 501},
    },
    {
        "ticket": 102,
        "prompt": "Ticket #102: Elm City Properties says rent is due in 2 days. "
                  "Check lease 1 — how much is rent and when exactly is it due?",
        "tool": "get_lease",
        "args": {"lease_id": 1},
    },
    {
        "ticket": 103,
        "prompt": "Ticket #103: Yale AI Club wants 20 Basic Hoodies in size M. "
                  "How many do we have and what are the cost and list price?",
        "tool": "check_stock",
        "args": {"sku": "CC-HOOD-NAVY", "size": "M"},
    },
]


def db_expected(tool: str, args: dict) -> dict:
    """Independent SQLite read of the same facts each tool should return."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    today = conn.execute("SELECT date_today FROM desk").fetchone()[0]
    if tool == "check_stock":
        inv = conn.execute(
            "SELECT qty, location FROM inventory WHERE sku=? AND size=?",
            (args["sku"], args["size"]),
        ).fetchone()
        price = conn.execute(
            "SELECT unit_cost, list_price FROM pricing WHERE sku=?", (args["sku"],)
        ).fetchone()
        exp = {**dict(inv), **dict(price)}
    elif tool == "get_invoice":
        row = conn.execute(
            "SELECT i.amount, i.due_date, i.status, v.name AS vendor_name, "
            "julianday(?) - julianday(i.due_date) AS days_overdue "
            "FROM invoices i JOIN vendors v ON v.id=i.vendor_id WHERE i.id=?",
            (today, args["invoice_id"]),
        ).fetchone()
        exp = dict(row)
    elif tool == "get_lease":
        row = conn.execute(
            "SELECT monthly_rent, next_due, landlord, "
            "julianday(next_due) - julianday(?) AS days_until_due "
            "FROM leases WHERE id=?",
            (today, args["lease_id"]),
        ).fetchone()
        exp = dict(row)
    conn.close()
    return exp


def flatten(tool: str, out: dict) -> dict:
    """Pull the fields we compare out of a tool's output."""
    if tool == "check_stock":
        row = out["stock"][0]
        return {"qty": row["qty"], "location": row["location"], **out["pricing"]}
    return out


def db_rows(sql: str, params: tuple = ()) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(sql, params)]
    conn.close()
    return rows


# Post-run: each tool's answer vs. an independent SQLite read of the same fact, after money has moved.
POST_RUN_CASES = [
    ("What is the checking balance now?", "get_cash_position", {"account": "checking"},
     lambda out: {"balance": out["balance"]},
     lambda: {"balance": db_rows("SELECT balance FROM cash_accounts WHERE name = 'checking'")[0]["balance"]}),
    ("Which payments have been made, and for how much in total?", "list_payments", {},
     lambda out: {"count": len(out["payments"]), "total": round(sum(p["amount"] for p in out["payments"]), 2),
                  "approved_by": sorted({p["approved_by"] for p in out["payments"]})},
     lambda: {"count": len(rows := db_rows("SELECT * FROM payments")),
              "total": round(sum(r["amount"] for r in rows), 2),
              "approved_by": sorted({r["approved_by"] for r in rows})}),
    ("Ticket #101: is invoice 501 still open?", "get_invoice", {"invoice_id": 501},
     lambda out: {"status": out["status"], "amount": out["amount"]},
     lambda: {k: db_rows("SELECT status, amount FROM invoices WHERE id = 501")[0][k] for k in ("status", "amount")}),
    ("Ticket #102: when is rent on lease 1 due next?", "get_lease", {"lease_id": 1},
     lambda out: {"next_due": out["next_due"], "monthly_rent": out["monthly_rent"]},
     lambda: db_rows("SELECT next_due, monthly_rent FROM leases WHERE id = 1")[0]),
    ("What status is every ticket in?", "list_tickets", {},
     lambda out: {str(t["id"]): t["status"] for t in out["tickets"]},
     lambda: {str(r["id"]): r["status"] for r in db_rows("SELECT id, status FROM tickets")}),
    ("Which approvals did a human decide?", "list_approvals", {},
     lambda out: {str(a["id"]): [a["status"], a["amount"], a["decided_by"]] for a in out["approvals"]},
     lambda: {str(r["id"]): [r["status"], r["amount"], r["decided_by"]]
              for r in db_rows("SELECT id, status, amount, decided_by FROM approvals")}),
    ("Ticket #103: how many size-M hoodies are on hand?", "check_stock", {"sku": "CC-HOOD-NAVY", "size": "M"},
     lambda out: {"qty": out["stock"][0]["qty"]},
     lambda: db_rows("SELECT qty FROM inventory WHERE sku = 'CC-HOOD-NAVY' AND size = 'M'")[0]),
]


async def post_run() -> None:
    results = []
    async with Client(MCP_CONFIG) as client:
        tools = await client.list_tools()
        for prompt, tool, args, pick, expected in POST_RUN_CASES:
            res = await client.call_tool(tool, args)
            output = res.data if res.data is not None else res.structured_content
            got, exp = pick(output), expected()
            results.append({"prompt": prompt, "tool": tool, "args": args, "mcp": got, "db": exp,
                            "match": got == exp})
    evidence = json.loads(OUT_PATH.read_text())
    evidence["post_run_check"] = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "database": str(DB_PATH.relative_to(ROOT)),
        "why": "The Problem 4 results above were checked before any agent ran (checking $3,400.00, invoice 501 "
               "open, rent due 2026-09-02). The agent runs and human approvals have changed the database since, "
               "so this section re-checks the same server against the database as it is now.",
        "tools_listed_now": [t.name for t in tools],
        "results": results,
        "all_match": all(r["match"] for r in results),
    }
    OUT_PATH.write_text(json.dumps(evidence, indent=2))
    print(json.dumps({"post_run_all_match": evidence["post_run_check"]["all_match"],
                      "tools_listed_now": len(evidence["post_run_check"]["tools_listed_now"])}))


async def main() -> None:
    results = []
    async with Client(MCP_CONFIG) as client:
        tools = await client.list_tools()
        for case in CASES:
            res = await client.call_tool(case["tool"], case["args"])
            output = res.data if res.data is not None else res.structured_content
            expected = db_expected(case["tool"], case["args"])
            got = flatten(case["tool"], output)
            checks = {k: {"mcp": got.get(k), "db": v, "match": got.get(k) == v}
                      for k, v in expected.items()}
            results.append({
                **case,
                "output": output,
                "db_check": checks,
                "all_match": all(c["match"] for c in checks.values()),
            })

    evidence = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "database": str(DB_PATH.relative_to(ROOT)),
        "connection": {
            "config_file": ".mcp.json",
            "server_name": "campus-customs",
            "transport": MCP_CONFIG["mcpServers"]["campus-customs"]["type"],
            "client": "fastmcp.Client (stdio, launched from .mcp.json)",
            "tools_listed": [t.name for t in tools],
        },
        "results": results,
        "all_tests_pass": all(r["all_match"] for r in results),
    }
    OUT_PATH.write_text(json.dumps(evidence, indent=2))
    print(json.dumps({"all_tests_pass": evidence["all_tests_pass"],
                      "tools_listed": evidence["connection"]["tools_listed"]}))


if __name__ == "__main__":
    asyncio.run(post_run() if "--post-run" in sys.argv[1:] else main())
