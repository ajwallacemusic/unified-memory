"""How an erased value is matched, shared by erase time (`forget.py`) and the later-ingest guard (`index.py`).

Both use one rule: the value, stripped and lower-cased, is a substring of the lower-cased text, where the text is
also tried with its JSON decoded (`um.erase._decoded`) and with JSON string escapes inside non-JSON text decoded.
Substring matching covers `name_client`, `NameClient` and `Zo\\u00eb` with no special cases.

The guard cannot keep the value, so it keeps a keyed hash (BLAKE2b, keyed with the index's salt) of the value's
UTF-8 bytes and their length n. At ingest it hashes every n-byte window of each normalised form of the chunk text
and drops the chunk when one is in the set: the same substring test, run against digests. UTF-8 is
self-synchronising, so a byte-window match is exactly a character-substring match. A value like `C++` is matched
as the three bytes `c++`, never collapsed to the word `c`.
"""
from __future__ import annotations

import hashlib
import json
import re

from um.erase import _decoded

_ESCAPES = re.compile(r'(?:\\u[0-9a-fA-F]{4})+|\\["\\/]')


def _unescape_one(m: re.Match) -> str:
    try:
        return json.loads('"' + m.group(0) + '"')
    except ValueError:
        return m.group(0)


def normal_forms(text: str) -> list[str]:
    """The lower-cased forms of `text` an erased value is looked for in."""
    forms = [_decoded(text).lower()]
    unescaped = _ESCAPES.sub(_unescape_one, text)
    if unescaped != text:
        forms.append(_decoded(unescaped).lower())
    return forms


def matches(text: str, low: list[str]) -> bool:
    """Whether any of `low` (values already stripped and lower-cased by `um.erase._check`) is in `text`."""
    return any(v in f for f in normal_forms(text) for v in low)


def _key(salt: str) -> bytes:
    return salt.encode("utf-8")[:64]


def value_digest(salt: str, value_low: str) -> tuple[int, str]:
    """(byte length, keyed digest) of a stripped, lower-cased value."""
    b = value_low.encode("utf-8")
    return len(b), hashlib.blake2b(b, key=_key(salt), digest_size=16).hexdigest()


def erased_hit(text: str, erased: dict[int, set[str]], salt: str) -> bool:
    """Whether `text` contains a value whose `value_digest` is in `erased` ({byte length: digests})."""
    if not erased:
        return False
    base = hashlib.blake2b(key=_key(salt), digest_size=16)
    raw = {n: {bytes.fromhex(d) for d in ds} for n, ds in erased.items()}
    for form in normal_forms(text):
        b = memoryview(form.encode("utf-8"))
        for n, digests in raw.items():
            for i in range(len(b) - n + 1):
                h = base.copy()
                h.update(b[i:i + n])
                if h.digest() in digests:
                    return True
    return False
