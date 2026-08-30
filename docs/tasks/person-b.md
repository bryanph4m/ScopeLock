# Person B — MCP Server

Branch: `person-b/mcp-server`. Read `docs/tasks/README.md` first for the shared
contract and integration order. Spec: `docs/build-spec.md` §5, §7, §9, §14.1.

## Why this exists

There is no `apoderado/mcp/` directory at all right now. An MCP server exposing case
policy and audit information is a **required demo outcome** (spec §3.1, item 11), not
an optional extra — the build isn't demo-ready without it regardless of how good the
phone flow is.

## Files you own

- `apoderado/mcp/__init__.py` — **new**, empty is fine.
- `apoderado/mcp/schemas.py` — **new**. Typed input/output models (pydantic or plain
  dataclasses, match whatever the official MCP Python SDK v2 expects) for every tool
  in §7.2 — mirror the JSON shapes in the spec exactly, including
  `get_active_case`'s redacted case summary and `evaluate_action`'s
  `{decision, may_execute, requires_holder, refusal, audit_event_id}` output.
- `apoderado/mcp/server.py` — **new**. Implement all 8 tools and 3 resources from
  spec §7.2/§7.3, run over stdio (streamable HTTP is post-demo, per spec §7.1):
  - `get_active_case`
  - `get_mandate`
  - `evaluate_action` — must return **the same decision** a direct
    `PolicyService.evaluate_action()` call would (test this explicitly).
  - `restrict_action` — reject attempts to enable hard-prohibited actions or modify
    an already-confirmed mandate.
  - `request_holder_decision` / `resolve_holder_decision` — thin wrappers over
    Person A's `consult.py` functions. The MCP layer only creates/records requests;
    it never decides anything itself.
  - `get_callback_card` — wraps the existing `apoderado/core/card.py` (already
    built, no changes needed there).
  - `get_audit_report` — wraps Person C's `audit.get_audit_report()`.
  - `run_safety_scenario` — takes a list of proposed verbs, returns how ScopeLock
    would handle each, **never** mutates the live case (run against a throwaway
    case copy or a pure evaluation path, not the real `case_id`).
  - Resources: `case://{case_id}/mandate`, `case://{case_id}/audit`,
    `case://{case_id}/callback-card` — all return redacted structured JSON. Do not
    expose raw transcripts as an MCP resource (spec §12, item 7).
- `pyproject.toml` — add the two missing direct dependencies:
  ```toml
  dependencies = [
    "guava-sdk",
    "fastapi",
    "uvicorn[standard]",
    "python-dotenv",
    "mcp>=2,<3",
  ]
  ```
  This is a small, isolated diff — nobody else touches this file, so it won't
  conflict at merge.
- `tests/test_mcp.py` — **new**. In-process MCP tool/resource tests per spec §14.1:
  - MCP `evaluate_action` returns the same decision as a direct `PolicyService` call.
  - MCP cannot enable a hard-prohibited action via `restrict_action`.
  - `run_safety_scenario` never changes the live case's actual mandate/state.

## Dependencies you need (stub if missing)

You're calling into Person A's not-yet-merged interface. Stub it locally so your
server and tests run standalone:

```python
# temporary stub in apoderado/mcp/server.py, delete at integration
class _PolicyServiceStub:
    def evaluate_action(self, case_id, verb, trigger, source):
        from apoderado.core.policy import PolicyDecision  # once policy.py exists, or inline the dataclass shape here
        return PolicyDecision(decision="allowed", may_execute=True,
                               requires_holder=False, refusal=None, audit_event_id="evt_stub")
```

Same idea for `consult.request_holder_decision` / `resolve_holder_decision` and
`audit.get_audit_report` — match the exact signatures in `docs/tasks/README.md` so
swapping the stub for the real import at merge time is a one-line change.

## Definition of done for this branch

- [ ] All 8 tools and 3 resources from spec §7.2/§7.3 exist and are wired to the MCP
      SDK's tool/resource registration.
- [ ] `evaluate_action` (MCP) and `PolicyService.evaluate_action` (direct) agree on
      every test case in `tests/test_mcp.py`.
- [ ] `run_safety_scenario` is provably side-effect-free (a test asserts the case
      row is unchanged after calling it).
- [ ] No MCP tool can set `decided_by="agent"` or confirm a mandate — confirmation
      only ever originates from the holder voice leg (spec §12, items 5-6).
- [ ] `uv run python -m apoderado.mcp.server` starts cleanly over stdio.
- [ ] `uv run pytest tests/test_mcp.py -q` passes.
