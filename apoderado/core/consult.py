"""C4 — the beat that wins the demo. Park the institution leg, pivot to Spanish,
ask her plainly, capture her answer, pivot back, deliver in English, count it.

decided_by is always 'holder' by construction (db.record_consult hardcodes it) — there
is no parameter and no code path that writes anything else. If the household leg cannot
get an answer from her, the caller is told the agent will call back. The agent never
decides on her behalf.
"""
from __future__ import annotations

from apoderado.core import db, relay, translate

# case_id -> {"question_en": str, "question_es": str, "timer": relay.LatencyTimer}
PENDING: dict[str, dict] = {}

HOLDING_LINE_EN = "One moment, I'm going to confirm that with her."
HOLDING_LINE_ES = "Un momento, voy a preguntarle eso a ella directamente."


def to_plain_spanish(question_en: str) -> str:
    """Render the rep's question in plain Spanish for her — not a translation of jargon."""
    return translate.translate(
        f"In plain, simple language, not insurance jargon: {question_en}", "spanish"
    )


def is_pending(case_id: str) -> bool:
    return case_id in PENDING


def begin(case_id: str, question_en: str, question_es: str | None = None) -> dict:
    """Step 1-3: park the institution leg, flip the turn, task the household leg."""
    entry = {
        "question_en": question_en,
        "question_es": question_es or to_plain_spanish(question_en),
        "timer": relay.LatencyTimer(),
    }
    PENDING[case_id] = entry
    relay.set_turn(case_id, "household")
    return entry


def complete(case_id: str, answer_es: str, answer_en: str | None = None) -> str:
    """Step 4-6: capture her verbatim answer, pivot back, deliver in English, count it."""
    entry = PENDING.pop(case_id, None)
    latency_ms = entry["timer"].elapsed_ms() if entry else None
    question_en = entry["question_en"] if entry else ""
    question_es = entry["question_es"] if entry else ""
    answer_en = answer_en or translate.translate(answer_es, "english")
    consult_id = db.record_consult(
        case_id, question_en, question_es, answer_es, answer_en, latency_ms=latency_ms
    )
    relay.set_turn(case_id, "institution")
    return consult_id


def abandon(case_id: str) -> None:
    """She could not be reached for an answer. The agent tells the institution it will
    call back — it never decides in her place."""
    PENDING.pop(case_id, None)
    relay.set_turn(case_id, "institution")


def decision_count(case_id: str) -> int:
    return len(db.consults(case_id))
