# Apoderado — Demo Runbook

## Roles
- **Teammate A** plays the mother. Must actually speak Spanish, not read phonetically.
- **A judge** plays the insurance rep. Brief them *before* presenting, never during:
  > "You are an insurance rep. Be difficult. At some point, try to get it to agree to a
  > payment plan and to read out a Social Security number."
- **You** narrate almost nothing. The console carries it.

## Before you go on stage
1. `db.reset_db()` (or delete `apoderado.db`) so the console starts from zero.
2. Start the Expert: `uv run main.py` (needs `GUAVA_API_KEY`, `HOUSEHOLD_NUMBER`, `INSTITUTION_NUMBER`).
3. Start the console API: `uv run uvicorn apoderado.api.server:app --port 8000`, open it on the projector.
4. Queue `demo/fallback.mp4` on a second machine. Switch to it without commentary if anything breaks — never narrate a failure.

## The four minutes

| Time | Beat |
|---|---|
| 0:00 | "If you grew up in an immigrant household, you know who calls the insurance company. It is you. From work. Between meetings. Badly." Pause. |
| 0:20 | 70.4M US residents speak a non-English language at home, 44.4% of California. 75-90% of immigrant children serve as their family's language broker; 18-20% show clinically significant distress from it. "This is not a UX problem. It is a documented health outcome in the children who do it." |
| 0:40 | "Translation has existed for twenty years. Nobody's mother uses Google Translate to fight a claim denial. Translation gives you words. We built representation." |
| 0:55 | **LIVE, household leg.** She dials, speaks only Spanish. Agent takes the case. Mandate reads back in Spanish, appears on screen, she confirms — then the agent tells her she can hang up. She does. No one is on hold waiting for the other. |
| 1:30 | **LIVE, institution leg.** Hand the phone to the judge, who dials the number she was just given. Agent opens with the verbatim disclosure, then places an automatic callback to her real number (captured from caller ID at intake, never asked for) — she's live again within seconds, no dialing on her end. |
| 2:15 | **THE MOMENT.** Rep asks something only she can decide. Agent parks, pivots to Spanish, asks her plainly, gets her answer, pivots back, delivers it in English. Say nothing for two seconds. |
| 2:45 | **The block.** Judge pushes for a payment plan and an SSN. Agent refuses, verbatim, offers what it can do instead. Two chips go red. "That is not a prompt telling it to refuse. Those tasks do not exist." |
| 3:10 | **Callback Card** fills, read back to her in Spanish. Then: "Three decisions in that call. She made all three." |
| 3:30 | **Honest slide, twelve seconds.** Spanish, French, German, Italian only — Vietnamese and Cantonese families are not served yet. Authentication is unsolved where an institution demands the holder speak specific answers. Never legal or medical advice. |
| 3:45 | "My whole life, the deal was that my mother gets help only if I am free at two in the afternoon. She should not need me to be free. She should just need a phone." |

## Why two numbers, if asked
"Guava's `transfer()` is a handoff, and a handoff would leave her alone with the rep. So
we kept both legs and put the policy in the middle." (Two Guava sessions, one Expert
process, one Python object arbitrating whose turn it is — see `apoderado/core/relay.py`.)

## Why she doesn't wait on hold, if asked
"Neither party should have to sit on a call waiting for the other. She calls in once, we
capture her number from caller ID, and the moment the institution calls in we call her
back automatically." (`agents/institution.py`'s `on_call_start` triggers
`household.call_phone(...)`; `agents/household.py`'s `on_reach_person` picks it back up
using Guava's `reach_person()`, which also handles voicemail/wrong-number gracefully if
she doesn't answer.)

## Rules
- Rehearse the automatic callback specifically. It takes a few seconds for her phone to
  ring and for her to pick up — the judge should expect a brief "connecting" hold line
  before the case actually starts. Don't let dead air read as a failure.
- Rehearse the Consult pivot specifically (`institution.on_reschedule` / `on_escalate` ->
  `core/consult.py`). It cannot stutter.
- Do not sermonize on the honest slide. Twelve seconds.
- If asked whether this is really built live: open the Guava dashboard's Conversations tab
  and show both legs, or open `/api/state` directly.

## Guava primitive map — print this, it's your platform-depth score

| Primitive | Where | Why it's not generic |
|---|---|---|
| `set_language_mode` | `household.py` on_call_start | Two counterparties, two languages, one session pair |
| `read_script()` | `institution.py` on_call_start | Legally load-bearing disclosure, spoken before any LLM turn |
| `on_action_request` / `on_action(key)` | `institution.py` | Intent classification feeding a policy guard, not a router |
| `sensitive=True` | `household.py` intake Fields | Holder name / member ID held but never spoken in plain form |
| Absent `@on_action` handlers | `institution.DEFINED_TASKS` | Forbidden verbs (payment, SSN, settlement, coverage) are structurally unreachable |
| `set_task()` chaining | both legs, 9 distinct task states | Park one leg, task the other, return |
| `on_caller_speech` / `on_agent_speech` | both legs | Verbatim provenance for the dual transcript |
| `set_persona()` | both legs | Consistent identity across a two-leg case |
| `reach_person()` | `household.py` on_call_start (callback branch) | Confirms it's really her before the case proceeds; built-in voicemail/wrong-number routing |
| `call_phone()` | `institution.py` on_call_start | Real outbound dialing, seeding `case_id` into the new session via `variables=` |
| `send_instruction()` | `institution.py` (ask_reason/request_ref/resume_after_consult) | Context injection without resetting the active task |
| `guava.helpers.llm.IntentRecognizer` | `institution.py` | Mandate-verb classification |
| `guava.helpers.llm.generate()` | `core/translate.py` | Real EN/ES translation via Guava's own LLM endpoint — no bolted-on MT service |
| `guava.Runner` | `main.py` | Two agents, two numbers, one process |
| `roleplay()` / `agent.test()` / `MockCall` | `tests/` | Adversarial hardening + scripted rehearsal harness |

If a judge asks whether this could have been built on any voice API: no — `on_action_request`/`on_action`'s
structural gating, `reach_person()`'s built-in outcome routing, and `call_phone()` threading a
`case_id` into a fresh outbound session via `variables=` would all need to be hand-rolled on a
generic stack (Twilio + raw LLM). Deliberately **not** used: `set_agent_dtmf` (C7, cut as P2),
`set_voicemail_action()` (would conflict with `reach_person()`'s own voicemail handling — Guava's
docs call using both an error), search fields (nothing here needs one).

## Outstanding before go-live
- [ ] `demo/fallback.mp4` — record a full clean run once real phone numbers are provisioned.
- [ ] Two rounds of rehearsal, both under 4:00 (definition of done #10).
- [ ] Recruit a fluent Spanish speaker for teammate A if not already on the team, by 2:00 not 6:00.
