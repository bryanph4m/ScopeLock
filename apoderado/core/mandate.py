"""Compatibility constants and legacy entry points for the tri-state policy service."""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from apoderado.core import db

DEFAULT_MANDATE: dict[str, str] = {
    "ask_reason": "allowed",
    "request_ref": "allowed",
    "request_written": "allowed",
    "escalate": "requires_holder",
    "reschedule": "requires_holder",
    "agree_payment": "forbidden",
    "accept_settlement": "forbidden",
    "change_coverage": "forbidden",
    "disclose_ssn": "forbidden",
}

# Plain data describing each verb, shared by apoderado/agents/institution.py (for intent
# classification) and apoderado/api/server.py (for console labels). Lives here — not in
# institution.py — so that importing it never triggers guava.Agent()'s network auth.
ALLOWED_ACTIONS: dict[str, str] = {
    "ask_reason": "the representative is explaining, or is being asked, why something happened",
    "request_ref": "getting or giving a reference number for this call",
    "request_written": "asking for something to be sent in writing or by mail",
    "escalate": "asking for, or being offered, a supervisor",
    "reschedule": "proposing or accepting a new appointment date or time",
}

FORBIDDEN_ACTIONS: dict[str, str] = {
    "agree_payment": "proposing or agreeing to a payment or a payment plan",
    "accept_settlement": "proposing or agreeing to a settlement or other arrangement",
    "change_coverage": "changing the account holder's coverage or plan",
    "disclose_ssn": "asking for or giving a Social Security number",
}

NEEDS_HOLDER_DECISION = {"reschedule", "escalate"}


class MandateNotConfirmed(Exception):
    """Raised when the institution leg is opened before the holder has confirmed the mandate aloud."""


def create_case_mandate(case_id: str,
                        overrides: dict[str, bool | str] | None = None) -> None:
    from apoderado.core.policy import PolicyService

    normalized: dict[str, str] = {}
    for verb, value in (overrides or {}).items():
        if isinstance(value, bool):
            normalized[verb] = DEFAULT_MANDATE.get(verb, "allowed") if value else "forbidden"
        else:
            normalized[verb] = value
    PolicyService().create_draft(case_id, normalized)


def confirm(case_id: str, utterance: str) -> None:
    from apoderado.core.policy import PolicyService

    PolicyService().confirm_mandate(case_id, utterance)


def is_confirmed(case_id: str) -> bool:
    return db.mandate_confirmed(case_id)


def require_confirmed(case_id: str) -> None:
    if not is_confirmed(case_id):
        raise MandateNotConfirmed(f"case {case_id} mandate not confirmed by holder")


def lookup(case_id: str, verb: str) -> sqlite3.Row | None:
    return db.mandate_rule(case_id, verb)


def guard(case_id: str, intent: str, text: str) -> SimpleNamespace:
    """Deprecated baseline adapter; institution-side code uses PolicyService directly."""
    from apoderado.core.policy import PolicyService

    decision = PolicyService().evaluate_action(
        case_id, intent, text, source="mandate_compat"
    )
    blocked = not decision.may_execute
    if blocked:
        db.log_violation(case_id, intent, trigger=text)
    return SimpleNamespace(blocked=blocked, substitute=decision.refusal)
