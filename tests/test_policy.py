"""Pure tri-state policy and persistence tests; no live Guava calls."""
from __future__ import annotations

import inspect
import sqlite3
from types import SimpleNamespace

import pytest

from apoderado.core import consult, db, mandate, policy, relay


@pytest.fixture(autouse=True)
def clean_db():
    db.reset_db()
    consult.PENDING.clear()
    consult._QUEUED_VERBS.clear()
    yield


def make_case() -> str:
    return db.create_case(
        holder_name="Maria Gomez",
        holder_lang="spanish",
        institution="Valley Health Plan",
        issue_type="denial",
        issue_summary="They denied her MRI claim.",
    )


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


def test_policy_exposes_all_three_default_dispositions():
    case_id = make_case()
    service = policy.PolicyService()
    service.create_draft(case_id)

    assert service.evaluate_action(
        case_id, "ask_reason", "Why?", "test"
    ).decision == "allowed"
    consult = service.evaluate_action(case_id, "reschedule", "Next Tuesday?", "test")
    assert consult.decision == "requires_holder"
    assert consult.requires_holder and not consult.may_execute
    blocked = service.evaluate_action(case_id, "agree_payment", "$40 monthly", "test")
    assert blocked.decision == "forbidden"
    assert not blocked.may_execute and blocked.refusal


def test_draft_overrides_can_narrow_but_never_expand_authority():
    case_id = make_case()
    service = policy.PolicyService()
    service.create_draft(
        case_id,
        {
            "ask_reason": "requires_holder",
            "reschedule": "allowed",
            "agree_payment": "allowed",
        },
    )

    dispositions = {row["verb"]: row["disposition"] for row in service.get_mandate(case_id)}
    assert dispositions["ask_reason"] == "requires_holder"
    assert dispositions["reschedule"] == "requires_holder"
    assert dispositions["agree_payment"] == "forbidden"


def test_restrict_action_blocks_a_normally_safe_verb():
    case_id = make_case()
    service = policy.PolicyService()
    service.create_draft(case_id)

    service.restrict_action(case_id, "ask_reason")

    decision = service.evaluate_action(case_id, "ask_reason", "Why?", "test")
    assert decision.decision == "forbidden"
    assert not decision.may_execute


def test_unknown_verbs_default_block_and_are_audited(monkeypatch):
    case_id = make_case()
    policy.PolicyService().create_draft(case_id)
    recorded = []

    def fake_record_event(**event):
        recorded.append(event)
        return "evt_unknown"

    monkeypatch.setattr(policy, "record_event", fake_record_event)
    decision = policy.PolicyService().evaluate_action(
        case_id, "invented_verb", "Do something new", "test_harness"
    )

    assert decision.decision == "forbidden"
    assert decision.audit_event_id == "evt_unknown"
    assert recorded == [
        {
            "case_id": case_id,
            "verb": "invented_verb",
            "disposition": "forbidden",
            "source": "test_harness",
            "trigger_redacted": "Do something new",
            "result": "blocked",
        }
    ]


@pytest.mark.parametrize("utterance", ["maybe", "tal vez", "No", "quizás sí", ""])
def test_ambiguous_or_negative_text_does_not_confirm(utterance):
    case_id = make_case()
    service = policy.PolicyService()
    service.create_draft(case_id)

    service.confirm_mandate(case_id, utterance)

    assert not db.mandate_confirmed(case_id)
    assert db.get_case(case_id)["state"] == "mandate_draft"
    with pytest.raises(mandate.MandateNotConfirmed):
        relay.open_institution_leg(case_id)


def test_clear_affirmative_confirms_and_opens_the_institution_leg():
    case_id = make_case()
    service = policy.PolicyService()
    service.create_draft(case_id)

    service.confirm_mandate(case_id, "Sí, entiendo y estoy de acuerdo.")
    relay.open_institution_leg(case_id)

    assert db.mandate_confirmed(case_id)
    assert db.get_case(case_id)["state"] == "awaiting_institution"


def test_get_mandate_returns_only_the_frozen_contract_fields():
    case_id = make_case()
    service = policy.PolicyService()
    service.create_draft(case_id)

    assert service.get_mandate(case_id)
    assert set(service.get_mandate(case_id)[0]) == {
        "verb",
        "disposition",
        "confirmed_by_holder",
        "confirmed_utterance",
    }


