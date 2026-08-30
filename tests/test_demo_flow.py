"""Pure state-machine walkthrough for the judge demo path; no Guava calls."""
from __future__ import annotations

from apoderado.core import db
from apoderado.core.policy import PolicyService


def _case() -> str:
    return db.create_case(
        holder_name="Maria Gomez",
        holder_lang="spanish",
        institution="Valley Health Plan",
        issue_type="denial",
        issue_summary="They denied her MRI claim.",
    )


def test_demo_walks_the_nine_state_happy_path_without_guava():
    db.reset_db()
    case_id = _case()
    service = PolicyService()
    visited = [db.get_case(case_id)["state"]]

    service.create_draft(case_id)
    visited.append(db.get_case(case_id)["state"])

    service.confirm_mandate(case_id, "Sí, estoy de acuerdo.")
    visited.append(db.get_case(case_id)["state"])

    for state in (
        "awaiting_institution",
        "connecting_holder",
        "representing",
        "consulting_holder",
        "closing",
        "closed",
    ):
        db.set_case_state(case_id, state)
        visited.append(db.get_case(case_id)["state"])

    assert tuple(visited) == db.CASE_STATES[:-1]


def test_interrupted_is_a_separate_valid_terminal_state():
    db.reset_db()
    case_id = _case()

    db.set_case_state(case_id, "interrupted")

    assert db.get_case(case_id)["state"] == "interrupted"
