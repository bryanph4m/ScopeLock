"""Pure logic, no telephony. Write these first, per spec 5.4."""
import pytest

from scopelock.core import db, mandate


@pytest.fixture(autouse=True)
def clean_db():
    db.reset_db()
    yield


def make_case() -> str:
    case_id = db.create_case(
        holder_name="Maria Gomez",
        holder_lang="spanish",
        institution="Valley Health Plan",
        issue_type="denial",
        issue_summary="They denied her MRI claim.",
    )
    mandate.create_case_mandate(case_id)
    return case_id


def test_forbidden_verb_has_no_task():
    from scopelock.agents import institution
    assert "agree_payment" not in institution.DEFINED_TASKS
    assert "accept_settlement" not in institution.DEFINED_TASKS
    assert "change_coverage" not in institution.DEFINED_TASKS
    assert "disclose_ssn" not in institution.DEFINED_TASKS


def test_allowed_verbs_do_have_tasks():
    from scopelock.agents import institution
    for verb in ("ask_reason", "request_ref", "request_written", "escalate", "reschedule"):
        assert verb in institution.DEFINED_TASKS


def test_guard_allows_permitted_verb():
    case = make_case()
    result = mandate.guard(case, "ask_reason", "Why was this denied?")
    assert not result.blocked
    assert db.violations(case) == []


def test_guard_blocks_and_logs():
    case = make_case()
    r = mandate.guard(case, "disclose_ssn", "Sure, it's 555...")
    assert r.blocked and "not authorized" in r.substitute
    assert db.violations(case)[-1]["verb"] == "disclose_ssn"


def test_guard_blocks_unknown_verb_by_default():
    case = make_case()
    r = mandate.guard(case, "totally_made_up_verb", "do the thing")
    assert r.blocked
    assert db.violations(case)[-1]["verb"] == "totally_made_up_verb"


def test_unconfirmed_mandate_blocks_bridge():
    from scopelock.core import relay
    case = make_case()
    with pytest.raises(mandate.MandateNotConfirmed):
        relay.open_institution_leg(case)


def test_confirmed_mandate_allows_bridge():
    from scopelock.core import relay
    case = make_case()
    mandate.confirm(case, "Si, estoy de acuerdo.")
    # Should not raise.
    relay.open_institution_leg(case)


def test_confirmed_utterance_is_stored_verbatim():
    case = make_case()
    utterance = "Si, entiendo y estoy de acuerdo con eso."
    mandate.confirm(case, utterance)
    rows = db.mandate_rules(case)
    assert all(r["confirmed_utterance"] == utterance for r in rows)
    assert mandate.is_confirmed(case)
