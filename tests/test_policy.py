"""Pure tri-state policy and persistence tests; no live Guava calls."""
from __future__ import annotations

import pytest

from apoderado.core import db, mandate, policy, relay


@pytest.fixture(autouse=True)
def clean_db():
    db.reset_db()
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
