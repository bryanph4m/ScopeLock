"""Tri-state policy engine for every institution-side action."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from apoderado.agents.scripts import REFUSAL
from apoderado.core import db
from apoderado.core.mandate import DEFAULT_MANDATE, FORBIDDEN_ACTIONS

try:
    from apoderado.core.audit import record_event
except ImportError:
    # STUB — replace with person C's branch at merge
    def record_event(*args, **kwargs) -> str:
        return "evt_stub"


_PERMISSION_RANK = {"forbidden": 0, "requires_holder": 1, "allowed": 2}
_DEFAULT_REFUSAL = (
    "I'm not authorized to do that on this call. "
    "I can get a reference number and have her call back about that."
)


@dataclass
class PolicyDecision:
    decision: str
    may_execute: bool
    requires_holder: bool
    refusal: str | None
    audit_event_id: str


def _normalized_words(text: str) -> tuple[str, set[str]]:
    ascii_text = "".join(
        character
        for character in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(character)
    )
    words = re.findall(r"[a-z]+", ascii_text)
    return " ".join(words), set(words)


def _is_clear_affirmative(utterance: str) -> bool:
    normalized, words = _normalized_words(utterance)
    if not normalized:
        return False

    if words & {"no", "not", "never", "nunca", "maybe", "perhaps", "quizas", "quiza"}:
        return False
    if any(phrase in normalized for phrase in ("tal vez", "no se", "not sure", "it depends")):
        return False

    affirmative_phrases = (
        "si",
        "yes",
        "estoy de acuerdo",
        "de acuerdo",
        "confirmo",
        "claro",
        "vale",
        "okay",
        "ok",
        "i agree",
    )
    return any(
        re.search(rf"(?:^| ){re.escape(phrase)}(?: |$)", normalized)
        for phrase in affirmative_phrases
    )


class PolicyService:
    def create_draft(self, case_id: str,
                     overrides: dict[str, str] | None = None) -> None:
        if db.get_case(case_id) is None:
            raise KeyError(f"unknown case: {case_id}")

        rules = dict(DEFAULT_MANDATE)
        for verb, requested in (overrides or {}).items():
            if verb not in rules:
                raise KeyError(f"unknown policy verb: {verb}")
            if requested not in _PERMISSION_RANK:
                raise ValueError(f"invalid policy disposition: {requested}")

            # A draft may remove authority, never add more authority than the default.
            default = rules[verb]
            rules[verb] = (
                requested
                if _PERMISSION_RANK[requested] <= _PERMISSION_RANK[default]
                else default
            )

        db.create_mandate_rules(case_id, rules)
        db.set_case_state(case_id, "mandate_draft")

    def evaluate_action(self, case_id: str, verb: str, trigger: str,
                        source: str) -> PolicyDecision:
        rule = db.mandate_rule(case_id, verb)
        if verb in FORBIDDEN_ACTIONS or verb not in DEFAULT_MANDATE or rule is None:
            disposition = "forbidden"
        else:
            disposition = rule["disposition"]

        may_execute = disposition == "allowed"
        requires_holder = disposition == "requires_holder"
        refusal = REFUSAL.get(verb, _DEFAULT_REFUSAL) if disposition == "forbidden" else None
        result = (
            "allowed"
            if may_execute
            else "holder_decision_required"
            if requires_holder
            else "blocked"
        )
        audit_event_id = record_event(
            case_id=case_id,
            verb=verb,
            disposition=disposition,
            source=source,
            trigger_redacted=trigger,
            result=result,
        )
        return PolicyDecision(
            decision=disposition,
            may_execute=may_execute,
            requires_holder=requires_holder,
            refusal=refusal,
            audit_event_id=audit_event_id,
        )

    def restrict_action(self, case_id: str, verb: str) -> None:
        if verb not in DEFAULT_MANDATE:
            raise KeyError(f"unknown policy verb: {verb}")
        db.set_mandate_disposition(case_id, verb, "forbidden")

    def get_mandate(self, case_id: str) -> list[dict]:
        return [
            {
                "verb": row["verb"],
                "disposition": row["disposition"],
                "confirmed_by_holder": bool(row["confirmed_by_holder"]),
                "confirmed_utterance": row["confirmed_utterance"],
            }
            for row in db.mandate_rules(case_id)
        ]

    def confirm_mandate(self, case_id: str, utterance: str) -> None:
        if not _is_clear_affirmative(utterance):
            return
        if not db.mandate_rules(case_id):
            raise KeyError(f"case {case_id} has no mandate draft")
        db.confirm_mandate(case_id, utterance)
        db.set_case_state(case_id, "mandated")
