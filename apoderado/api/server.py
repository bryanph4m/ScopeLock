"""C6 backend. One endpoint, polled every 400ms by the console. No auth, no deployment
scope per spec 1.2 — this is a demo-night console, not a product."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from apoderado.core import db
from apoderado.core.mandate import ALLOWED_ACTIONS, FORBIDDEN_ACTIONS

app = FastAPI(title="Apoderado console API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def _current_case() -> dict | None:
    conn = db.connect()
    row = conn.execute(
        "SELECT * FROM kase WHERE state != 'closed' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM kase ORDER BY created_at DESC LIMIT 1").fetchone()
    return dict(row) if row else None


@app.get("/api/state")
def state():
    case = _current_case()
    if case is None:
        return {
            "case": None,
            "mandate": [],
            "transcript": [],
            "consults": [],
            "violations": [],
            "card": None,
            "decision_count": 0,
        }

    case_id = case["id"]
    rules = [dict(r) for r in db.mandate_rules(case_id)]
    for r in rules:
        r["verb_label"] = ALLOWED_ACTIONS.get(r["verb"]) or FORBIDDEN_ACTIONS.get(r["verb"], r["verb"])

    return {
        "case": case,
        "mandate": rules,
        "transcript": [dict(u) for u in db.utterances(case_id)],
        "consults": [dict(c) for c in db.consults(case_id)],
        "violations": [dict(v) for v in db.violations(case_id)],
        "card": db.get_card(case_id),
        "decision_count": len(db.consults(case_id)),
    }


app.mount("/", StaticFiles(directory="apoderado/console", html=True), name="console")
