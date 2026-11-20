"""Types and chunking for conversation search (spec, "Chunks").

A reader turns a source into `SessionDoc`s of `Exchange`s (a typed user turn plus the assistant text after it).
`chunks_of` cuts each exchange into the `Chunk`s that are indexed, ranked and returned.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Sequence

MAX_USER_CHARS, CHUNK_CHARS, LEAD_CHARS = 4000, 4000, 300  # chunk and lead frozen on the dev split (results/search-gate/2026-11-tune)

_WORD = re.compile(r"\w+")


@dataclass(frozen=True)
class Exchange:
    turn_id: str                 # the user record's / human message's uuid
    at: str                      # ISO-8601 UTC time of the typed turn
    user_text: str               # already cut to MAX_USER_CHARS by the reader
    assistant_text: str          # assistant text blocks joined with "\n\n"
    tools: tuple[str, ...] = ()  # tool names only


@dataclass(frozen=True)
class SessionDoc:
    surface: str                 # "code" | "desktop" | "web" | "bench"
    native_id: str
    title: str                   # "" when the reader found none
    project: str | None
    url: str | None
    started_at: str
    updated_at: str
    exchanges: tuple[Exchange, ...]
    source_path: str | None = None

    @property
    def session_key(self) -> str:
        return f"{self.surface}:{self.native_id}"


@dataclass(frozen=True)
class Chunk:
    chunk_key: str               # f"{session_key}#{turn_id}#{part}"
    session_key: str
    turn_id: str
    part: int
    at: str
    user_text: str
    assistant_text: str
    lead: str
    tools: tuple[str, ...]


def _pieces(text: str, limit: int) -> list[str]:
    """Cut `text` into pieces of at most `limit` characters: at the last paragraph break before the limit, else
    the last space, else hard. The whitespace at a cut is dropped; whitespace-only pieces are skipped."""
    out: list[str] = []
    rest = text
    while rest:
        if len(rest) <= limit:
            piece, rest = rest, ""
        else:
            cut = rest.rfind("\n\n", 0, limit + 1)
            if cut > 0:
                piece, rest = rest[:cut], rest[cut + 2:]
            else:
                cut = rest.rfind(" ", 0, limit + 1)
                if cut > 0:
                    piece, rest = rest[:cut], rest[cut + 1:]
                else:
                    piece, rest = rest[:limit], rest[limit:]
        if piece.strip():
            out.append(piece)
    return out


def chunks_of(session: SessionDoc, chunk_chars: int = CHUNK_CHARS, lead_chars: int = LEAD_CHARS) -> list[Chunk]:
    out: list[Chunk] = []
    key = session.session_key
    for ex in session.exchanges:
        if not ex.user_text and not ex.assistant_text:
            continue
        if len(ex.user_text) + len(ex.assistant_text) <= chunk_chars:
            parts = [(ex.user_text, ex.assistant_text, "")]
        else:
            lead = ex.user_text[:lead_chars]
            parts = [(p, "", "") for p in _pieces(ex.user_text, chunk_chars)]
            parts += [("", p, lead) for p in _pieces(ex.assistant_text, chunk_chars)]
        for i, (u, a, lead) in enumerate(parts):
            out.append(Chunk(f"{key}#{ex.turn_id}#{i}", key, ex.turn_id, i, ex.at, u, a, lead, ex.tools))
    return out


def index_text(chunk: Chunk, title: str) -> str:
    """The text that is tokenized for BM25: title, lead, user text, assistant text, joined by newlines."""
    return "\n".join((title, chunk.lead, chunk.user_text, chunk.assistant_text))


def words(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


def digest(salt: str, ws: Sequence[str]) -> str:
    # surrogatepass: a lone surrogate in text from any reader must not raise (it is the same bytes for valid text)
    return hashlib.sha256((salt + "\x00" + " ".join(ws)).encode("utf-8", "surrogatepass")).hexdigest()
