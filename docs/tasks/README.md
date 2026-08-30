# ScopeLock build-out — 3-way split

Source of truth: `docs/build-spec.md` (v0.2). This directory splits the gap between
that spec and the current repo (baseline commit `92ba825`) into three branches that
can be built **in parallel, in separate CLIs, with zero file overlap**.

| Branch | Owner | Scope | Detail |
|---|---|---|---|
| `person-a/policy-core` | Person A | Tri-state policy engine, data model, decision lifecycle | [person-a.md](./person-a.md) |
| `person-b/mcp-server` | Person B | MCP server (tools + resources), dependency wiring | [person-b.md](./person-b.md) |
| `person-c/console-audit` | Person C | Audit + redaction, API contracts, console UI | [person-c.md](./person-c.md) |

Each branch was cut from the same commit and touches a **disjoint file set** — no two
people edit the same file, so there is no merge conflict to resolve by hand. What they
share instead is an **interface contract** (below): exact function signatures and JSON
shapes, taken directly from the spec, so nobody has to wait on anybody else's code to
start.

## How to pick this up

```bash
git fetch origin
git checkout person-a/policy-core      # or person-b/mcp-server, person-c/console-audit
```

Read your file, build against the frozen interface below. If you call into a module
another branch owns and it doesn't exist yet on your branch, add a **stub** matching
the signature exactly (mark it `# STUB — replace with person X's branch at merge`) so
your own code and tests run standalone. Delete the stub at integration time.

## Integration order

1. `person-a/policy-core` merges to `main` first — it owns the data model (`db.py`
   schema) that the other two read from or generate fixtures against.
2. `person-b/mcp-server` and `person-c/console-audit` rebase onto `main` after that,
   swap their stubs for the real imports, and merge.
3. Whoever merges last runs the full spec-driven verification pass: `docs/build-spec.md`
   §14.1 (pure tests) and §14.2 (live Guava tests), then §18 (Definition of Done).

If timeline is tight and A isn't done first, B and C can keep developing against their
stubs — the interface below is frozen and won't change shape, only implementation.

## Frozen interface contract

### From Person A (`scopelock/core/policy.py`, `consult.py`, `db.py`)

```python
# scopelock/core/policy.py
@dataclass
class PolicyDecision:
    decision: str          # "allowed" | "requires_holder" | "forbidden"
    may_execute: bool
    requires_holder: bool
    refusal: str | None
    audit_event_id: str

class PolicyService:
    def create_draft(self, case_id: str, overrides: dict[str, str] | None = None) -> None: ...
    def evaluate_action(self, case_id: str, verb: str, trigger: str, source: str) -> PolicyDecision: ...
    def restrict_action(self, case_id: str, verb: str) -> None: ...
    def get_mandate(self, case_id: str) -> list[dict]: ...   # verb, disposition, confirmed_by_holder, confirmed_utterance
    def confirm_mandate(self, case_id: str, utterance: str) -> None: ...

# scopelock/core/consult.py (decision_request lifecycle)
def request_holder_decision(case_id: str, verb: str, question_en: str, question_es: str) -> str: ...  # -> decision_request.id
def resolve_holder_decision(decision_id: str, answer_es: str, answer_en: str, latency_ms: int) -> None: ...  # decided_by is always "holder", not caller-settable

# scopelock/core/db.py — new/changed schema
# mandate_rule.disposition TEXT CHECK(disposition IN ('allowed','requires_holder','forbidden'))
# kase.state TEXT IN (intake|mandate_draft|mandated|awaiting_institution|connecting_holder|
#                      representing|consulting_holder|closing|closed|interrupted)
# policy_event(id, case_id, verb, disposition, source, trigger_redacted, result, created_at)
# decision_request(id, case_id, verb, question_en, question_es, answer_es, answer_en,
#                   status, decided_by, latency_ms, created_at, resolved_at)
```

### From Person C (`scopelock/core/audit.py`, `redact.py`)

```python
# scopelock/core/audit.py
def record_event(case_id: str, verb: str, disposition: str, source: str,
                  trigger_redacted: str | None, result: str) -> str: ...  # -> policy_event.id
def get_audit_report(case_id: str) -> list[dict]: ...  # chronological, redacted

# scopelock/core/redact.py
def redact(text: str) -> str: ...  # masks SSN-like (\d{3}-\d{2}-\d{4} and spoken variants) and
                                    # member/account-ID-shaped substrings before persistence/display
```

Person A's `policy.py.evaluate_action()` calls `audit.record_event()` to fill
`audit_event_id`, and `db.py` should call `redact.redact()` before persisting
transcript/consult text — that's the one real cross-branch call. Stub both as
one-line passthroughs (`record_event` returns `"evt_stub"`, `redact` returns the input
unchanged) until Person C's branch lands.

## What NOT to touch

Don't add abstractions the spec doesn't ask for (no auth, no multi-tenancy, no new
frontend framework — see spec §3.3 non-goals). Reset `scopelock.db` instead of writing
a migration framework (spec §8.2) — the database is disposable for the hackathon.
