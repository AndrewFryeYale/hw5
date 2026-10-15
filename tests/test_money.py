"""Money paths: agents can only queue; a human approval moves exactly the approved amount, once."""

import pytest

import server


def approve(approval_id: int, who: str = "andrew"):
    return server.decide_approval(approval_id, "approved", who)


def test_request_approval_moves_no_money(ask, balance, sql):
    res = ask("invoice", 501, 840, ticket_id=101, status_after_approval="waiting_on_customer")
    assert res["approval"]["status"] == "pending"
    assert balance() == 3400.0
    assert sql("SELECT * FROM payments") == []
    assert server.get_cash_position()["pending_approvals_total"] == 840.0


@pytest.mark.parametrize("kind, ref_id, amount, ticket_id, after", [
    ("invoice", 501, 840.0, 101, "waiting_on_customer"),
    ("rent", 1, 2400.0, 102, "resolved"),
])
def test_human_approval_pays_exactly_the_amount(ask, balance, sql, kind, ref_id, amount, ticket_id, after):
    approval = ask(kind, ref_id, amount, ticket_id=ticket_id, status_after_approval=after)["approval"]
    before = balance()
    result = approve(approval["id"])
    assert "error" not in result["result"]
    assert balance() == round(before - amount, 2)
    [payment] = sql("SELECT * FROM payments")
    assert (payment["kind"], payment["ref_id"], payment["amount"], payment["approved_by"]) == (
        kind, ref_id, amount, "human:andrew")
    assert sql("SELECT status FROM tickets WHERE id = ?", ticket_id)[0]["status"] == after
    if kind == "invoice":
        assert sql("SELECT status FROM invoices WHERE id = 501")[0]["status"] == "paid"
    else:
        assert sql("SELECT next_due FROM leases WHERE id = 1")[0]["next_due"] == "2026-10-02"


def test_problem_9_cash_math_ties_out(ask, balance, sql):
    """Opening $3,400.00 - invoice 501 $840.00 - rent $2,400.00 - hoodie quote $0.00 = $160.00."""
    approve(ask("invoice", 501, 840, ticket_id=101)["approval"]["id"])
    assert balance() == 2560.0
    approve(ask("rent", 1, 2400, ticket_id=102)["approval"]["id"])
    paid = sum(p["amount"] for p in sql("SELECT amount FROM payments"))
    assert paid == 3240.0
    assert balance() == 160.0 == 3400.0 - paid
    assert server.get_cash_position()["balance"] == 160.0


def test_rejection_moves_no_money_and_escalates(ask, balance, sql):
    approval = ask("invoice", 501, 840, ticket_id=101)["approval"]
    server.decide_approval(approval["id"], "rejected", "andrew")
    assert balance() == 3400.0
    assert sql("SELECT * FROM payments") == []
    assert sql("SELECT status FROM tickets WHERE id = 101")[0]["status"] == "escalated"
    assert sql("SELECT status FROM invoices WHERE id = 501")[0]["status"] == "open"


def test_an_approval_can_only_be_decided_once(ask, balance):
    approval_id = ask("invoice", 501, 840)["approval"]["id"]
    approve(approval_id)
    assert "error" in approve(approval_id)
    assert balance() == 2560.0


@pytest.mark.parametrize("kind, ref_id, amount", [
    ("invoice", 501, 800),      # amount doesn't match the record
    ("invoice", 999, 840),      # no such invoice
    ("rent", 1, 2000),          # wrong rent
    ("refund", 1, 10),          # not a kind agents can ask for
])
def test_bad_requests_are_refused(ask, kind, ref_id, amount):
    assert "error" in ask(kind, ref_id, amount)
    assert server.list_approvals()["approvals"] == []


def test_no_double_payment(ask):
    first = ask("invoice", 501, 840)["approval"]["id"]
    assert "already pending" in ask("invoice", 501, 840)["error"]
    approve(first)
    assert "not open" in ask("invoice", 501, 840)["error"]           # invoice is paid now
    approve(ask("rent", 1, 2400)["approval"]["id"])
    assert "isn't due until 2026-10-02" in ask("rent", 1, 2400)["error"]  # next month's rent can't be paid early


def test_requests_count_money_already_pending(ask, sql):
    with server._connect() as conn:
        conn.execute("UPDATE cash_accounts SET balance = 3000 WHERE name = 'checking'")
    assert "error" not in ask("rent", 1, 2400)
    assert "can't be covered" in ask("invoice", 501, 840)["error"]   # 3000 - 2400 pending < 840


def test_overdraft_is_refused_even_on_approval(ask, balance):
    approval_id = ask("invoice", 501, 840)["approval"]["id"]
    with server._connect() as conn:
        conn.execute("UPDATE cash_accounts SET balance = 100 WHERE name = 'checking'")
    result = approve(approval_id)
    assert result["approval"]["status"] == "failed"
    assert balance() == 100.0


def test_purchase_raises_a_po_without_moving_cash(ask, balance, sql):
    assert "doesn't match" in ask("purchase", 1, 200, sku="CC-HOOD-NAVY", size="M", qty=12)["error"]
    approval = ask("purchase", 1, 264, ticket_id=103, sku="CC-HOOD-NAVY", size="M", qty=12,
                   status_after_approval="waiting_on_vendor")["approval"]
    result = approve(approval["id"])["result"]
    assert balance() == 3400.0
    [po] = sql("SELECT * FROM invoices WHERE id = ?", result["invoice_id"])
    assert (po["amount"], po["status"], po["due_date"]) == (264.0, "open", "2026-09-05")


def test_next_rent_beyond_30_days_is_visible(ask):
    approve(ask("rent", 1, 2400)["approval"]["id"])
    approve(ask("invoice", 501, 840)["approval"]["id"])
    pos = server.get_cash_position()
    assert pos["balance"] == 160.0 and pos["total_obligations"] == 0
    [rent] = pos["upcoming_rent"]
    assert (rent["next_due"], rent["days_until_due"], rent["counted_in_obligations"]) == ("2026-10-02", 32, False)
    assert len(pos["warnings"]) == 1 and "2026-10-02" in pos["warnings"][0]


def test_record_receipt_adds_exactly_the_amount(balance, sql):
    res = server.record_receipt(464, "Yale AI Club", "50% deposit on 20 hoodies", "human:andrew", ticket_id=103)
    assert res["new_balance"] == 3864.0 == balance()
    assert server.list_receipts(103)["total"] == 464.0
    assert sql("SELECT status FROM tickets WHERE id = 103")[0]["status"] == "open"   # status unchanged
    assert "Received $464.00 from Yale AI Club" in sql("SELECT notes FROM tickets WHERE id = 103")[0]["notes"]


@pytest.mark.parametrize("amount, payer, ticket_id", [(0, "Yale AI Club", 103), (-5, "Yale AI Club", 103),
                                                      (10, " ", 103), (10, "Yale AI Club", 999)])
def test_record_receipt_refuses_bad_input(balance, amount, payer, ticket_id):
    assert "error" in server.record_receipt(amount, payer, "deposit", "human:andrew", ticket_id=ticket_id)
    assert balance() == 3400.0
