"""The Mandate. Write tests first (tests/test_mandate.py) — this is pure logic, no telephony.

Two enforcement layers, and the order matters:
  Layer 1 (structural): forbidden verbs have no corresponding @on_action handler anywhere
  in apoderado/agents/institution.py. There is no code path that reaches them.
  Layer 2 (the guard): every candidate action on the institution leg is checked here first,
  against the per-case rules stored in mandate_rule. Layer 2 is what still catches a
  forbidden verb if it were ever wired up by mistake, and it's what produces the
  violation log the console lights up red.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from apoderado.agents.scripts import REFUSAL
from apoderado.core import db

# allowed
DEFAULT_MANDATE: dict[str, bool] = {
    "ask_reason": True,       # why was it denied
    "request_ref": True,      # get a reference number
    "request_written": True,  # ask for the policy in writing
    "escalate": True,         # ask for a supervisor
    "reschedule": True,
    # never
    "agree_payment": False,
    "accept_settlement": False,
    "change_coverage": False,
    "disclose_ssn": False,
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


@dataclass
class GuardResult:
    blocked: bool
    substitute: str | None = None


def create_case_mandate(case_id: str, overrides: dict[str, bool] | None = None) -> None:
    rules = dict(DEFAULT_MANDATE)
    if overrides:
        rules.update(overrides)
    db.create_mandate_rules(case_id, rules)


def confirm(case_id: str, utterance: str) -> None:
    db.confirm_mandate(case_id, utterance)


def is_confirmed(case_id: str) -> bool:
    return db.mandate_confirmed(case_id)


def require_confirmed(case_id: str) -> None:
    if not is_confirmed(case_id):
        raise MandateNotConfirmed(f"case {case_id} mandate not confirmed by holder")


def lookup(case_id: str, verb: str) -> sqlite3.Row | None:
    return db.mandate_rule(case_id, verb)


def guard(case_id: str, intent: str, text: str) -> GuardResult:
    """Every candidate utterance the institution-leg agent would speak passes through here."""
    rule = lookup(case_id, intent)
    if rule is None or not rule["allowed"]:
        db.log_violation(case_id, intent, trigger=text)
        substitute = REFUSAL.get(
            intent,
            "I'm not authorized to do that on this call. "
            "I can get a reference number and have her call back about that.",
        )
        return GuardResult(blocked=True, substitute=substitute)
    return GuardResult(blocked=False)
