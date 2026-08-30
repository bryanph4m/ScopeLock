"""C3 (institution side) + C7 disclosure. English primary — the judge/rep dials this leg.

Layer 1 of the Mandate lives here structurally: FORBIDDEN_ACTIONS never get an
@institution.on_action(...) handler. There is no task, field, or code path that reaches
"agree to a payment plan" — a jailbreak cannot reach a task that does not exist.

ALLOWED_ACTIONS / FORBIDDEN_ACTIONS themselves live in core/mandate.py (not here) so that
importing them — e.g. from apoderado/api/server.py, for the console — never triggers
guava.Agent()'s network auth. See mandate.py's module docstring.

Neither party has to stay on hold waiting for the other to dial in. She calls in once to
do intake and confirm the mandate, then hangs up — see agents/household.py. The moment the
representative calls this leg, on_call_start places an outbound callback to her real
number (captured from caller ID at intake) so she's live again before the case proceeds.
"""
from __future__ import annotations

import os

import guava
from guava import Agent, Field, Say, SuggestedAction
from guava.events import AgentSpeechEvent, CallerSpeechEvent
from guava.helpers.llm import IntentRecognizer

from apoderado.agents import scripts
from apoderado.core import card, consult, db, mandate, relay
from apoderado.core.util import safe

institution = Agent(
    name="Apoderado",
    organization="Apoderado",
    purpose=(
        "Represent an account holder to an institution representative, strictly within a "
        "mandate the account holder confirmed aloud before this call began."
    ),
)

# Layer 1: this set is populated ONLY by the @defined_action decorator below, which is the
# same decorator that registers the real @institution.on_action handler. A verb that never
# calls defined_action literally has no action to execute — see tests/test_mandate.py.
DEFINED_TASKS: set[str] = set()

_intent_recognizer = IntentRecognizer({**mandate.ALLOWED_ACTIONS, **mandate.FORBIDDEN_ACTIONS})


def defined_action(key: str):
    """Registers @institution.on_action(key) and records it in DEFINED_TASKS. Only call
    this for verbs the mandate allows — see module docstring."""
    DEFINED_TASKS.add(key)
    return institution.on_action(key)


def _represent_objective(row) -> str:
    return (
        f"You represent {row['holder_name']} regarding a {row['issue_type']} matter with "
        f"{row['institution']}. In her own words, here is what happened: {row['issue_summary']} "
        "The account holder is on another line right now and available to be consulted on "
        "anything that requires her decision. Find out why this happened, get a reference "
        "number for this call, and ask for anything relevant in writing. If there's no "
        "resolution on this call, ask to escalate to a supervisor."
    )


def _represent_checklist() -> list:
    return [
        Field(key="denial_reason", field_type="text",
              description="Why the institution says this happened", required=False),
        Field(key="reference_number", field_type="digit_sequence",
              description="A reference number for this call", required=False),
    ]


def start_representing(call: guava.Call, row) -> None:
    call.set_task("represent", objective=_represent_objective(row), checklist=_represent_checklist())


@institution.on_call_start
@safe
def on_call_start(call: guava.Call):
    # read_script() must be the agent's very first words — before any task, before any
    # LLM turn. This is the disclosure: bot-identification (Cal. B.O.T. Act), all-party
    # recording consent (CIPA, Penal Code 632), and FCC 24-17 artificial-voice notice.
    call.read_script(scripts.DISCLOSURE_EN)

    case_id = relay.pair_institution_call(call)
    if case_id is None:
        call.hangup("Apologize that there is no active case ready to receive this call right now, and end politely.")
        return

    row = db.get_case(case_id)
    call.set_variable("case_id", case_id)
    call.set_persona(organization_name="Apoderado")

    if row["holder_phone"] and relay.HOUSEHOLD_AGENT is not None:
        # She already confirmed the mandate and hung up — call her back now, live, rather
        # than making her wait on the line for the institution to call in.
        call.set_task(
            "connecting",
            objective="Tell the representative you are connecting the account holder now and to please hold briefly.",
            checklist=["Wait quietly for the account holder to join."],
        )
        relay.HOUSEHOLD_AGENT.call_phone(
            from_number=os.environ.get("HOUSEHOLD_NUMBER", ""),
            to_number=row["holder_phone"],
            variables={"case_id": case_id},
        )
    else:
        # Fallback: she's already live on the household leg (e.g. a test run without a
        # real caller-ID number available). Open the case immediately.
        start_representing(call, row)