def test_holder_decision_lifecycle_counts_only_resolved_requests():
    case_id = make_case()
    decision_id = consult.request_holder_decision(
        case_id,
        "reschedule",
        "Does next Tuesday work?",
        "¿Le sirve el próximo martes?",
    )
    pending = db.connect().execute(
        "SELECT * FROM decision_request WHERE id = ?", (decision_id,)
    ).fetchone()

    assert pending["status"] == "pending"
    assert pending["decided_by"] is None
    assert consult.decision_count(case_id) == 0

    consult.resolve_holder_decision(decision_id, "Sí.", "Yes.", 37)
    resolved = db.connect().execute(
        "SELECT * FROM decision_request WHERE id = ?", (decision_id,)
    ).fetchone()

    assert resolved["status"] == "resolved"
    assert resolved["decided_by"] == "holder"
    assert resolved["latency_ms"] == 37
    assert resolved["resolved_at"]
    assert consult.decision_count(case_id) == 1


def test_decided_by_cannot_be_supplied_through_the_public_resolver():
    parameters = inspect.signature(consult.resolve_holder_decision).parameters
    assert "decided_by" not in parameters

    with pytest.raises(TypeError):
        consult.resolve_holder_decision(
            "dec_fake",
            "Sí.",
            "Yes.",
            10,
            decided_by="agent",
        )


def test_decision_schema_rejects_non_holder_decider():
    case_id = make_case()
    decision_id = consult.request_holder_decision(case_id, "reschedule", "Q", "P")

    with pytest.raises(sqlite3.IntegrityError):
        db.connect().execute(
            "UPDATE decision_request SET decided_by = 'agent' WHERE id = ?",
            (decision_id,),
        )


def test_abandoned_decision_is_not_counted():
    case_id = make_case()
    consult.queue_holder_verb(case_id, "reschedule")
    entry = consult.begin(case_id, "Does Tuesday work?", "¿Le sirve el martes?")

    consult.abandon(case_id)

    row = db.connect().execute(
        "SELECT * FROM decision_request WHERE id = ?", (entry["decision_id"],)
    ).fetchone()
    assert row["status"] == "abandoned"
    assert row["decided_by"] is None
    assert consult.decision_count(case_id) == 0


def test_decision_text_uses_the_db_redaction_seam(monkeypatch):
    case_id = make_case()
    monkeypatch.setattr(db, "redact", lambda text: f"redacted:{text}")
    decision_id = consult.request_holder_decision(case_id, "reschedule", "Q-en", "Q-es")
    consult.resolve_holder_decision(decision_id, "A-es", "A-en", 1)

    row = db.connect().execute(
        "SELECT * FROM decision_request WHERE id = ?", (decision_id,)
    ).fetchone()
    assert row["question_en"] == "redacted:Q-en"
    assert row["question_es"] == "redacted:Q-es"
    assert row["answer_es"] == "redacted:A-es"
    assert row["answer_en"] == "redacted:A-en"


def test_forbidden_verbs_have_no_executable_institution_handler():
    from apoderado.agents import institution

    assert institution.DEFINED_TASKS.isdisjoint(mandate.FORBIDDEN_ACTIONS)


@pytest.mark.parametrize("verb", sorted(mandate.ALLOWED_ACTIONS))
def test_every_normally_safe_verb_passes_through_policy_service(
    monkeypatch, verb
):
    from apoderado.agents import institution

    case_id = make_case()
    action = SimpleNamespace(key=verb)
    monkeypatch.setattr(
        institution._intent_recognizer,
        "classify",
        lambda request: [action],
    )
    evaluated = []

    def fake_evaluate(self, case_id_arg, verb_arg, trigger, source):
        evaluated.append((case_id_arg, verb_arg, trigger, source))
        requires_holder = verb_arg in mandate.NEEDS_HOLDER_DECISION
        return policy.PolicyDecision(
            decision="requires_holder" if requires_holder else "allowed",
            may_execute=not requires_holder,
            requires_holder=requires_holder,
            refusal=None,
            audit_event_id="evt_test",
        )

    monkeypatch.setattr(policy.PolicyService, "evaluate_action", fake_evaluate)
    call = SimpleNamespace(
        get_variable=lambda key: case_id,
        set_task=lambda *args, **kwargs: None,
    )

    returned = institution.on_action_request(call, f"request for {verb}")

    assert returned is action
    assert evaluated == [
        (case_id, verb, f"request for {verb}", "institution_agent")
    ]


def test_per_case_restriction_blocks_safe_verb_at_institution_call_site(monkeypatch):
    from apoderado.agents import institution

    case_id = make_case()
    service = policy.PolicyService()
    service.create_draft(case_id)
    service.restrict_action(case_id, "ask_reason")
    action = SimpleNamespace(key="ask_reason")
    monkeypatch.setattr(
        institution._intent_recognizer,
        "classify",
        lambda request: [action],
    )
    tasks = []
    call = SimpleNamespace(
        get_variable=lambda key: case_id,
        set_task=lambda *args, **kwargs: tasks.append((args, kwargs)),
    )

    returned = institution.on_action_request(call, "Why was the claim denied?")

    assert returned is None
    assert tasks and tasks[0][0][0] == "refusal"
