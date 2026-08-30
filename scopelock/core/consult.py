"""Holder decision lifecycle and live-call compatibility coordination."""
from __future__ import annotations

from scopelock.core import db, relay, translate

# case_id -> pending live-call metadata. Persistence lives only in decision_request.
PENDING: dict[str, dict] = {}
_QUEUED_VERBS: dict[str, str] = {}

HOLDING_LINE_EN = "One moment, I'm going to confirm that with her."
HOLDING_LINE_ES = "Un momento, voy a preguntarle eso a ella directamente."


def request_holder_decision(case_id: str, verb: str, question_en: str,
                            question_es: str) -> str:
    if db.get_case(case_id) is None:
        raise KeyError(f"unknown case: {case_id}")

    decision_id = db.new_id("dec")
    conn = db.connect()
    conn.execute(
        "INSERT INTO decision_request (id, case_id, verb, question_en, question_es, "
        "answer_es, answer_en, status, decided_by, latency_ms, created_at, resolved_at) "
        "VALUES (?, ?, ?, ?, ?, NULL, NULL, 'pending', NULL, NULL, ?, NULL)",
        (
            decision_id,
            case_id,
            verb,
            db.redact(question_en),
            db.redact(question_es),
            db.now(),
        ),
    )
    conn.commit()
    db.set_case_state(case_id, "consulting_holder")
    return decision_id


def resolve_holder_decision(decision_id: str, answer_es: str, answer_en: str,
                            latency_ms: int) -> None:
    if latency_ms < 0:
        raise ValueError("latency_ms must be non-negative")

    conn = db.connect()
    row = conn.execute(
        "SELECT case_id, status FROM decision_request WHERE id = ?", (decision_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown decision request: {decision_id}")
    if row["status"] != "pending":
        raise ValueError(f"decision request {decision_id} is already {row['status']}")

    # Security invariant: the holder identity is literal SQL, never caller-controlled.
    conn.execute(
        "UPDATE decision_request SET answer_es = ?, answer_en = ?, status = 'resolved', "
        "decided_by = 'holder', latency_ms = ?, resolved_at = ? WHERE id = ?",
        (
            db.redact(answer_es),
            db.redact(answer_en),
            latency_ms,
            db.now(),
            decision_id,
        ),
    )
    conn.commit()
    db.set_case_state(row["case_id"], "representing")


def to_plain_spanish(question_en: str) -> str:
    """Render the representative's question plainly, without institution jargon."""
    return translate.translate(
        f"In plain, simple language, not insurance jargon: {question_en}", "spanish"
    )


def queue_holder_verb(case_id: str, verb: str) -> None:
    """Carry the evaluated verb into the existing Guava action handler."""
    _QUEUED_VERBS[case_id] = verb


def is_pending(case_id: str) -> bool:
    return case_id in PENDING


def begin(case_id: str, question_en: str, question_es: str | None = None) -> dict:
    """Compatibility wrapper for the current live-call coordinator."""
    rendered_es = question_es or to_plain_spanish(question_en)
    verb = _QUEUED_VERBS.pop(case_id, "holder_decision")
    decision_id = request_holder_decision(case_id, verb, question_en, rendered_es)
    entry = {
        "decision_id": decision_id,
        "verb": verb,
        "question_en": question_en,
        "question_es": rendered_es,
        "timer": relay.LatencyTimer(),
    }
    PENDING[case_id] = entry
    relay.set_turn(case_id, "household")
    return entry


def complete(case_id: str, answer_es: str, answer_en: str | None = None) -> str:
    """Resolve the pending request with the holder's own answer and restore the rep leg."""
    entry = PENDING.pop(case_id, None)
    if entry is None:
        raise KeyError(f"case {case_id} has no pending holder decision")
    rendered_en = answer_en or translate.translate(answer_es, "english")
    resolve_holder_decision(
        entry["decision_id"],
        answer_es,
        rendered_en,
        entry["timer"].elapsed_ms(),
    )
    relay.set_turn(case_id, "institution")
    return entry["decision_id"]


def abandon(case_id: str) -> None:
    """Close a pending request without manufacturing a decision for the holder."""
    entry = PENDING.pop(case_id, None)
    _QUEUED_VERBS.pop(case_id, None)
    if entry is not None:
        conn = db.connect()
        conn.execute(
            "UPDATE decision_request SET status = 'abandoned', resolved_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (db.now(), entry["decision_id"]),
        )
        conn.commit()
        db.set_case_state(case_id, "representing")
    relay.set_turn(case_id, "institution")


def decision_count(case_id: str) -> int:
    row = db.connect().execute(
        "SELECT COUNT(*) AS count FROM decision_request "
        "WHERE case_id = ? AND status = 'resolved' AND decided_by = 'holder'",
        (case_id,),
    ).fetchone()
    return row["count"]
