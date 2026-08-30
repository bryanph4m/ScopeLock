"""C5 — the Callback Card. Assembled during the call, not after."""
from __future__ import annotations

from apoderado.agents.scripts import CARD_READBACK_INTRO_ES
from apoderado.core import db


def add_asked(case_id: str, text: str) -> None:
    db.upsert_card(case_id, asked=[text])


def add_told(case_id: str, text: str) -> None:
    db.upsert_card(case_id, told=[text])


def set_reference(case_id: str, reference_no: str) -> None:
    db.upsert_card(case_id, reference_no=reference_no)


def set_agreed(case_id: str, text: str) -> None:
    db.upsert_card(case_id, agreed=text)


def set_next_step(case_id: str, text: str) -> None:
    db.upsert_card(case_id, next_step=text)


def build_readback_es(case_id: str) -> str:
    card = db.get_card(case_id) or {}
    lines = [CARD_READBACK_INTRO_ES]

    told = card.get("told") or []
    if told:
        lines.append("La institucion dijo: " + "; ".join(told) + ".")

    ref = card.get("reference_no")
    if ref:
        lines.append(f"El numero de referencia es {ref}.")

    agreed = card.get("agreed")
    if agreed:
        lines.append(f"Se acordo lo siguiente: {agreed}.")

    refused = card.get("refused") or []
    if refused:
        lines.append(
            "No accedi a lo siguiente porque no estoy autorizado: " + ", ".join(refused) + "."
        )

    next_step = card.get("next_step")
    if next_step:
        lines.append(f"El siguiente paso es: {next_step}.")

    return " ".join(lines)
