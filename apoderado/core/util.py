"""One decorator: a dead institution leg must not kill the household leg, or vice versa."""
from __future__ import annotations

import functools
import logging

logger = logging.getLogger("apoderado")


def safe(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.exception("handler %s raised", fn.__name__)
            return None
    return wrapper
