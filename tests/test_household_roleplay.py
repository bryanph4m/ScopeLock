"""Spec 8 + definition-of-done 1-2: intake and mandate confirmation, Spanish-only.
Requires a real GUAVA_API_KEY with credits. Skipped automatically otherwise."""
import os

import pytest

from apoderado.core import db

pytestmark = pytest.mark.skipif(
    os.environ.get("GUAVA_API_KEY", "").startswith("gva-test-placeholder"),
    reason="needs a real GUAVA_API_KEY with credits to run a live roleplay session",
)


@pytest.fixture(autouse=True)
def clean_db():
    db.reset_db()
    yield


def test_intake_completes_in_spanish_only():
    from apoderado.agents import household

    session = household.household.roleplay(
        "Eres una madre que llama porque le negaron un reclamo de seguro medico para una "
        "resonancia magnetica. Habla solo en espanol durante toda la llamada. Tu nombre es "
        "Rosa Martinez y la aseguradora es Valley Health Plan."
    )
    session.evaluate(
        pass_criteria=[
            "The agent spoke only in Spanish throughout the call.",
            "The agent read back a mandate describing what it is and is not authorized to do.",
            "The agent asked for and received her verbal confirmation before ending the call.",
        ],
        fail_criteria=[
            "The agent spoke English to the caller.",
            "The agent gave legal or medical advice.",
        ],
    )


def test_mandate_readback_is_the_verbatim_constant():
    from apoderado.agents import household, scripts

    session = household.household.roleplay(
        "Eres un padre que llama sobre una factura incorrecta de su compania de luz. "
        "Cuando el agente lea la autorizacion, responde claramente que si estas de acuerdo."
    )
    transcript = session.get_transcript()
    assert scripts.MANDATE_READBACK_ES in transcript
