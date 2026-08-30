"""SQLite persistence, WAL mode, single file. Pure stdlib, no telephony."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "apoderado.db"

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS kase (
  id            TEXT PRIMARY KEY,
  holder_name   TEXT NOT NULL,
  holder_lang   TEXT NOT NULL,
  holder_phone  TEXT,
  institution   TEXT NOT NULL,
  issue_type    TEXT NOT NULL,
  issue_summary TEXT NOT NULL,
  session_a     TEXT,
  session_b     TEXT,
  state         TEXT NOT NULL,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mandate_rule (
  id        TEXT PRIMARY KEY,
  case_id   TEXT NOT NULL REFERENCES kase(id),
  verb      TEXT NOT NULL,
  allowed   INTEGER NOT NULL,
  confirmed_by_holder INTEGER DEFAULT 0,
  confirmed_utterance TEXT
);

CREATE TABLE IF NOT EXISTS consult (
  id            TEXT PRIMARY KEY,
  case_id       TEXT NOT NULL REFERENCES kase(id),
  question_en   TEXT NOT NULL,
  question_es   TEXT NOT NULL,
  answer_es     TEXT NOT NULL,
  answer_en     TEXT NOT NULL,
  decided_by    TEXT NOT NULL,
  latency_ms    INTEGER,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS violation (
  id         TEXT PRIMARY KEY,
  case_id    TEXT NOT NULL,
  verb       TEXT NOT NULL,
  trigger    TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS utterance (
  id         TEXT PRIMARY KEY,
  case_id    TEXT NOT NULL,
  leg        TEXT NOT NULL,
  speaker    TEXT NOT NULL,
  lang       TEXT NOT NULL,
  text       TEXT NOT NULL,
  call_id    TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS card (
  case_id      TEXT PRIMARY KEY REFERENCES kase(id),
  asked        TEXT NOT NULL,
  told         TEXT NOT NULL,
  reference_no TEXT,
  agreed       TEXT,
  refused      TEXT NOT NULL,
  next_step    TEXT,
  created_at   TEXT NOT NULL
);
"""


def new_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000):013x}{uuid.uuid4().hex[:12]}"


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def connect() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        conn.commit()
        _local.conn = conn
    return conn


def create_case(holder_name: str, holder_lang: str, institution: str,
                 issue_type: str, issue_summary: str, holder_phone: str | None = None) -> str:
    case_id = new_id("cas")
    conn = connect()
    conn.execute(
        "INSERT INTO kase (id, holder_name, holder_lang, holder_phone, institution, issue_type, "
        "issue_summary, session_a, session_b, state, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'intake', ?)",
        (case_id, holder_name, holder_lang, holder_phone, institution, issue_type, issue_summary, now()),
    )
    conn.commit()
    return case_id


def get_case(case_id: str) -> sqlite3.Row | None:
    return connect().execute("SELECT * FROM kase WHERE id = ?", (case_id,)).fetchone()


def get_open_case() -> sqlite3.Row | None:
    """Dumb pairing for the demo: the one case that is mandated/live and has no institution leg yet."""
    return connect().execute(
        "SELECT * FROM kase WHERE state IN ('mandated', 'live') AND session_b IS NULL "
        "ORDER BY created_at DESC LIMIT 1"
    ).fetchone()


def set_case_state(case_id: str, state: str) -> None:
    conn = connect()
    conn.execute("UPDATE kase SET state = ? WHERE id = ?", (state, case_id))
    conn.commit()


def set_case_session(case_id: str, *, session_a: str | None = None, session_b: str | None = None) -> None:
    conn = connect()
    if session_a is not None:
        conn.execute("UPDATE kase SET session_a = ? WHERE id = ?", (session_a, case_id))
    if session_b is not None:
        conn.execute("UPDATE kase SET session_b = ? WHERE id = ?", (session_b, case_id))
    conn.commit()


def create_mandate_rules(case_id: str, rules: dict[str, bool]) -> None:
    conn = connect()
    conn.executemany(
        "INSERT INTO mandate_rule (id, case_id, verb, allowed, confirmed_by_holder, confirmed_utterance) "
        "VALUES (?, ?, ?, ?, 0, NULL)",
        [(new_id("man"), case_id, verb, 1 if allowed else 0) for verb, allowed in rules.items()],
    )
    conn.commit()


def mandate_rules(case_id: str) -> list[sqlite3.Row]:
    return connect().execute(
        "SELECT * FROM mandate_rule WHERE case_id = ? ORDER BY verb", (case_id,)
    ).fetchall()


def mandate_rule(case_id: str, verb: str) -> sqlite3.Row | None:
    return connect().execute(
        "SELECT * FROM mandate_rule WHERE case_id = ? AND verb = ?", (case_id, verb)
    ).fetchone()


