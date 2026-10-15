"""The desk API end to end (real MCP server process, scratch database, no agent runs)."""

import pytest
from fastapi.testclient import TestClient

import main
import server
from conftest import SCRATCH_DB


@pytest.fixture(scope="module")
def client():
    assert main.WORKING_DB == SCRATCH_DB and main.audit.AUDIT_PATH.parent == SCRATCH_DB.parent
    with TestClient(main.app) as c:
        yield c


def queue(kind, ref_id, amount, ticket_id, after):
    return server.request_approval(kind=kind, ref_id=ref_id, amount=amount, reason="test", requested_by="boss",
                                   ticket_id=ticket_id, status_after_approval=after)["approval"]["id"]


def test_tickets_and_cash(client):
    tickets = client.get("/tickets").json()["tickets"]
    assert [(t["id"], t["state"]) for t in tickets] == [(101, "open"), (102, "open"), (103, "open")]
    cash = client.get("/cash").json()
    assert (cash["balance"], cash["total_obligations"], cash["balance_after_obligations"]) == (3400.0, 3240.0, 160.0)


def test_approve_click_pays_and_updates_the_ticket(client):
    approval_id = queue("invoice", 501, 840, 101, "waiting_on_customer")
    assert [a["id"] for a in client.get("/approvals").json()["approvals"]] == [approval_id]
    r = client.post(f"/approvals/{approval_id}/approve", json={"decided_by": "andrew"})
    assert r.status_code == 200 and r.json()["result"]["new_balance"] == 2560.0
    assert client.get("/cash").json()["balance"] == 2560.0
    ticket = client.get("/tickets/101").json()
    assert ticket["status"] == "waiting_on_customer" and ticket["approvals"][0]["decided_by"] == "andrew"
    assert client.post(f"/approvals/{approval_id}/approve", json={"decided_by": "andrew"}).status_code == 400


def test_reject_click_pays_nothing(client):
    approval_id = queue("rent", 1, 2400, 102, "resolved")
    client.post(f"/approvals/{approval_id}/reject", json={"decided_by": "andrew"})
    assert client.get("/cash").json()["balance"] == 3400.0
    assert client.get("/tickets/102").json()["status"] == "escalated"


def test_money_in(client):
    r = client.post("/receipts", json={"amount": 464, "payer": "Yale AI Club", "memo": "Deposit",
                                       "received_by": "andrew", "ticket_id": 103})
    assert r.status_code == 200 and client.get("/cash").json()["balance"] == 3864.0
    assert client.get("/tickets/103").json()["receipts"][0]["recorded_by"] == "human:andrew"
    assert client.post("/receipts", json={"amount": -1, "payer": "x"}).status_code == 422


def test_resolve_waits_for_pending_approvals(client):
    queue("invoice", 501, 840, 101, "waiting_on_customer")
    assert client.post("/tickets/101/resolve", json={"decided_by": "andrew"}).status_code == 409
    assert client.post("/tickets/103/resolve", json={"decided_by": "andrew", "note": "done"}).status_code == 200
    assert client.get("/tickets/103").json()["state"] == "resolved"


def test_reset_restores_the_original(client):
    approval_id = queue("rent", 1, 2400, 102, "resolved")
    client.post(f"/approvals/{approval_id}/approve", json={"decided_by": "andrew"})
    client.post("/receipts", json={"amount": 50, "payer": "Walk-in"})
    assert client.get("/cash").json()["balance"] == 1050.0
    assert client.post("/reset").json()["cash"]["balance"] == 3400.0
    assert client.get("/approvals").json()["approvals"] == []
    assert client.get("/receipts").json()["receipts"] == []
