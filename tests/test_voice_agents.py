"""Command-level regressions for ScopeLock's live voice behavior.

These tests stop at the Guava command queue. They verify the exact persona and turn
transitions sent to the live voice runtime without placing a call or spending credits.
"""
from types import SimpleNamespace

from guava import Say, SuggestedAction
from guava.commands import (
    ReadScriptCommand,
    RetryTaskCommand,
    SendInstructionCommand,
    SetPersona,
    SetTaskCommand,
)
from guava.testing import MockCall
from guava.types.call_info import PSTNCallInfo

from scopelock.agents import household, institution, scripts
from scopelock.core.policy import PolicyDecision, PolicyService


CASE_ROW = {
    "holder_name": "Maria Gomez",
    "holder_phone": None,
    "institution": "Valley Health Plan",
    "issue_type": "denial",
    "issue_summary": "An MRI claim was denied.",
}


def _drain(call) -> list:
    commands = []
    while not call._command_queue.empty():
        commands.append(call._command_queue.get_nowait())
    return commands


def test_household_call_sends_one_complete_scopelock_persona_and_one_greeting():
    call = household.household._init_call(
        "household-persona",
        PSTNCallInfo(from_number="+15555550100", to_number="+15555550101"),
    )
    commands = _drain(call)

    personas = [command for command in commands if isinstance(command, SetPersona)]
    assert len(personas) == 1
    assert personas[0].agent_name == scripts.PRODUCT_NAME
    assert personas[0].organization_name == scripts.PRODUCT_NAME
    assert personas[0].agent_purpose == scripts.HOUSEHOLD_PURPOSE
    assert personas[0].tts_replacements == scripts.PRODUCT_PRONUNCIATIONS

    spoken = [command.script for command in commands if isinstance(command, ReadScriptCommand)]
    assert spoken == [scripts.HOUSEHOLD_GREETING_ES]


def test_institution_call_sends_one_complete_scopelock_persona(monkeypatch):
    monkeypatch.setattr(institution.relay, "pair_institution_call", lambda call: "case-1")
    monkeypatch.setattr(institution.db, "get_case", lambda case_id: CASE_ROW)
    monkeypatch.setattr(institution.relay, "HOUSEHOLD_AGENT", None)

    call = institution.institution._init_call(
        "institution-persona",
        PSTNCallInfo(from_number="+15555550102", to_number="+15555550103"),
    )
    commands = _drain(call)

    personas = [command for command in commands if isinstance(command, SetPersona)]
    assert len(personas) == 1
    assert personas[0].agent_name == scripts.PRODUCT_NAME
    assert personas[0].organization_name == scripts.PRODUCT_NAME
    assert personas[0].agent_purpose == scripts.INSTITUTION_PURPOSE
    assert personas[0].tts_replacements == scripts.PRODUCT_PRONUNCIATIONS

    spoken = [command.script for command in commands if isinstance(command, ReadScriptCommand)]
    assert spoken[0] == scripts.DISCLOSURE_EN
    assert scripts.PRODUCT_NAME in spoken[0]


def test_mandate_readback_and_confirmation_are_separate_turns(monkeypatch):
    monkeypatch.setattr(household.db, "create_case", lambda **kwargs: "case-1")
    monkeypatch.setattr(household.mandate, "create_case_mandate", lambda case_id: None)

    call = MockCall()
    call.set_variable("caller_phone", "+15555550100")
    call.set_field("holder_name", "Maria Gomez")
    call.set_field("institution", "Valley Health Plan")
    call.set_field("issue_type", "denial")
    call.set_field("issue_summary", "An MRI claim was denied.")
    call.set_field("member_id", None)
    call._command_queue.clear()

    household.on_intake_done(call)
    readback = next(command for command in call._command_queue if isinstance(command, SetTaskCommand))
    assert readback.task_id == "mandate_readback"
    assert [item.statement for item in readback.action_items if isinstance(item, Say)] == [
        scripts.MANDATE_READBACK_ES
    ]

    call._command_queue.clear()
    household.on_mandate_readback_done(call)
    confirmation = next(command for command in call._command_queue if isinstance(command, SetTaskCommand))
    assert confirmation.task_id == "mandate_confirm"
    assert not any(isinstance(item, Say) for item in confirmation.action_items)
    assert "do not repeat" in confirmation.objective.lower()


def test_unclear_confirmation_retries_question_without_replaying_mandate(monkeypatch):
    monkeypatch.setattr(household.mandate, "confirm", lambda case_id, utterance: None)
    monkeypatch.setattr(household.db, "mandate_confirmed", lambda case_id: False)
    call = MockCall()
    call.set_variable("case_id", "case-1")
    call.set_field("mandate_confirmed", "Tal vez.")
    call._command_queue.clear()

    household.on_mandate_confirmed(call)

    assert len(call._command_queue) == 1
    assert isinstance(call._command_queue[0], RetryTaskCommand)
    assert "do not repeat" in call._command_queue[0].reason.lower()


def test_forbidden_response_is_spoken_once_without_replacing_active_task(monkeypatch):
    monkeypatch.setattr(
        institution,
        "_intent_recognizer",
        SimpleNamespace(classify=lambda request: [SuggestedAction(key="agree_payment")]),
    )
    monkeypatch.setattr(
        PolicyService,
        "evaluate_action",
        lambda self, *args, **kwargs: PolicyDecision(
            decision="forbidden",
            may_execute=False,
            requires_holder=False,
            refusal=scripts.REFUSAL["agree_payment"],
            audit_event_id="event-1",
        ),
    )
    call = MockCall()
    call.set_variable("case_id", "case-1")
    call._command_queue.clear()

    assert institution.on_action_request(call, "Agree to a payment plan") is None
    assert not any(isinstance(command, SetTaskCommand) for command in call._command_queue)
    assert [
        command.script for command in call._command_queue if isinstance(command, ReadScriptCommand)
    ] == [scripts.REFUSAL["agree_payment"]]


def test_consult_resume_uses_one_continuation_task_without_second_trigger(monkeypatch):
    monkeypatch.setattr(institution.db, "get_case", lambda case_id: CASE_ROW)
    call = MockCall()
    call.set_variable("case_id", "case-1")
    call._command_queue.clear()
    answer = "Tuesday at 2 PM works for her."

    institution.resume_after_consult(call, answer)

    tasks = [command for command in call._command_queue if isinstance(command, SetTaskCommand)]
    assert len(tasks) == 1
    assert answer in tasks[0].objective
    assert tasks[0].objective.count(answer) == 1
    assert "do not repeat" in tasks[0].objective.lower()
    assert not any(isinstance(command, SendInstructionCommand) for command in call._command_queue)
