"""C6 backend. One endpoint, polled every 400ms by the console. No auth, no deployment
scope per spec 1.2 — this is a demo-night console, not a product."""
from __future__ import annotations

import importlib
import importlib.util
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from apoderado.core import audit, card, db
from apoderado.core.mandate import ALLOWED_ACTIONS, FORBIDDEN_ACTIONS
from apoderado.core.redact import redact

app = FastAPI(title="Apoderado console API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_methods=["GET"],
    allow_headers=["Accept", "Content-Type"],
)


def _current_case() -> dict | None:
    conn = db.connect()
    row = conn.execute(
        "SELECT * FROM kase WHERE state != 'closed' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM kase ORDER BY created_at DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def _table_exists(table: str) -> bool:
    return db.connect().execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def _redact_payload(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_payload(item) for key, item in value.items()}
    return value


def _decision_requests(case_id: str) -> list[dict]:
    # STUB — replace with Person A's db accessor at merge. Frozen target shape stays intact.
    if not _table_exists("decision_request"):
        return []
    return [
        dict(row)
        for row in db.connect()
        .execute(
            "SELECT * FROM decision_request WHERE case_id = ? ORDER BY created_at, id", (case_id,)
        )
        .fetchall()
    ]


def _mandate_rules(case_id: str) -> list[dict]:
    rules = [dict(row) for row in db.mandate_rules(case_id)]
    for rule in rules:
        # STUB — Person A adds mandate_rule.disposition. Frozen fallback is "allowed".
        rule.setdefault("disposition", "allowed")
        rule["verb_label"] = ALLOWED_ACTIONS.get(rule["verb"]) or FORBIDDEN_ACTIONS.get(
            rule["verb"], rule["verb"]
        )
    return rules


def _mcp_readiness() -> dict[str, bool]:
    try:
        spec = importlib.util.find_spec("apoderado.mcp.server")
    except (ImportError, ModuleNotFoundError, ValueError):
        spec = None

    if spec is None:
        return {"configured": False, "importable": False, "runnable": False, "ready": False}

    try:
        module = importlib.import_module("apoderado.mcp.server")
        candidates = (
            getattr(module, "main", None),
            getattr(module, "mcp", None),
            getattr(module, "server", None),
            getattr(module, "mcp_server", None),
        )
        runnable = any(
            callable(candidate) or callable(getattr(candidate, "run", None))
            for candidate in candidates
            if candidate is not None
        )
    except Exception:
        return {"configured": True, "importable": False, "runnable": False, "ready": False}

    return {
        "configured": True,
        "importable": True,
        "runnable": runnable,
        "ready": runnable,
    }


@app.get("/api/state")
def state():
    case = _current_case()
    if case is None:
        return {
            "case": None,
            "mandate": [],
            "transcript": [],
            "consults": [],
            "decision_requests": [],
            "violations": [],
            "card": None,
            "decision_count": 0,
        }

    case_id = case["id"]
    consults = [dict(row) for row in db.consults(case_id)]
    decisions = _decision_requests(case_id)
    holder_decision_count = sum(
        1
        for decision in decisions
        if decision.get("decided_by") == "holder"
        and decision.get("status") in {"resolved", "completed"}
    )
    payload = {
        "case": case,
        "mandate": _mandate_rules(case_id),
        "transcript": [dict(row) for row in db.utterances(case_id)],
        "consults": consults,
        "decision_requests": decisions,
        "violations": [dict(row) for row in db.violations(case_id)],
        "card": db.get_card(case_id),
        "decision_count": holder_decision_count if decisions else len(consults),
    }
    return _redact_payload(payload)


@app.get("/api/health")
def health():
    try:
        conn = db.connect()
        database_ready = conn.execute("SELECT 1").fetchone()[0] == 1 and _table_exists("kase")
        case = _current_case()
    except Exception:
        database_ready = False
        case = None

    active_case_ready = bool(case and case.get("state") != "closed")
    mandate_confirmed = False
    if database_ready and active_case_ready and case is not None:
        rows = db.mandate_rules(case["id"])
        mandate_confirmed = bool(rows) and all(row["confirmed_by_holder"] for row in rows)

    phone_numbers = {
        "household_configured": bool(os.environ.get("HOUSEHOLD_NUMBER")),
        "institution_configured": bool(os.environ.get("INSTITUTION_NUMBER")),
    }
    phone_numbers["ready"] = all(phone_numbers.values())
    mcp = _mcp_readiness()
    readiness = {
        "phone_numbers": phone_numbers["ready"],
        "active_case": active_case_ready,
        "mandate_confirmed": mandate_confirmed,
        "mcp_server": mcp["ready"],
    }
    all_ready = database_ready and all(readiness.values())
    return {
        "status": "ready" if all_ready else "not_ready",
        "ready": all_ready,
        "process": {"ready": True},
        "database": {"ready": database_ready},
        "mcp": mcp,
        "phone_numbers": phone_numbers,
        "active_case": {"ready": active_case_ready},
        "mandate": {"confirmed": mandate_confirmed},
        "readiness": readiness,
    }


@app.get("/api/cases/{case_id}/audit")
def case_audit(case_id: str):
    if db.get_case(case_id) is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return audit.get_audit_report(case_id)


@app.get("/api/cases/{case_id}/report")
def case_report(case_id: str):
    case = db.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    outcome = db.get_card(case_id) or {
        "case_id": case_id,
        "asked": [],
        "told": [],
        "reference_no": None,
        "agreed": None,
        "refused": [],
        "next_step": None,
    }
    return _redact_payload(
        {
            **outcome,
            "state": case["state"],
            "readback_es": card.build_readback_es(case_id),
        }
    )


app.mount("/", StaticFiles(directory="apoderado/console", html=True), name="console")
