"""C3 — the heart of A3. Two Guava Call objects, one policy in the middle.

The relay does not hold a conference; Guava's transfer() is a handoff and would leave
the mother alone with the rep, which is the failure this product exists to prevent
(see build spec 0.1). Instead we keep both legs as separate inbound Guava sessions and
arbitrate whose turn it is from here, in our own Expert code — not in a prompt.
"""
from __future__ import annotations

import time

from apoderado.core import db, mandate

# case_id -> {"household": Call | None, "institution": Call | None, "turn": str}
ACTIVE: dict[str, dict] = {}

# Set by agents/household.py at import time. Lets institution.py place the outbound
# callback (household.call_phone(...)) without importing agents/household.py directly —
# household.py already imports institution.py for resume_after_consult, so importing it
# back here would create a cycle.
HOUSEHOLD_AGENT = None


def open_institution_leg(case_id: str) -> None:
    """Gate: the institution leg may not be paired until the holder has confirmed the
    mandate aloud. Raises mandate.MandateNotConfirmed otherwise."""
    mandate.require_confirmed(case_id)
    db.set_case_state(case_id, "live")
    ACTIVE.setdefault(case_id, {"household": None, "institution": None, "turn": "institution"})


def register_household_call(case_id: str, call) -> None:
    ACTIVE.setdefault(case_id, {"household": None, "institution": None, "turn": "institution"})
    ACTIVE[case_id]["household"] = call
    db.set_case_session(case_id, session_a=call.id)


def pair_institution_call(call) -> str | None:
    """Dumb pairing for the demo: attach to the one open, mandate-confirmed case."""
    row = db.get_open_case()
    if row is None:
        return None
    case_id = row["id"]
    ACTIVE.setdefault(case_id, {"household": None, "institution": None, "turn": "institution"})
    ACTIVE[case_id]["institution"] = call
    db.set_case_session(case_id, session_b=call.id)
    return case_id


def household_call(case_id: str):
    return ACTIVE.get(case_id, {}).get("household")


def institution_call(case_id: str):
    return ACTIVE.get(case_id, {}).get("institution")


def turn(case_id: str) -> str:
    return ACTIVE.get(case_id, {}).get("turn", "institution")


def set_turn(case_id: str, who: str) -> None:
    ACTIVE.setdefault(case_id, {"household": None, "institution": None, "turn": "institution"})
    ACTIVE[case_id]["turn"] = who


def close_case(case_id: str) -> None:
    db.set_case_state(case_id, "closed")
    ACTIVE.pop(case_id, None)


class LatencyTimer:
    """Measures a relayed turn's round trip; store the real number, don't guess it."""

    def __init__(self):
        self._start = time.monotonic()

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._start) * 1000)
