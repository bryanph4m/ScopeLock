"""Verbatim text. Never LLM-generated, never paraphrased.

Anything a judge, a regulator, or a transcript could quote back at us lives here as a
constant and is delivered through guava.read_script() (call-opening) or guava.Say()
(mid-call) rather than left to the LLM to phrase.
"""

DISCLOSURE_EN = (
    "Hi, I'm an AI assistant calling with the account holder on the line, "
    "and this call is being recorded. She's here and can confirm anything you need."
)

MANDATE_READBACK_ES = (
    "Antes de llamar a la institucion, quiero confirmar lo que estoy autorizado a hacer. "
    "Puedo preguntar por que paso esto, pedir un numero de referencia, pedir la politica por escrito, "
    "pedir hablar con un supervisor, y pedir reprogramar una cita. "
    "No puedo aceptar ningun pago, no puedo aceptar cambios en su cobertura, "
    "no puedo aceptar un acuerdo o arreglo, y no puedo dar su numero de Seguro Social. "
    "Si le preguntan algo que solo usted puede decidir, la voy a consultar antes de responder. "
    "¿Esta de acuerdo con esto?"
)

REFUSAL = {
    "agree_payment": (
        "I'm not authorized to agree to any payment on this call. "
        "I can get a reference number and have her call back about that."
    ),
    "accept_settlement": (
        "I'm not authorized to accept any settlement or agreement on this call. "
        "I can get a reference number and have her call back about that."
    ),
    "change_coverage": (
        "I'm not authorized to change her coverage on this call. "
        "I can get a reference number and have her call back about that."
    ),
    "disclose_ssn": (
        "I'm not authorized to give out the Social Security number. "
        "She's on the other line and can verify her identity another way."
    ),
}

CARD_READBACK_INTRO_ES = "Esto es lo que paso en la llamada:"
