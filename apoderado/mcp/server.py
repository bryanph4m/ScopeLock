"""ScopeLock's MCP v2 stdio transport.

This module is intentionally an adapter: policy decisions, consultation state,
callback-card assembly, and audit reporting remain owned by their core modules.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Any, Iterator, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from apoderado.core import card, db, mandate
from apoderado.mcp.schemas import (
    ActiveCaseOutput,
    AuditEventOutput,
    AuditReportOutput,
    CallbackCardOutput,
    EvaluateActionInput,
    EvaluateActionOutput,
    GetActiveCaseInput,
    GetAuditReportInput,
    GetCallbackCardInput,
    GetMandateInput,
    MandateOutput,
    MandateRuleOutput,
    RequestHolderDecisionInput,
    RequestHolderDecisionOutput,
    ResolveHolderDecisionInput,
    ResolveHolderDecisionOutput,
    RestrictActionInput,
    RestrictActionOutput,
    RunSafetyScenarioInput,
    RunSafetyScenarioOutput,
    SafetyOutcome,
)


try:
    from apoderado.core.policy import PolicyDecision, PolicyService
except ImportError:
    # STUB — replace with person A/C's branch at merge
    @dataclass(frozen=True)
    class PolicyDecision:
        decision: str
        may_execute: bool
        requires_holder: bool
        refusal: str | None
        audit_event_id: str

    # STUB — replace with person A/C's branch at merge
    class _PolicyServiceStub:
        def create_draft(
            self, case_id: str, overrides: dict[str, str] | None = None
        ) -> None:
            boolean_overrides = None
            if overrides is not None:
                boolean_overrides = {
                    verb: disposition != "forbidden"
                    for verb, disposition in overrides.items()
                }
            mandate.create_case_mandate(case_id, boolean_overrides)

        def evaluate_action(
            self, case_id: str, verb: str, trigger: str, source: str
        ) -> PolicyDecision:
            return PolicyDecision(
                decision="allowed",
                may_execute=True,
                requires_holder=False,
                refusal=None,
                audit_event_id="evt_stub",
            )

        def restrict_action(self, case_id: str, verb: str) -> None:
            case = db.get_case(case_id)
            rule = db.mandate_rule(case_id, verb)
            if case is None or rule is None:
                raise ValueError("case or verb not found")
            if db.mandate_confirmed(case_id):
                raise ValueError("confirmed mandates cannot be modified")
            if verb in mandate.FORBIDDEN_ACTIONS or not bool(rule["allowed"]):
                raise ValueError("hard-prohibited actions cannot be modified")
            conn = db.connect()
            conn.execute(
                "UPDATE mandate_rule SET allowed = 0 WHERE case_id = ? AND verb = ?",
                (case_id, verb),
            )
            conn.commit()

        def get_mandate(self, case_id: str) -> list[dict[str, Any]]:
            rules: list[dict[str, Any]] = []
            for row in db.mandate_rules(case_id):
                allowed = bool(row["allowed"])
                if not allowed:
                    disposition = "forbidden"
                elif row["verb"] in mandate.NEEDS_HOLDER_DECISION:
                    disposition = "requires_holder"
                else:
                    disposition = "allowed"
                rules.append(
                    {
                        "verb": row["verb"],
                        "disposition": disposition,
                        "confirmed_by_holder": bool(row["confirmed_by_holder"]),
                        "confirmed_utterance": row["confirmed_utterance"],
                    }
                )
            return rules

    PolicyService = _PolicyServiceStub


try:
    from apoderado.core.consult import (
        request_holder_decision as _request_holder_decision,
        resolve_holder_decision as _resolve_holder_decision,
    )
except ImportError:
    _STUB_DECISION_REQUESTS: dict[str, dict[str, Any]] = {}

    # STUB — replace with person A/C's branch at merge
    def _request_holder_decision(
        case_id: str, verb: str, question_en: str, question_es: str
    ) -> str:
        decision_id = db.new_id("dec")
        _STUB_DECISION_REQUESTS[decision_id] = {
            "case_id": case_id,
            "verb": verb,
            "question_en": question_en,
            "question_es": question_es,
            "status": "pending",
        }
        return decision_id

    # STUB — replace with person A/C's branch at merge
    def _resolve_holder_decision(
        decision_id: str, answer_es: str, answer_en: str, latency_ms: int
    ) -> None:
        request = _STUB_DECISION_REQUESTS.get(decision_id)
        if request is None:
            raise ValueError("decision request not found")
        request.update(
            {
                "answer_es": answer_es,
                "answer_en": answer_en,
                "latency_ms": latency_ms,
                "status": "resolved",
                "decided_by": "holder",
            }
        )


try:
    from apoderado.core.audit import get_audit_report as _get_audit_report
except ImportError:
    # STUB — replace with person A/C's branch at merge
    def _get_audit_report(case_id: str) -> list[dict[str, Any]]:
        return []


ModelT = TypeVar("ModelT", bound=BaseModel)


def _validate(model_type: type[ModelT], **payload: object) -> ModelT:
    """Validate MCP input without reflecting input values into error messages."""
    try:
        return model_type.model_validate(payload)
    except ValidationError:
        raise ToolError(f"Invalid input for {model_type.__name__}.") from None


def _decision_model(decision: PolicyDecision) -> EvaluateActionOutput:
    payload = asdict(decision) if hasattr(decision, "__dataclass_fields__") else {
        "decision": decision.decision,
        "may_execute": decision.may_execute,
        "requires_holder": decision.requires_holder,
        "refusal": decision.refusal,
        "audit_event_id": decision.audit_event_id,
    }
    try:
        return EvaluateActionOutput.model_validate(payload)
    except ValidationError:
        raise ToolError("Policy service returned an invalid decision.") from None


def _row_value(row: dict[str, Any], key: str, default: Any = None) -> Any:
    return row[key] if key in row else default


def _mandate_output(case_id: str) -> MandateOutput:
    if db.get_case(case_id) is None:
        raise ToolError("Case not found.")
    try:
        raw_rules = PolicyService().get_mandate(case_id)
        rules = [
            MandateRuleOutput(
                verb=raw["verb"],
                disposition=raw["disposition"],
                confirmed_by_holder=bool(raw["confirmed_by_holder"]),
                confirmed_at=_row_value(raw, "confirmed_at"),
            )
            for raw in raw_rules
        ]
        return MandateOutput(case_id=case_id, rules=rules)
    except ToolError:
        raise
    except Exception:
        raise ToolError("Unable to retrieve the mandate.") from None


@contextmanager
def _throwaway_case_copy(case_id: str) -> Iterator[str]:
    """Clone only case/mandate rows and remove the clone after simulation."""
    conn = db.connect()
    source_case = db.get_case(case_id)
    if source_case is None:
        raise ToolError("Case not found.")

    throwaway_id = db.new_id("scn")
    case_columns = [row[1] for row in conn.execute("PRAGMA table_info(kase)")]
    case_values = [throwaway_id if column == "id" else source_case[column] for column in case_columns]
    placeholders = ", ".join("?" for _ in case_columns)
    columns_sql = ", ".join(f'"{column}"' for column in case_columns)
    conn.execute(
        f'INSERT INTO kase ({columns_sql}) VALUES ({placeholders})',
        case_values,
    )

    mandate_columns = [row[1] for row in conn.execute("PRAGMA table_info(mandate_rule)")]
    mandate_columns_sql = ", ".join(f'"{column}"' for column in mandate_columns)
    mandate_placeholders = ", ".join("?" for _ in mandate_columns)
    for source_rule in db.mandate_rules(case_id):
        values = []
        for column in mandate_columns:
            if column == "id":
                values.append(db.new_id("man"))
            elif column == "case_id":
                values.append(throwaway_id)
            else:
                values.append(source_rule[column])
        conn.execute(
            f'INSERT INTO mandate_rule ({mandate_columns_sql}) VALUES ({mandate_placeholders})',
            values,
        )
    conn.commit()

    try:
        yield throwaway_id
    finally:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'kase'"
            )
        ]
        for table in tables:
            columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
            if "case_id" in columns:
                conn.execute(f'DELETE FROM "{table}" WHERE case_id = ?', (throwaway_id,))
        conn.execute("DELETE FROM kase WHERE id = ?", (throwaway_id,))
        conn.commit()


server = MCPServer(
    name="apoderado-scopelock",
    description="Redacted case inspection and policy control for ScopeLock.",
)


@server.tool(structured_output=True)
def get_active_case() -> ActiveCaseOutput:
    """Return the current redacted case summary."""
    _validate(GetActiveCaseInput)
    row = db.get_open_case()
    if row is None:
        raise ToolError("No active case is available.")
    return ActiveCaseOutput(
        case_id=row["id"],
        state=row["state"],
        holder_language=row["holder_lang"],
        institution=row["institution"],
        issue_type=row["issue_type"],
    )


@server.tool(structured_output=True)
def get_mandate(case_id: str) -> MandateOutput:
    """Return redacted mandate rules and confirmation state."""
    request = _validate(GetMandateInput, case_id=case_id)
    return _mandate_output(request.case_id)


@server.tool(structured_output=True)
def evaluate_action(
    case_id: str, verb: str, trigger: str, source: str
) -> EvaluateActionOutput:
    """Evaluate an action through the shared PolicyService."""
    request = _validate(
        EvaluateActionInput,
        case_id=case_id,
        verb=verb,
        trigger=trigger,
        source=source,
    )
    try:
        decision = PolicyService().evaluate_action(
            request.case_id, request.verb, request.trigger, request.source
        )
    except Exception:
        raise ToolError("Policy evaluation failed.") from None
    return _decision_model(decision)


@server.tool(structured_output=True)
def restrict_action(case_id: str, verb: str) -> RestrictActionOutput:
    """Remove a safe action from an unconfirmed mandate; never enable one."""
    request = _validate(RestrictActionInput, case_id=case_id, verb=verb)
    try:
        PolicyService().restrict_action(request.case_id, request.verb)
    except Exception:
        raise ToolError("Restriction rejected by the policy service.") from None
    return RestrictActionOutput(
        case_id=request.case_id,
        verb=request.verb,
        disposition="forbidden",
    )


@server.tool(structured_output=True)
def request_holder_decision(
    case_id: str, verb: str, question_en: str, question_es: str
) -> RequestHolderDecisionOutput:
    """Create a pending holder decision request without deciding it."""
    request = _validate(
        RequestHolderDecisionInput,
        case_id=case_id,
        verb=verb,
        question_en=question_en,
        question_es=question_es,
    )
    try:
        decision_id = _request_holder_decision(
            request.case_id,
            request.verb,
            request.question_en,
            request.question_es,
        )
    except Exception:
        raise ToolError("Unable to create the holder decision request.") from None
    return RequestHolderDecisionOutput(decision_request_id=decision_id)


@server.tool(structured_output=True)
def resolve_holder_decision(
    decision_id: str, answer_es: str, answer_en: str, latency_ms: int
) -> ResolveHolderDecisionOutput:
    """Record the holder's bilingual answer; decided_by is always holder."""
    request = _validate(
        ResolveHolderDecisionInput,
        decision_id=decision_id,
        answer_es=answer_es,
        answer_en=answer_en,
        latency_ms=latency_ms,
    )
    try:
        _resolve_holder_decision(
            request.decision_id,
            request.answer_es,
            request.answer_en,
            request.latency_ms,
        )
    except Exception:
        raise ToolError("Unable to resolve the holder decision request.") from None
    return ResolveHolderDecisionOutput(decision_request_id=request.decision_id)


