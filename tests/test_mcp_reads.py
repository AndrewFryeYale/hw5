"""The read tools return exactly what's in the database and never change it."""

import server


def test_ticket_101_tee_and_invoice():
    stock = server.check_stock("CC-TEE-WHITE")
    assert {r["size"]: r["qty"] for r in stock["stock"]} == {"S": 0, "M": 5, "L": 3, "XL": 2}
    assert stock["pricing"] == {"unit_cost": 8.0, "list_price": 28.0}
    inv = server.get_invoice(501)
    assert (inv["amount"], inv["status"], inv["vendor_name"], inv["days_overdue"]) == (840.0, "open", "Bulldog Print Co", 3)


def test_ticket_102_lease():
    lease = server.get_lease(1)
    assert (lease["monthly_rent"], lease["next_due"], lease["days_until_due"]) == (2400.0, "2026-09-02", 2)
    assert lease["landlord"] == "Elm City Properties"


def test_ticket_103_quote_matches_policy_numbers():
    q = server.quote_price("CC-HOOD-NAVY", 20, discount_pct=20, size="M", deposit_pct=50)
    assert (q["unit_price"], q["total"], q["margin_pct"], q["above_cost"]) == (46.4, 928.0, 52.6, True)
    assert (q["on_hand"], q["shortfall"], q["reorder_cost"], q["deposit_amount"]) == (8, 12, 264.0, 464.0)


def test_cash_position_on_fresh_data():
    pos = server.get_cash_position()
    assert pos["balance"] == 3400.0
    assert pos["total_obligations"] == 3240.0          # invoice 501 $840 + rent $2,400
    assert pos["balance_after_obligations"] == 160.0
    assert pos["pending_approvals_total"] == 0
    assert pos["warnings"] == []                        # September rent is inside the window
    assert pos["upcoming_rent"][0]["counted_in_obligations"] is True


def test_unknown_ids_return_errors_not_guesses():
    assert "error" in server.get_invoice(999)
    assert "error" in server.get_lease(9)
    assert "error" in server.check_stock("CC-BEANIE")
    assert "error" in server.quote_price("CC-BEANIE", 10)


def test_read_tools_never_write(sql):
    def snapshot():
        tables = [r["name"] for r in sql("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        return {t: sql(f"SELECT * FROM {t}") for t in tables}

    server.list_tickets()  # creates the approvals/receipts tables on first connect
    before = snapshot()
    server.check_stock("CC-HOOD-NAVY"); server.get_invoice(501); server.get_lease(1)
    server.list_open_tickets(); server.get_ticket(101); server.get_cash_position()
    server.list_vendors("apparel"); server.quote_price("CC-HOOD-NAVY", 20, 20, "M", 50)
    server.list_payments(); server.list_approvals(); server.list_receipts()
    assert snapshot() == before
