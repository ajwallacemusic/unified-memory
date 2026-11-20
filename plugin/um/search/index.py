"""The conversation-search index (spec, "Index" and "Ranking"): one SQLite file with BM25 postings.

Scores come from stored postings with `um.search.bm25.score`, so they equal `BM25(docs).scores(query)` over the
same chunk texts. Writes skip tombstoned chunk keys and chunks whose text contains an erased value
(`erasematch.py`).
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from um.search.bm25 import score as bm25_score
from um.search.bm25 import tokenize
from um.search.erasematch import erased_hit
from um.search.model import (CHUNK_CHARS, LEAD_CHARS, Chunk, Exchange, SessionDoc, chunks_of, digest, index_text,
                             words)

SCHEMA_VERSION = 1
DEFAULT_PATH = "~/.local/share/unified-memory/search.sqlite"
SNIPPET_USER_CHARS = 200

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(
  session_key TEXT PRIMARY KEY, surface TEXT NOT NULL, native_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
  project TEXT, url TEXT, started_at TEXT, updated_at TEXT, n_turns INTEGER NOT NULL DEFAULT 0,
  source_path TEXT, source_gone INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS chunks(
  chunk_id INTEGER PRIMARY KEY, chunk_key TEXT NOT NULL UNIQUE, session_key TEXT NOT NULL, turn_id TEXT NOT NULL,
  part INTEGER NOT NULL, at TEXT, user_text TEXT NOT NULL, assistant_text TEXT NOT NULL, lead TEXT NOT NULL DEFAULT '',
  tools TEXT NOT NULL DEFAULT '[]', n_tokens INTEGER NOT NULL, text_sha TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS chunks_session ON chunks(session_key);
CREATE TABLE IF NOT EXISTS postings(
  term TEXT NOT NULL, chunk_id INTEGER NOT NULL, tf INTEGER NOT NULL, PRIMARY KEY(term, chunk_id)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS postings_chunk ON postings(chunk_id);
CREATE TABLE IF NOT EXISTS cursors(
  source_path TEXT PRIMARY KEY, surface TEXT, session_key TEXT, size INTEGER, mtime REAL, offset INTEGER);
CREATE TABLE IF NOT EXISTS tombstones(chunk_key TEXT PRIMARY KEY, erased_at TEXT);
CREATE TABLE IF NOT EXISTS erased(n_tokens INTEGER, digest TEXT, erased_at TEXT, PRIMARY KEY(n_tokens, digest));
CREATE TABLE IF NOT EXISTS erased_text(n_bytes INTEGER, digest TEXT, erased_at TEXT, PRIMARY KEY(n_bytes, digest));
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


@dataclass(frozen=True)
class Hit:
    chunk_key: str
    session_key: str
    surface: str
    native_id: str
    title: str
    project: str | None
    url: str | None
    at: str
    user_text: str
    assistant_text: str
    score: float


@dataclass(frozen=True)
class SessionRow:
    session_key: str
    surface: str
    native_id: str
    title: str
    project: str | None
    url: str | None
    started_at: str
    updated_at: str
    n_turns: int
    first_user: str
    last_user: str


@dataclass(frozen=True)
class Cursor:
    source_path: str
    surface: str
    session_key: str
    size: int
    mtime: float
    offset: int


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _before_bound(before: str) -> str:
    """A bare date `before` is inclusive of that day: compare against the start of the next day."""
    if len(before) == 10:
        try:
            return (date.fromisoformat(before) + timedelta(days=1)).isoformat()
        except ValueError:
            pass
    return before


class Index:
    def __init__(self, path: Path) -> None:
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        if not path.exists():
            os.close(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600))
        os.chmod(path, 0o600)
        self.path = path
        self._db = sqlite3.connect(str(path))
        self._db.executescript(_SCHEMA)
        if self.get_meta("salt") is None:
            self.set_meta("salt", secrets.token_hex(16))
            self.set_meta("schema_version", str(SCHEMA_VERSION))
            self.set_meta("chunk_chars", str(CHUNK_CHARS))
            self.set_meta("lead_chars", str(LEAD_CHARS))
        else:
            try:
                stored = int(self.get_meta("schema_version") or SCHEMA_VERSION)
            except ValueError:
                stored = SCHEMA_VERSION
            if stored > SCHEMA_VERSION:
                self._db.close()
                raise ValueError(f"search index {path} has schema version {stored}, newer than this code's "
                                 f"{SCHEMA_VERSION}; update unified-memory before using it")
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    # --- meta ---------------------------------------------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        r = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return r[0] if r else None

    def set_meta(self, key: str, value: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))
        self._db.commit()

    # --- chunk parameters ---------------------------------------------------------------------------------------

    def stored_chunk_params(self) -> tuple[int, int] | None:
        """(chunk_chars, lead_chars) the stored chunks were cut with; None for an index that never recorded them."""
        try:
            return int(self.get_meta("chunk_chars") or ""), int(self.get_meta("lead_chars") or "")
        except ValueError:
            return None

    def chunk_params_mismatch(self) -> dict | None:
        """None when the stored chunks were cut with the current `CHUNK_CHARS`/`LEAD_CHARS`, else
        {"stored": (chunk, lead) or None, "current": (chunk, lead)}."""
        stored, current = self.stored_chunk_params(), (CHUNK_CHARS, LEAD_CHARS)
        return None if stored == current else {"stored": stored, "current": current}

    def rechunk(self, chunk_chars: int = CHUNK_CHARS, lead_chars: int = LEAD_CHARS) -> dict:
        """Re-cut every stored exchange with these parameters, in place, from the text the index already holds, so a
        session whose source file is gone is kept. Each turn is reassembled from its chunks (user pieces, then
        assistant pieces, joined by a blank line). A turn with any tombstoned part is left exactly as it is: its
        text is incomplete and new part numbers could land on the tombstoned key. Tombstones and erased sequences
        are never touched, and the erased check still applies to every chunk written."""
        tomb_turns = set()
        for (k,) in self._db.execute("SELECT chunk_key FROM tombstones"):
            bits = k.rsplit("#", 2)
            if len(bits) == 3:
                tomb_turns.add((bits[0], bits[1]))
        salt = self.get_meta("salt") or ""
        erased: dict[int, set[str]] = {}
        for n, d in self._db.execute("SELECT n_bytes, digest FROM erased_text"):
            erased.setdefault(n, set()).add(d)
        sessions = self._db.execute("SELECT session_key, surface, native_id, title FROM sessions").fetchall()
        touched, turns, skipped = 0, 0, 0
        for sk, surface, native_id, title in sessions:
            by_turn: dict[str, list] = {}
            for row in self._db.execute(
                    "SELECT chunk_id, turn_id, part, at, user_text, assistant_text, tools, text_sha FROM chunks"
                    " WHERE session_key = ? ORDER BY chunk_id", (sk,)):
                by_turn.setdefault(row[1], []).append(row)
            changed = False
            for turn_id, rows in by_turn.items():
                if (sk, turn_id) in tomb_turns:
                    skipped += 1
                    continue
                rows.sort(key=lambda r: r[2])
                ex = Exchange(turn_id, rows[0][3] or "", "\n\n".join(r[4] for r in rows if r[4]),
                              "\n\n".join(r[5] for r in rows if r[5]), tuple(json.loads(rows[0][6] or "[]")))
                doc = SessionDoc(surface, native_id, title, None, None, "", "", (ex,))
                new = [Chunk(f"{sk}#{turn_id}#{c.part}", sk, turn_id, c.part, c.at, c.user_text, c.assistant_text,
                             c.lead, c.tools) for c in chunks_of(doc, chunk_chars, lead_chars)]
                texts = [index_text(c, title) for c in new]
                if [(r[2], r[7]) for r in rows] == [(c.part, digest("", [t])) for c, t in zip(new, texts)]:
                    continue
                self._drop_chunk_ids([r[0] for r in rows])
                for c, text in zip(new, texts):
                    if erased_hit(text, erased, salt):
                        continue
                    toks = tokenize(text)
                    cur = self._db.execute(
                        "INSERT INTO chunks(chunk_key, session_key, turn_id, part, at, user_text, assistant_text,"
                        " lead, tools, n_tokens, text_sha) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (c.chunk_key, sk, turn_id, c.part, c.at, c.user_text, c.assistant_text, c.lead,
                         json.dumps(list(c.tools)), len(toks), digest("", [text])))
                    self._db.executemany("INSERT INTO postings(term, chunk_id, tf) VALUES (?,?,?)",
                                         [(t, cur.lastrowid, n) for t, n in Counter(toks).items()])
                turns += 1
                changed = True
            if changed:
                touched += 1
                self._refresh_session(sk)
        before = self.stored_chunk_params()
        self._db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('chunk_chars', ?)", (str(chunk_chars),))
        self._db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('lead_chars', ?)", (str(lead_chars),))
        self._db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('rechunked_at', ?)", (_now_iso(),))
        self._db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('rechunked_from', ?)",
                         ("unrecorded" if before is None else f"{before[0]}/{before[1]}",))
        self._db.commit()
        return {"sessions": touched, "turns": turns, "turns_skipped": skipped, "from": before}

    def ensure_chunk_params(self) -> dict | None:
        """Re-chunk when the stored chunk parameters differ from the current ones; None when nothing was needed."""
        return self.rechunk() if self.chunk_params_mismatch() else None

    # --- writes -------------------------------------------------------------------------------------------------

    def _drop_chunk_ids(self, ids: list[int]) -> None:
        for i in ids:
            self._db.execute("DELETE FROM postings WHERE chunk_id = ?", (i,))
            self._db.execute("DELETE FROM chunks WHERE chunk_id = ?", (i,))

    def _refresh_session(self, session_key: str) -> None:
        n = self._db.execute("SELECT count(DISTINCT turn_id) FROM chunks WHERE session_key = ?",
                             (session_key,)).fetchone()[0]
        if n:
            self._db.execute("UPDATE sessions SET n_turns = ? WHERE session_key = ?", (n, session_key))
        else:
            self._db.execute("DELETE FROM sessions WHERE session_key = ?", (session_key,))

    def upsert_session(self, s: SessionDoc, chunks: list[Chunk], *, replace: bool) -> tuple[int, int]:
        try:
            return self._upsert_session(s, chunks, replace=replace)
        except BaseException:
            self._db.rollback()      # never leave a half-written session or a held write lock behind
            raise

    def _upsert_session(self, s: SessionDoc, chunks: list[Chunk], *, replace: bool) -> tuple[int, int]:
        key = s.session_key
        old = self.session_meta(key)
        title = s.title or (old["title"] if old else "")
        source_path = s.source_path or (old["source_path"] if old else None)
        self._db.execute(
            "INSERT INTO sessions(session_key, surface, native_id, title, project, url, started_at, updated_at,"
            " source_path, source_gone) VALUES (?,?,?,?,?,?,?,?,?,0) ON CONFLICT(session_key) DO UPDATE SET"
            " title=excluded.title, project=excluded.project, url=excluded.url, started_at=excluded.started_at,"
            " updated_at=excluded.updated_at, source_path=excluded.source_path, source_gone=0",
            (key, s.surface, s.native_id, title, s.project, s.url, s.started_at, s.updated_at, source_path))
        salt = self.get_meta("salt") or ""
        erased: dict[int, set[str]] = {}
        for n, d in self._db.execute("SELECT n_bytes, digest FROM erased_text"):
            erased.setdefault(n, set()).add(d)
        tomb = {k for (k,) in self._db.execute(
            "SELECT t.chunk_key FROM tombstones t WHERE t.chunk_key LIKE ? ESCAPE '\\'",
            (key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "#%",))}
        existing = {k: (cid, sha) for cid, k, sha in self._db.execute(
            "SELECT chunk_id, chunk_key, text_sha FROM chunks WHERE session_key = ?", (key,))}
        written, kept = 0, set()
        for c in chunks:
            if c.chunk_key in tomb:
                continue
            text = index_text(c, title)
            sha = digest("", [text])
            prev = existing.get(c.chunk_key)
            if prev and prev[1] == sha:     # already indexed, so it passed every erase since (erase scans all)
                kept.add(c.chunk_key)
                continue
            if erased_hit(text, erased, salt):
                continue
            kept.add(c.chunk_key)
            if prev:
                self._drop_chunk_ids([prev[0]])
            toks = tokenize(text)
            cur = self._db.execute(
                "INSERT INTO chunks(chunk_key, session_key, turn_id, part, at, user_text, assistant_text, lead, tools,"
                " n_tokens, text_sha) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (c.chunk_key, key, c.turn_id, c.part, c.at, c.user_text, c.assistant_text, c.lead,
                 json.dumps(list(c.tools)), len(toks), sha))
            self._db.executemany("INSERT INTO postings(term, chunk_id, tf) VALUES (?,?,?)",
                                 [(t, cur.lastrowid, n) for t, n in Counter(toks).items()])
            written += 1
        removed = 0
        if replace:
            gone = [cid for k, (cid, _) in existing.items() if k not in kept]
            self._drop_chunk_ids(gone)
            removed = len(gone)
        self._refresh_session(key)
        self._db.commit()
        return written, removed

    def delete_chunks(self, chunk_keys: list[str], *, tombstone: bool) -> int:
        n, sessions = 0, set()
        now = _now_iso()
        for k in chunk_keys:
            r = self._db.execute("SELECT chunk_id, session_key FROM chunks WHERE chunk_key = ?", (k,)).fetchone()
            if r:
                self._drop_chunk_ids([r[0]])
                sessions.add(r[1])
                n += 1
            if tombstone:
                self._db.execute("INSERT OR REPLACE INTO tombstones(chunk_key, erased_at) VALUES (?, ?)", (k, now))
        for sk in sessions:
            self._refresh_session(sk)
        self._db.commit()
        return n

    def delete_session(self, session_key: str, *, tombstone: bool = False) -> int:
        keys = [k for (k,) in self._db.execute("SELECT chunk_key FROM chunks WHERE session_key = ?", (session_key,))]
        n = self.delete_chunks(keys, tombstone=tombstone)
        self._db.execute("DELETE FROM sessions WHERE session_key = ?", (session_key,))
        self._db.commit()
        return n

    def add_erased(self, n_bytes: int, digest_hex: str) -> None:
        """Record an erased value's `erasematch.value_digest`; every later write drops a chunk containing it."""
        self._db.execute("INSERT OR IGNORE INTO erased_text(n_bytes, digest, erased_at) VALUES (?,?,?)",
                         (n_bytes, digest_hex, _now_iso()))
        self._db.commit()

    def forget_all(self) -> int:
        """Empty every content table and the content meta, then VACUUM, in place: the file, its salt, the erase
        guard and the tombstones stay, so an erased value cannot come back when the index is rebuilt, and a
        running server holding this file sees it empty. Returns the number of chunks removed."""
        n = self._db.execute("SELECT count(*) FROM chunks").fetchone()[0]
        for table in ("postings", "chunks", "sessions", "cursors"):
            self._db.execute(f"DELETE FROM {table}")
        self._db.execute("DELETE FROM meta WHERE key NOT IN ('salt', 'schema_version')")
        self.vacuum()
        return n

    # --- reads --------------------------------------------------------------------------------------------------

    def session_meta(self, session_key: str) -> dict | None:
        r = self._db.execute("SELECT updated_at, n_turns, title, source_path FROM sessions WHERE session_key = ?",
                             (session_key,)).fetchone()
        return None if r is None else {"updated_at": r[0], "n_turns": r[1], "title": r[2], "source_path": r[3]}

    def session_keys(self, surface: str) -> set[str]:
        return {k for (k,) in self._db.execute("SELECT session_key FROM sessions WHERE surface = ?", (surface,))}

    def iter_chunks(self) -> Iterator[tuple[str, str]]:
        rows = self._db.execute(
            "SELECT c.chunk_key, COALESCE(s.title, ''), c.lead, c.user_text, c.assistant_text"
            " FROM chunks c LEFT JOIN sessions s ON s.session_key = c.session_key ORDER BY c.chunk_id").fetchall()
        for k, title, lead, u, a in rows:
            yield k, "\n".join((title, lead, u, a))

    def _filters(self, *, time_col: str, after, before, surfaces, project, within=None, exclude=None):
        where, args = [], []
        if after:
            where.append(f"{time_col} >= ?"); args.append(after)
        if before:
            where.append(f"{time_col} < ?"); args.append(_before_bound(before))
        if surfaces:
            where.append(f"s.surface IN ({','.join('?' * len(surfaces))})"); args.extend(surfaces)
        if project:
            where.append("s.project IS NOT NULL AND instr(lower(s.project), lower(?)) > 0"); args.append(project)
        if within:
            where.append("(s.native_id = ? OR s.session_key = ?)"); args += [within, within]
        if exclude:
            where.append("NOT (s.native_id = ? OR s.session_key = ?)"); args += [exclude, exclude]
        return where, args

    def search(self, query: str, *, limit: int = 5, per_session: int | None = 2, after: str | None = None,
               before: str | None = None, sort: str = "relevance", surfaces: tuple[str, ...] | None = None,
               project: str | None = None, within: str | None = None, exclude: str | None = None,
               half_life_days: float | None = None, now: str | None = None) -> list[Hit]:
        q = tokenize(query)
        if not q or limit <= 0:
            return []
        terms = sorted(set(q))
        qcount = Counter(q)   # BM25.scores sums a repeated query term once per occurrence
        n_docs, total = self._db.execute("SELECT count(*), COALESCE(sum(n_tokens), 0) FROM chunks").fetchone()
        if not n_docs:
            return []
        avgdl = total / n_docs or 1.0
        marks = ",".join("?" * len(terms))
        df = dict(self._db.execute(f"SELECT term, count(*) FROM postings WHERE term IN ({marks}) GROUP BY term", terms))
        where, args = self._filters(time_col="c.at", after=after, before=before, surfaces=surfaces, project=project,
                                    within=within, exclude=exclude)
        sql = (f"SELECT p.chunk_id, p.term, p.tf, c.n_tokens, c.at, c.session_key FROM postings p"
               f" JOIN chunks c ON c.chunk_id = p.chunk_id JOIN sessions s ON s.session_key = c.session_key"
               f" WHERE p.term IN ({marks})" + "".join(f" AND {w}" for w in where))
        scores: dict[int, float] = {}
        ats: dict[int, str] = {}
        sess: dict[int, str] = {}
        for cid, term, tf, dl, at, sk in self._db.execute(sql, terms + args):
            scores[cid] = scores.get(cid, 0.0) + qcount[term] * bm25_score(tf, df[term], n_docs, dl, avgdl)
            ats[cid] = at or ""
            sess[cid] = sk
        if half_life_days:
            ref = _parse_time(now) or datetime.now(timezone.utc)
            for cid in scores:
                t = _parse_time(ats[cid])
                age = max(0.0, (ref - t).total_seconds() / 86400) if t else 0.0
                scores[cid] *= 0.5 + 0.5 * 0.5 ** (age / half_life_days)
        # The per-session cap is applied while walking the whole ranked list, before the candidate pool is cut, so
        # one session with many matching chunks cannot crowd every other session out of the pool.
        per: Counter = Counter()
        ranked = []
        for cid in sorted((cid for cid, sc in scores.items() if sc > 0), key=lambda cid: (-scores[cid], ats[cid], cid)):
            if per_session is not None:
                if per[sess[cid]] >= per_session:
                    continue
                per[sess[cid]] += 1
            ranked.append(cid)
            if len(ranked) >= 5 * limit:
                break
        if sort == "newest":
            ranked.sort(key=lambda cid: ats[cid], reverse=True)
        elif sort == "oldest":
            ranked.sort(key=lambda cid: ats[cid])
        rows = {}
        if ranked:
            rows = {r[0]: r for r in self._db.execute(
                "SELECT c.chunk_id, c.chunk_key, c.session_key, s.surface, s.native_id, s.title, s.project, s.url,"
                " c.at, c.user_text, c.assistant_text FROM chunks c JOIN sessions s ON s.session_key = c.session_key"
                f" WHERE c.chunk_id IN ({','.join('?' * len(ranked))})", ranked)}
        return [Hit(*rows[cid][1:], score=scores[cid]) for cid in ranked[:limit]]

    def recent(self, *, n: int = 5, after: str | None = None, before: str | None = None, order: str = "desc",
               surfaces: tuple[str, ...] | None = None, project: str | None = None) -> list[SessionRow]:
        if n <= 0:
            return []
        where, args = self._filters(time_col="s.updated_at", after=after, before=before, surfaces=surfaces,
                                    project=project)
        direction = "ASC" if order == "asc" else "DESC"
        sql = ("SELECT s.session_key, s.surface, s.native_id, s.title, s.project, s.url, s.started_at, s.updated_at,"
               " s.n_turns FROM sessions s" + (" WHERE " + " AND ".join(where) if where else "")
               + f" ORDER BY s.updated_at {direction}, s.session_key {direction} LIMIT ?")
        out = []
        for r in self._db.execute(sql, args + [n]).fetchall():
            users = [u for (u,) in self._db.execute(
                "SELECT user_text FROM chunks WHERE session_key = ? AND user_text != '' ORDER BY at, chunk_id",
                (r[0],))]
            first = users[0][:SNIPPET_USER_CHARS] if users else ""
            last = users[-1][:SNIPPET_USER_CHARS] if users else ""
            out.append(SessionRow(*r, first_user=first, last_user=last))
        return out

    # --- cursors and housekeeping -------------------------------------------------------------------------------

    def cursor(self, source_path: str) -> Cursor | None:
        r = self._db.execute("SELECT source_path, surface, session_key, size, mtime, offset FROM cursors"
                             " WHERE source_path = ?", (source_path,)).fetchone()
        return Cursor(*r) if r else None

    def set_cursor(self, c: Cursor) -> None:
        self._db.execute("INSERT OR REPLACE INTO cursors(source_path, surface, session_key, size, mtime, offset)"
                         " VALUES (?,?,?,?,?,?)", (c.source_path, c.surface, c.session_key, c.size, c.mtime, c.offset))
        self._db.commit()

    def mark_gone(self, surface: str, present: set[str]) -> int:
        """Set `source_gone` on this surface's sessions whose source file is not in `present`; returns how many
        were newly marked. Their chunks stay: the index is the durable copy."""
        rows = self._db.execute("SELECT session_key, source_path FROM sessions WHERE surface = ? AND source_gone = 0"
                                " AND source_path IS NOT NULL", (surface,)).fetchall()
        gone = [k for k, p in rows if p not in present]
        self._db.executemany("UPDATE sessions SET source_gone = 1 WHERE session_key = ?", [(k,) for k in gone])
        self._db.commit()
        return len(gone)

    def stats(self) -> dict:
        sessions = dict(self._db.execute("SELECT surface, count(*) FROM sessions GROUP BY surface"))
        chunks = dict(self._db.execute("SELECT s.surface, count(*) FROM chunks c JOIN sessions s"
                                       " ON s.session_key = c.session_key GROUP BY s.surface"))
        gone = self._db.execute("SELECT count(*) FROM sessions WHERE source_gone = 1").fetchone()[0]
        return {"sessions": sessions, "chunks": chunks, "source_gone": gone}

    def vacuum(self) -> None:
        self._db.commit()
        self._db.execute("VACUUM")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def check_index_path(path: Path, profile: Path) -> None:
    """Refuse an index location inside a git work tree, the profile folder, or ~/.claude (spec, "Index")."""
    p = Path(path).expanduser().resolve()
    for root, what in ((Path(profile).expanduser().resolve(), "the profile folder"),
                       ((Path.home() / ".claude").resolve(), "~/.claude")):
        if _inside(p, root):
            raise ValueError(f"search index {p} is inside {what}; choose a path outside it")
    for d in (p.parent, *p.parent.parents):
        if (d / ".git").exists():
            raise ValueError(f"search index {p} is inside the git work tree {d}; choose a path outside it")
