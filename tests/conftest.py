"""guava.Agent() builds an auth object at construction time, before any network call —
so importing scopelock.agents.* for pure-logic checks (DEFINED_TASKS, etc.) needs *a*
value in GUAVA_API_KEY, even though these tests never place a call. Never overrides a
real key the developer has already set."""
import os

os.environ.setdefault("GUAVA_API_KEY", "gva-test-placeholder-not-a-real-key")
