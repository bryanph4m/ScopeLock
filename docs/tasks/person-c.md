# Person C — Audit, Redaction, API & Console

Branch: `person-c/console-audit`. Read `docs/tasks/README.md` first for the shared
contract and integration order. Spec: `docs/build-spec.md` §9, §11, §12, §13, §14.1.

## Why this exists

The console currently shows a single decision counter and two chip states
(allowed/forbidden) — there's no `requires_holder` tier, no audit trail, no way to
tell a judge the displayed data is redacted, and no readiness check before going live.
The API only has `/api/state`; nothing exposes health, audit, or the final report.
And there's no redaction layer at all — an SSN spoken on the call would currently
persist and display in full.

The iMessage-style chat-thread rework (commit `92ba825`) already covers the
transcript/bubble part of spec §11 — you're extending that same file, not replacing
it.

## Files you own

- `apoderado/core/redact.py` — **new**. `redact(text: str) -> str`, masking SSN-like
  patterns (`\d{3}-\d{2}-\d{4}` and spoken-out variants like "one two three, four five,
  six seven eight nine") and member/account-ID-shaped substrings. Call this from
  wherever transcript/consult text gets persisted or returned by the API — that's a
  one-line call added inside Person A's `db.py` and `consult.py`, so coordinate the
  call site with them rather than editing those files yourself.
- `apoderado/core/audit.py` — **new**.
  - `record_event(case_id, verb, disposition, source, trigger_redacted, result) -> str`
    — inserts into `policy_event` (Person A's table) and returns its id.
  - `get_audit_report(case_id) -> list[dict]` — chronological, redacted: scope
    creation, confirmation, policy checks, consultations, refusals, closeout.
- `apoderado/api/server.py` — add:
  - `GET /api/health` — process, database, and MCP configuration readiness (check
    whether `apoderado/mcp/server.py` is importable/runnable, not that it's currently
    running).
  - `GET /api/cases/{case_id}/audit` — wraps `audit.get_audit_report()`.
  - `GET /api/cases/{case_id}/report` — final structured outcome + Spanish readback
    (wraps `apoderado/core/card.py`, already built).
  - Replace `allow_origins=["*"]` with explicit localhost origins (spec §13) — e.g.
    `["http://localhost:8000", "http://127.0.0.1:8000"]`, adjusted to whatever ports
    the console and API actually run on.
- `apoderado/console/index.html` — extend the existing chat-thread layout (don't
  rewrite it) with spec §11's remaining requirements:
  - **Amber `requires_holder` chip** alongside the current green/grey/red — this
    needs `mandate.disposition` from Person A's API payload; if that field isn't in
    `/api/state` yet, code against the frozen shape in `docs/tasks/README.md` and
    treat a missing field as `"allowed"` until it lands.
  - **Pending-decision panel** — English question, plain-Spanish question, and
    status, sourced from the `decision_request` rows once `/api/state` includes them.
  - **Unified audit timeline** with MCP/Guava source badges, backed by the new
    `/api/cases/{case_id}/audit` endpoint.
  - **Four-way decision counts** — holder decisions, agent decisions, refusals, and
    sensitive disclosures (replaces the current single "decisions by account holder"
    counter).
  - **Privacy indicator** — a small always-visible badge confirming displayed data
    is redacted.
  - **Demo-readiness strip** — both phone numbers configured, active case present,
    mandate confirmed, MCP server available — sourced from `/api/health`.
  - Do not add navigation, auth UI, or a frontend framework (spec §11, last line).
- `tests/test_redact.py` — **new**. Cover spec §14.1's redaction bullets:
  - SSN-like content never appears in persisted transcripts or `/api/state` output.
  - Redaction is applied before storage, not just at display time (assert against
    the DB row directly, not just the API response).

## Dependencies you need (stub if missing)

`mandate_rule.disposition`, the `decision_request` table, and `PolicyService` are
Person A's. If `/api/state` doesn't yet return disposition/decision-request data
when you start:

```python
# temporary stub in apoderado/api/server.py, delete at integration
# treat every mandate row as {"disposition": "allowed"} and decision_request as []
```

Build the console against the target shape regardless, so swapping in the real data
is just removing the stub.

## Definition of done for this branch

- [ ] SSN-shaped text typed into a test consult never appears unredacted in the DB
      or in any API response.
- [ ] `/api/health`, `/api/cases/{id}/audit`, `/api/cases/{id}/report` all return
      real data (not 404/500) against a seeded case.
- [ ] CORS is scoped to explicit localhost origins, not `*`.
- [ ] Console shows all three chip colors, the pending-decision panel, the audit
      timeline, four-way counts, the privacy indicator, and the readiness strip —
      verified visually via `/browse` against a seeded case, same as the bubble
      rework in commit `92ba825`.
- [ ] `uv run pytest tests/test_redact.py -q` passes.
