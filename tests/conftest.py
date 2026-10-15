"""Shared test setup.

Every test runs on a scratch copy of the untouched original (data/campus_customs.db) with a scratch audit
trail, so data/campus_customs_new.db and output/audit_trail.json are never touched. No LLM calls are made.

Run from hw5/:  venv/bin/python -m pytest
"""

import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

HW_DIR = Path(__file__).resolve().parent.parent
ORIGINAL_DB = HW_DIR / "data" / "campus_customs.db"
SCRATCH = Path(tempfile.mkdtemp(prefix="campus_customs_tests_"))
SCRATCH_DB = SCRATCH / "campus_customs_test.db"

# The server, team and API read these at import time, so they're set before any of them is imported.
os.environ["CAMPUS_CUSTOMS_DB"] = str(SCRATCH_DB)
os.environ["AUDIT_TRAIL_PATH"] = str(SCRATCH / "audit_trail.json")
os.environ.setdefault("PORTKEY_API_KEY", "unused-in-tests")  # the model client is built on import, never called
sys.path[:0] = [str(HW_DIR / "mcp_server"), str(HW_DIR / "backend")]

import server  # noqa: E402  (after the env override above)


@pytest.fixture(autouse=True)
def fresh_db():
    """Start every test from the original shop data: checking $3,400.00, nothing paid or queued."""
    assert server.DB_PATH == SCRATCH_DB, "tests must never run against the real working database"
    with closing(sqlite3.connect(ORIGINAL_DB)) as src, closing(sqlite3.connect(SCRATCH_DB)) as dst:
        src.backup(dst)


@pytest.fixture
def sql():
    """Read the scratch database directly, independent of the MCP tools."""
    def query(statement: str, *params):
        with closing(sqlite3.connect(SCRATCH_DB)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(statement, params)]
    return query


@pytest.fixture
def balance(sql):
    return lambda: sql("SELECT balance FROM cash_accounts WHERE name = 'checking'")[0]["balance"]


@pytest.fixture
def ask(sql):
    """request_approval as the Boss would call it (pending until a human decides)."""
    def request(kind: str, ref_id: int, amount: float, ticket_id: int | None = None, **extra):
        return server.request_approval(kind=kind, ref_id=ref_id, amount=amount, reason="test", requested_by="boss",
                                       ticket_id=ticket_id, **extra)
    return request
