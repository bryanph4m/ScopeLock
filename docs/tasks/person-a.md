# Person A — Policy Core & Data Model

Branch: `person-a/policy-core`. Read `docs/tasks/README.md` first for the shared
contract and integration order. Spec: `docs/build-spec.md` §6, §8, §9, §14.1.

## Why this exists

The current mandate check is a boolean (`mandate_rule.allowed INTEGER`) and is only
ever consulted for verbs already hardcoded as forbidden
(`scopelock/agents/institution.py:156`, `if key in mandate.FORBIDDEN_ACTIONS`). A
holder who verbally restricts a normally-safe verb (e.g. "don't let them reschedule")
is silently ignored — the guard never runs for that verb. This branch replaces the
boolean with the spec's three-state disposition and fixes the call site so every
verb, not just the hardcoded-forbidden ones, passes through the policy check.

## Files you own

- `scopelock/core/policy.py` — **new**. `PolicyService` + `PolicyDecision` per the
  frozen interface in `docs/tasks/README.md`.
- `scopelock/core/mandate.py` — becomes a thin compatibility facade: keep
  `ALLOWED_ACTIONS`/`FORBIDDEN_ACTIONS`/`NEEDS_HOLDER_DECISION` (institution.py's
  intent classifier still imports these), but the actual decision logic moves into
  `policy.py`. Delete `guard()`/`GuardResult` once `institution.py` calls
  `PolicyService.evaluate_action()` directly.
- `scopelock/core/db.py` — schema changes only (see README contract): add
  `mandate_rule.disposition`, `policy_event`, `decision_request` tables; migrate
  `kase.state` values to the 9-state list in spec §8.1. Since the DB is disposable
  for the hackathon (spec §8.2), just change `SCHEMA` and have people run
  `db.reset_db()` / delete `scopelock.db` — no migration framework.
- `scopelock/core/consult.py` — replace with (or rename into) the
  `decision_request` lifecycle: `request_holder_decision()` /
  `resolve_holder_decision()`. Don't keep two competing decision ledgers (spec §8.4)
  — pick one and update `household.py`'s consult call sites to match.
- `scopelock/agents/institution.py` — fix `on_action_request` (line ~146) to call
  `PolicyService.evaluate_action(case_id, key, request, source="institution_agent")`
  for **every** classified verb, not just ones in `FORBIDDEN_ACTIONS`. This is the
  one bug-fix line that matters most for the demo (spec §6.3).
- `tests/test_policy.py` — **new**. Cover spec §14.1's policy bullets:
  - forbidden verb has no executable Guava handler (structural — check
    `institution.DEFINED_TASKS`)
  - every normally-allowed verb still passes through the policy service
  - a per-case restriction blocks a normally-safe verb (the bug this branch fixes)
  - unknown verbs are blocked and audited
  - mandate can't open the institution leg before clear verbal confirmation
  - ambiguous text ("maybe") does not confirm the mandate
  - `decided_by` cannot be set to `"agent"` through any public function
- `tests/test_demo_flow.py` — **new**. Pure simulated state-machine walkthrough
  (spec §9 file list) — drive a case through the 9 states without touching Guava.

## Dependency you need (stub if missing)

`scopelock/core/audit.py` and `scopelock/core/redact.py` are Person C's. If they
don't exist yet on your branch:

```python
# temporary stub in policy.py, delete when person-c/console-audit merges
def _record_event_stub(*a, **kw) -> str:
    return "evt_stub"
```

Same for `redact.redact()` in `db.py` — passthrough `lambda text: text` until real.

## Definition of done for this branch

- [ ] `mandate_rule.disposition` replaces `allowed`, constrained to the three values.
- [ ] `PolicyService.evaluate_action()` is the only path institution.py uses to decide
      whether a verb executes — no direct `mandate.guard()` calls left.
- [ ] A per-case `restrict_action()` on a normally-safe verb actually blocks it end to
      end (this is the regression test that didn't exist before).
- [ ] `decision_request` table exists and `decided_by` is hardcoded `"holder"` inside
      `resolve_holder_decision()`, never accepted as a parameter from the caller.
- [ ] `uv run pytest tests/test_policy.py tests/test_demo_flow.py tests/test_mandate.py -q`
      passes.
