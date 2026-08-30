"""Real-time translation for the live-interpreter model. Uses guava.helpers.llm.generate() —
Guava's own public LLM endpoint — rather than standing up a separate translation service."""
from __future__ import annotations

from guava.helpers.llm import generate

_LANG_NAMES = {"spanish": "Spanish", "english": "English"}


def translate(text: str, target_lang: str) -> str:
    text = text.strip()
    if not text:
        return text
    target_name = _LANG_NAMES.get(target_lang, target_lang)
    prompt = (
        f"Translate the following into natural, conversational {target_name}, as if spoken "
        "aloud on a phone call. Return ONLY the translation — no notes, no quotes, no preamble.\n\n"
        f"Text: {text}"
    )
    return generate(prompt).strip()
