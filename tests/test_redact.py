"""Sensitive values are masked before SQLite persistence and API display."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apoderado.api.server import app
from apoderado.core import db
from apoderado.core.redact import ID_REDACTION, SSN_REDACTION, redact


@pytest.fixture(autouse=True)
def clean_db():
    db.reset_db()
    yield


def _case() -> str:
    return db.create_case(
        holder_name="Maria Gomez",
        holder_lang="spanish",
        institution="Valley Health Plan",
        issue_type="denial",
        issue_summary="MRI claim denial",
    )


@pytest.mark.parametrize(
    ("raw", "marker"),
    [
        ("123-45-6789", SSN_REDACTION),
        ("123 45 6789", SSN_REDACTION),
        ("123456789", SSN_REDACTION),
        ("1 2 3, 4 5, 6 7 8 9", SSN_REDACTION),
        ("one two three, four five, six seven eight nine", SSN_REDACTION),
        ("uno dos tres, cuatro cinco, seis siete ocho nueve", SSN_REDACTION),
        ("Member ID: AB-12345678", ID_REDACTION),
        ("account number 9988 7766 55", ID_REDACTION),
        ("mbr-AB123456", ID_REDACTION),
    ],
)
def test_redact_masks_sensitive_patterns(raw: str, marker: str):
    result = redact(f"Before {raw} after")
    assert raw not in result
    assert marker in result
    assert redact(result) == result


def test_reference_number_is_not_mistaken_for_account_id():
    text = "The call reference is REF-84021."
    assert redact(text) == text


def test_ssn_is_redacted_before_transcript_and_consult_persistence():
    case_id = _case()
    raw = "Mi número es 123-45-6789."

    # Frozen Person C -> Person A seam: Person A places this same one-line call inside
    # db.py/consult.py at merge. This branch must not edit those owned files.
    safe = redact(raw)
    db.add_utterance(case_id, "household", "party", "spanish", safe, "call-test")
    db.record_consult(
        case_id,
        "What is the identifier?",
        "¿Cuál es el identificador?",
        safe,
        "My number is redacted.",
    )

    conn = db.connect()
    transcript_row = conn.execute(
        "SELECT text FROM utterance WHERE case_id = ?", (case_id,)
    ).fetchone()
    consult_row = conn.execute(
        "SELECT answer_es FROM decision_request WHERE case_id = ?", (case_id,)
    ).fetchone()
    assert transcript_row["text"] == safe
    assert consult_row["answer_es"] == safe
    assert "123-45-6789" not in transcript_row["text"]
    assert "123-45-6789" not in consult_row["answer_es"]

    response = TestClient(app).get("/api/state")
    assert response.status_code == 200
    assert "123-45-6789" not in response.text
    assert SSN_REDACTION in response.text


def test_member_id_is_redacted_before_transcript_persistence_and_state_output():
    case_id = _case()
    raw_id = "AB-12345678"
    safe = redact(f"My Member ID is {raw_id}.")
    db.add_utterance(case_id, "household", "party", "english", safe, "call-test")

    row = db.connect().execute(
        "SELECT text FROM utterance WHERE case_id = ?", (case_id,)
    ).fetchone()
    assert raw_id not in row["text"]
    assert ID_REDACTION in row["text"]

    response = TestClient(app).get("/api/state")
    assert response.status_code == 200
    assert raw_id not in response.text
    assert ID_REDACTION in response.text