@institution.on_task_complete("represent")
@safe
def on_represent_done(call: guava.Call):
    case_id = call.get_variable("case_id")
    reason = call.get_field("denial_reason")
    ref = call.get_field("reference_number")
    if reason:
        card.add_told(case_id, reason)
    if ref:
        card.set_reference(case_id, ref)
    card.set_next_step(case_id, "Follow up if the institution does not respond by the promised date.")

    call.hangup("Thank the representative for their time and end the call politely.")

    household = relay.household_call(case_id)
    if household is not None:
        household.set_task(
            "closing",
            objective="Read the call summary back to her in plain Spanish, exactly as given, then say goodbye.",
            checklist=[Say(statement=card.build_readback_es(case_id))],
        )
    relay.close_case(case_id)


@institution.on_task_complete("refusal")
@safe
def on_refusal_said(call: guava.Call):
    """The refusal was delivered verbatim via Say. Return to representing the case."""
    case_id = call.get_variable("case_id")
    row = db.get_case(case_id)
    start_representing(call, row)


@institution.on_action_request
@safe
def on_action_request(call: guava.Call, request: str) -> SuggestedAction | None:
    case_id = call.get_variable("case_id")
    suggestions = _intent_recognizer.classify(request)
    if not suggestions:
        return None
    action = suggestions[0]
    key = action.key

    if key in mandate.FORBIDDEN_ACTIONS:
        # Layer 2: the guard. Logs the violation and produces the verbatim refusal.
        result = mandate.guard(case_id, key, request)
        call.set_task("refusal", checklist=[Say(statement=result.substitute)])
        return None  # never becomes an action — Layer 1 means there's no handler to run anyway.

    return action


@defined_action("ask_reason")
@safe
def on_ask_reason(call: guava.Call):
    call.send_instruction("Ask why this happened, plainly and directly.")


@defined_action("request_ref")
@safe
def on_request_ref(call: guava.Call):
    call.send_instruction("Ask for a reference number for this call.")


@defined_action("request_written")
@safe
def on_request_written(call: guava.Call):
    call.send_instruction("Ask for this to be sent in writing or by mail.")


def _open_consult(call: guava.Call, case_id: str, question_en: str) -> None:
    consult.begin(case_id, question_en)
    entry = consult.PENDING[case_id]
    call.set_task("holding", objective="Wait quietly for further instructions before continuing.",
                  checklist=[Say(statement=consult.HOLDING_LINE_EN)])
    household = relay.household_call(case_id)
    if household is not None:
        household.set_task(
            "consult",
            objective=entry["question_es"],
            checklist=[Field(key="consult_answer", field_type="text",
                              description="Su respuesta, tal cual la diga")],
        )


@defined_action("reschedule")
@safe
def on_reschedule(call: guava.Call):
    case_id = call.get_variable("case_id")
    _open_consult(call, case_id, "The representative is proposing a new date or time. Does that work for her?")


@defined_action("escalate")
@safe
def on_escalate(call: guava.Call):
    case_id = call.get_variable("case_id")
    _open_consult(call, case_id, "The representative offered to escalate this to a supervisor. Does she want that?")


def resume_after_consult(call: guava.Call, answer_en: str) -> None:
    """Called from the household leg once her answer comes back. One-directional
    dependency: household.py imports this; institution.py never imports household.py."""
    case_id = call.get_variable("case_id")
    row = db.get_case(case_id)
    start_representing(call, row)
    call.send_instruction(
        f"The account holder just responded: {answer_en} Share this with the representative "
        "naturally and continue."
    )


@institution.on_caller_speech
@safe
def on_caller_speech(call: guava.Call, event: CallerSpeechEvent):
    case_id = call.get_variable("case_id")
    if case_id:
        db.add_utterance(case_id, "institution", "party", "english", event.utterance, call.id,
                          external_id=event.utterance_id)


@institution.on_agent_speech
@safe
def on_agent_speech(call: guava.Call, event: AgentSpeechEvent):
    case_id = call.get_variable("case_id")
    if case_id:
        db.add_utterance(case_id, "institution", "agent", "english", event.utterance, call.id)
