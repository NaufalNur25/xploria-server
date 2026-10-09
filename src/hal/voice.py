"""Thread-safe buffer for speech-to-text commands sent by the Xploria app."""

import re
import threading
from datetime import datetime, timezone


_LOCK = threading.RLock()
_TEXT = ""
_TOKENS = ()
_REQUEST_ID = None
_UPDATED_AT = None

_NEGATIONS = {"jangan", "tidak", "tak", "bukan", "gak", "nggak", "enggak"}
_PREFIXES = ("meng", "men", "mem", "me", "di", "ter", "ber")
_SUFFIXES = ("nya", "kan", "lah", "i")


def normalize(value):
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _variants(token):
    variants = {token}
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            variants.add(token[:-len(suffix)])
    for current in tuple(variants):
        for prefix in _PREFIXES:
            if current.startswith(prefix) and len(current) > len(prefix) + 2:
                variants.add(current[len(prefix):])
    return variants


def _matches(spoken_token, keyword):
    if spoken_token == keyword:
        return True
    return keyword in _variants(spoken_token)


def set_voice_text(text, request_id=None):
    global _TEXT, _TOKENS, _REQUEST_ID, _UPDATED_AT
    normalized = normalize(text)
    with _LOCK:
        _TEXT = normalized
        _TOKENS = tuple(normalized.split())
        _REQUEST_ID = request_id
        _UPDATED_AT = datetime.now(timezone.utc).isoformat()
    return normalized


def get_voice_text():
    with _LOCK:
        return _TEXT


def contains_all(*keywords, auto_clear=True):
    required = []
    for keyword in keywords:
        required.extend(normalize(keyword).split())
    if not required:
        return False

    with _LOCK:
        tokens = _TOKENS
    if not tokens or any(token in _NEGATIONS for token in tokens):
        return False

    matched = all(
        any(_matches(spoken_token, keyword) for spoken_token in tokens)
        for keyword in required
    )

    if matched and auto_clear:
        clear()

    return matched



def clear():
    global _TEXT, _TOKENS, _REQUEST_ID, _UPDATED_AT
    with _LOCK:
        _TEXT = ""
        _TOKENS = ()
        _REQUEST_ID = None
        _UPDATED_AT = None


def snapshot():
    with _LOCK:
        return {
            "text": _TEXT,
            "request_id": _REQUEST_ID,
            "updated_at": _UPDATED_AT,
        }
