"""Deterministic redaction for sensitive values before storage or display."""
from __future__ import annotations

import re

SSN_REDACTION = "[REDACTED SSN]"
ID_REDACTION = "[REDACTED MEMBER/ACCOUNT ID]"

_DIGIT_WORD = (
    r"(?:zero|oh|one|two|three|four|five|six|seven|eight|nine|"
    r"cero|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve)"
)

# Conventional SSNs, including the common space-separated transcription form.
_FORMATTED_SSN = re.compile(r"(?<!\d)\d{3}[\s-]\d{2}[\s-]\d{4}(?!\d)")
_CONTIGUOUS_SSN = re.compile(r"(?<!\d)\d{9}(?!\d)")

# Voice transcripts often contain either individual digit characters or digit words
# separated by commas and pauses instead of the conventional 3-2-4 punctuation.
_SPOKEN_DIGIT_SSN = re.compile(
    r"(?<!\d)\d(?:[\s,.;:-]+\d){8}(?!\d)", re.IGNORECASE
)
_SPOKEN_WORD_SSN = re.compile(
    rf"(?<!\w){_DIGIT_WORD}(?:[\s,.;:-]+{_DIGIT_WORD}){{8}}(?!\w)",
    re.IGNORECASE,
)

_ID_LABEL = (
    r"(?:"
    r"(?:member|account|acct|subscriber|policy)\s*(?:id(?:entifier)?|number|no\.?|#)"
    r"|(?:id(?:entificador)?|n[uú]mero)\s+de(?:l|\s+la)?\s+"
    r"(?:miembro|cuenta|p[oó]liza)"
    r")"
)
_ID_VALUE = (
    r"(?:"
    r"\d{2,}(?:\s+\d{2,})+"
    r"|(?=[A-Z0-9-]{4,32}(?:\b|$))(?=[A-Z0-9-]*\d)[A-Z0-9]+(?:-[A-Z0-9]+)*"
    r")"
)
_LABELED_ID = re.compile(
    rf"(?P<label>\b{_ID_LABEL})(?P<separator>\s*(?:(?:is|es)\s+|[:=#-]\s*)?)"
    rf"(?P<value>{_ID_VALUE})",
    re.IGNORECASE,
)
_PREFIXED_ID = re.compile(
    r"\b(?=[A-Z0-9_-]{8,36}\b)(?=[A-Z0-9_-]*\d)"
    r"(?:acct|account|member|mbr|subscriber)[_-][A-Z0-9][A-Z0-9_-]{3,31}\b",
    re.IGNORECASE,
)


def _redact_labeled_id(match: re.Match[str]) -> str:
    return f"{match.group('label')}{match.group('separator')}{ID_REDACTION}"


def redact(text: str) -> str:
    """Mask SSN-like and member/account-ID-shaped values in ``text``.

    Callers that persist transcripts or consultation text must call this function
    before handing text to SQLite. API adapters should call it again as defense in
    depth; the operation is idempotent.
    """
    if not isinstance(text, str):
        raise TypeError("redact() requires str")

    redacted = _FORMATTED_SSN.sub(SSN_REDACTION, text)
    redacted = _CONTIGUOUS_SSN.sub(SSN_REDACTION, redacted)
    redacted = _SPOKEN_DIGIT_SSN.sub(SSN_REDACTION, redacted)
    redacted = _SPOKEN_WORD_SSN.sub(SSN_REDACTION, redacted)
    redacted = _LABELED_ID.sub(_redact_labeled_id, redacted)
    return _PREFIXED_ID.sub(ID_REDACTION, redacted)