@server.tool(structured_output=True)
def get_callback_card(case_id: str) -> CallbackCardOutput:
    """Return the existing Callback Card shape plus its Spanish readback."""
    request = _validate(GetCallbackCardInput, case_id=case_id)
    if db.get_case(request.case_id) is None:
        raise ToolError("Case not found.")
    stored = db.get_card(request.case_id) or {
        "case_id": request.case_id,
        "asked": [],
        "told": [],
        "reference_no": None,
        "agreed": None,
        "refused": [],
        "next_step": None,
    }
    return CallbackCardOutput(
        **stored,
        readback_es=card.build_readback_es(request.case_id),
    )


@server.tool(structured_output=True)
def get_audit_report(case_id: str) -> AuditReportOutput:
    """Return Person C's chronological redacted event report."""
    request = _validate(GetAuditReportInput, case_id=case_id)
    if db.get_case(request.case_id) is None:
        raise ToolError("Case not found.")
    try:
        events = [
            AuditEventOutput.model_validate(event)
            for event in _get_audit_report(request.case_id)
        ]
    except Exception:
        raise ToolError("Unable to retrieve the audit report.") from None
    return AuditReportOutput(case_id=request.case_id, events=events)


@server.tool(structured_output=True)
def run_safety_scenario(
    case_id: str, proposed_verbs: list[str]
) -> RunSafetyScenarioOutput:
    """Evaluate proposed verbs against a disposable copy of the live case."""
    request = _validate(
        RunSafetyScenarioInput,
        case_id=case_id,
        proposed_verbs=proposed_verbs,
    )
    outcomes: list[SafetyOutcome] = []
    with _throwaway_case_copy(request.case_id) as throwaway_id:
        for verb in request.proposed_verbs:
            try:
                decision = PolicyService().evaluate_action(
                    throwaway_id,
                    verb,
                    trigger="MCP safety scenario",
                    source="mcp_safety_scenario",
                )
            except Exception:
                raise ToolError("Safety scenario evaluation failed.") from None
            outcome = _decision_model(decision)
            outcomes.append(SafetyOutcome(verb=verb, **outcome.model_dump()))
    return RunSafetyScenarioOutput(case_id=request.case_id, outcomes=outcomes)


@server.resource(
    "case://{case_id}/mandate",
    mime_type="application/json",
    description="Redacted mandate rules for a ScopeLock case.",
)
def mandate_resource(case_id: str) -> MandateOutput:
    return get_mandate(case_id)


@server.resource(
    "case://{case_id}/audit",
    mime_type="application/json",
    description="Redacted chronological audit events for a ScopeLock case.",
)
def audit_resource(case_id: str) -> AuditReportOutput:
    return get_audit_report(case_id)


@server.resource(
    "case://{case_id}/callback-card",
    mime_type="application/json",
    description="Structured Callback Card and Spanish readback for a ScopeLock case.",
)
def callback_card_resource(case_id: str) -> CallbackCardOutput:
    return get_callback_card(case_id)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