def confirm_mandate(case_id: str, utterance: str) -> None:
    """A single verbal confirmation covers the whole mandate — see spec 5.3."""
    conn = connect()
    conn.execute(
        "UPDATE mandate_rule SET confirmed_by_holder = 1, confirmed_utterance = ? WHERE case_id = ?",
        (utterance, case_id),
    )
    conn.commit()


def mandate_confirmed(case_id: str) -> bool:
    rows = mandate_rules(case_id)
    return bool(rows) and all(r["confirmed_by_holder"] for r in rows)


def log_violation(case_id: str, verb: str, trigger: str) -> None:
    conn = connect()
    conn.execute(
        "INSERT INTO violation (id, case_id, verb, trigger, created_at) VALUES (?, ?, ?, ?, ?)",
        (new_id("vio"), case_id, verb, trigger, now()),
    )
    conn.commit()


def violations(case_id: str) -> list[sqlite3.Row]:
    return connect().execute(
        "SELECT * FROM violation WHERE case_id = ? ORDER BY created_at", (case_id,)
    ).fetchall()


def record_consult(case_id: str, question_en: str, question_es: str,
                    answer_es: str, answer_en: str, latency_ms: int | None = None) -> str:
    """decided_by is always 'holder' — there is no parameter for it. See core/consult.py."""
    conn = connect()
    consult_id = new_id("con")
    conn.execute(
        "INSERT INTO consult (id, case_id, question_en, question_es, answer_es, answer_en, "
        "decided_by, latency_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, 'holder', ?, ?)",
        (consult_id, case_id, question_en, question_es, answer_es, answer_en, latency_ms, now()),
    )
    conn.commit()
    return consult_id


def consults(case_id: str) -> list[sqlite3.Row]:
    return connect().execute(
        "SELECT * FROM consult WHERE case_id = ? ORDER BY created_at", (case_id,)
    ).fetchall()


def add_utterance(case_id: str, leg: str, speaker: str, lang: str, text: str, call_id: str,
                   external_id: str | None = None) -> None:
    """external_id dedupes progressive caller-speech updates (same utterance_id, growing text)
    by upserting in place instead of appending a new row per partial transcript."""
    conn = connect()
    row_id = f"utt_{leg}_{external_id}" if external_id else new_id("utt")
    conn.execute(
        "INSERT INTO utterance (id, case_id, leg, speaker, lang, text, call_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET text = excluded.text",
        (row_id, case_id, leg, speaker, lang, text, call_id, now()),
    )
    conn.commit()


def utterances(case_id: str) -> list[sqlite3.Row]:
    return connect().execute(
        "SELECT * FROM utterance WHERE case_id = ? ORDER BY created_at", (case_id,)
    ).fetchall()


def upsert_card(case_id: str, *, asked: list[str] | None = None, told: list[str] | None = None,
                 reference_no: str | None = None, agreed: str | None = None,
                 next_step: str | None = None) -> None:
    conn = connect()
    row = conn.execute("SELECT * FROM card WHERE case_id = ?", (case_id,)).fetchone()
    refused = [v["verb"] for v in violations(case_id)]
    if row is None:
        conn.execute(
            "INSERT INTO card (case_id, asked, told, reference_no, agreed, refused, next_step, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (case_id, json.dumps(asked or []), json.dumps(told or []), reference_no, agreed,
             json.dumps(refused), next_step, now()),
        )
    else:
        merged_asked = json.loads(row["asked"]) + (asked or [])
        merged_told = json.loads(row["told"]) + (told or [])
        conn.execute(
            "UPDATE card SET asked = ?, told = ?, reference_no = COALESCE(?, reference_no), "
            "agreed = COALESCE(?, agreed), refused = ?, next_step = COALESCE(?, next_step) "
            "WHERE case_id = ?",
            (json.dumps(merged_asked), json.dumps(merged_told), reference_no, agreed,
             json.dumps(refused), next_step, case_id),
        )
    conn.commit()


def get_card(case_id: str) -> dict | None:
    row = connect().execute("SELECT * FROM card WHERE case_id = ?", (case_id,)).fetchone()
    if row is None:
        return None
    return {
        "case_id": row["case_id"],
        "asked": json.loads(row["asked"]),
        "told": json.loads(row["told"]),
        "reference_no": row["reference_no"],
        "agreed": row["agreed"],
        "refused": json.loads(row["refused"]),
        "next_step": row["next_step"],
    }


def reset_db() -> None:
    """Test helper: drop and recreate all tables."""
    conn = connect()
    conn.executescript("""
        DROP TABLE IF EXISTS kase;
        DROP TABLE IF EXISTS mandate_rule;
        DROP TABLE IF EXISTS consult;
        DROP TABLE IF EXISTS violation;
        DROP TABLE IF EXISTS utterance;
        DROP TABLE IF EXISTS card;
    """)
    conn.executescript(SCHEMA)
    conn.commit()
