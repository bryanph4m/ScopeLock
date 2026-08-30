"""C1 Intake + C2 mandate readback/confirmation + C4 household side of the consult pivot.
Spanish primary — the mother dials this leg.

Neither party waits on hold for the other. She calls in once, does intake, confirms the
mandate, and hangs up. Her real number is captured automatically from caller ID (not
asked for) and stored on the case. The moment the institution calls in, its on_call_start
places an outbound callback to her (see agents/institution.py) — on_reach_person below
picks that up and brings her back onto a fresh session, live, without her having to
dial anything or wait on the line herself.
"""
from __future__ import annotations

import guava
from guava import Agent, Field, Say
from guava.events import AgentSpeechEvent, CallerSpeechEvent

from apoderado.agents import institution, scripts
from apoderado.core import consult, db, mandate, relay, translate
from apoderado.core.util import safe

household = Agent(
    name="Apoderado",
    organization="Apoderado",
    purpose="Take a household's case in Spanish and represent them to an institution.",
)

# See core/relay.py's HOUSEHOLD_AGENT docstring: lets institution.py place the outbound
# callback without importing this module (which would create an import cycle, since this
# module already imports institution.py for resume_after_consult).
relay.HOUSEHOLD_AGENT = household


@household.on_call_start
@safe
def on_call_start(call: guava.Call):
    call.set_language_mode(primary="spanish", secondary=["english"])
    call.set_persona(organization_name="Apoderado")

    case_id = call.get_variable("case_id")
    if case_id:
        # Outbound callback: bring her back onto an already-mandated case rather than
        # running intake again. reach_person() handles voicemail/wrong-number gracefully.
        row = db.get_case(case_id)
        call.reach_person(
            contact_full_name=row["holder_name"],
            greeting=(
                f"Hola, soy Apoderado. El representante de {row['institution']} esta en la "
                "linea ahora mismo sobre su caso. ¿Puede hablar?"
            ),
            voicemail_message="Por favor devuelvanos la llamada; el representante esta esperando en la linea.",
        )
        return

    call.set_variable("caller_phone", call.call_info.from_number)
    call.set_task(
        "intake",
        objective=(
            "Understand who is calling, which institution, and what happened. "
            "Speak only in Spanish unless she switches to English herself."
        ),
        checklist=[
            Field(key="holder_name", field_type="text", sensitive=True,
                  description="Su nombre completo"),
            Field(key="institution", field_type="text",
                  description="El nombre de la institucion o compania"),
            Field(key="issue_type", field_type="multiple_choice",
                  choices=["denial", "billing", "reschedule", "dispute"],
                  description="El tipo de problema que tiene"),
            Field(key="issue_summary", field_type="text",
                  description="Lo que paso, en sus propias palabras. No parafrasear."),
            Field(key="member_id", field_type="text", sensitive=True, required=False,
                  description="Su numero de miembro o de cuenta, si lo tiene a mano"),
        ],
    )


@household.on_task_complete("intake")
@safe
def on_intake_done(call: guava.Call):
    case_id = db.create_case(
        holder_name=call.get_field("holder_name"),
        holder_lang="spanish",
        institution=call.get_field("institution"),
        issue_type=call.get_field("issue_type"),
        issue_summary=call.get_field("issue_summary"),
        holder_phone=call.get_variable("caller_phone"),
    )
    call.set_variable("case_id", case_id)
    call.set_variable("member_id", call.get_field("member_id") or "")
    mandate.create_case_mandate(case_id)

    call.set_task(
        "mandate_confirm",
        objective=(
            "Read the mandate statement to her exactly as given, word for word, then wait "
            "for her clear verbal yes before continuing."
        ),
        checklist=[
            Say(statement=scripts.MANDATE_READBACK_ES),
            Field(key="mandate_confirmed", field_type="text",
                  description="Su respuesta confirmando que esta de acuerdo, tal cual la diga"),
        ],
    )


@household.on_task_complete("mandate_confirm")
@safe
def on_mandate_confirmed(call: guava.Call):
    case_id = call.get_variable("case_id")
    utterance = call.get_field("mandate_confirmed")
    mandate.confirm(case_id, utterance)
    relay.open_institution_leg(case_id)
    call.hangup(
        "Let her know you have everything you need and she can hang up now — she does not "
        "need to stay on the line. Tell her you will call her back automatically the moment "
        f"{call.get_field('institution')} calls in on the number she can give them."
    )


@household.on_reach_person
@safe
def on_reach_person(call: guava.Call, outcome: str):
    case_id = call.get_variable("case_id")
    inst_call = relay.institution_call(case_id)

    if outcome != "available":
        if inst_call is not None:
            inst_call.hangup(
                "Apologize that the account holder could not be reached just now, take a "
                "reference number or message if offered, and let them know she will call back."
            )
        relay.close_case(case_id)
        return

    row = db.get_case(case_id)
    relay.register_household_call(case_id, call)
    call.set_task(
        "waiting",
        objective="Let her know she is connected and the representative is on the line. Then wait quietly.",
    )
    if inst_call is not None:
        institution.start_representing(inst_call, row)


@household.on_task_complete("consult")
@safe
def on_consult_answered(call: guava.Call):
    case_id = call.get_variable("case_id")
    answer_es = call.get_field("consult_answer")
    answer_en = translate.translate(answer_es, "english")
    consult.complete(case_id, answer_es, answer_en)

    inst_call = relay.institution_call(case_id)
    if inst_call is not None:
        institution.resume_after_consult(inst_call, answer_en)

    call.set_task(
        "waiting",
        objective="Wait quietly until you have something new to tell her.",
    )


@household.on_task_complete("closing")
@safe
def on_closing_done(call: guava.Call):
    call.hangup("Say goodbye warmly.")


@household.on_caller_speech
@safe
def on_caller_speech(call: guava.Call, event: CallerSpeechEvent):
    case_id = call.get_variable("case_id")
    if case_id:
        db.add_utterance(case_id, "household", "party", "spanish", event.utterance, call.id,
                          external_id=event.utterance_id)


@household.on_agent_speech
@safe
def on_agent_speech(call: guava.Call, event: AgentSpeechEvent):
    case_id = call.get_variable("case_id")
    if case_id:
        db.add_utterance(case_id, "household", "agent", "spanish", event.utterance, call.id)
