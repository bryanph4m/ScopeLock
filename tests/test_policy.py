"""Pure tri-state policy and persistence tests; no live Guava calls."""
from __future__ import annotations

import pytest

from apoderado.core import db


@pytest.fixture(autouse=True)
def clean_db():
    db.reset_db()
    yield


def test_schema_uses_tri_state_rules_and_one_decision_ledger():
    conn = db.connect()
    mandate_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(mandate_rule)").fetchall()
    }
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }

    assert "disposition" in mandate_columns
    assert "allowed" not in mandate_columns
    assert "policy_event" in tables
    assert "decision_request" in tables
    assert "consult" not in tables


def test_schema_exposes_the_nine_step_flow_plus_interrupted_terminal_state():
    assert db.CASE_STATES == (
        "intake",
        "mandate_draft",
        "mandated",
        "awaiting_institution",
        "connecting_holder",
        "representing",
        "consulting_holder",
        "closing",
        "closed",
        "interrupted",
    )

