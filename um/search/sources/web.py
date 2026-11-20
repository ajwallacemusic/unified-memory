"""claude.ai export reader (spec, "Sources and what is indexed", "Freshness", "Privacy").

`load_export` accepts a `conversations.json`, a `conversations-NNN.zip`, an unpacked export folder, or a folder
holding the zips. Zips are read in memory; only `conversations.json` members and `manifest-*.json` files are
opened. Every other file in the export (users, projects, memories, attachments) is never read.
"""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from um.search.model import MAX_USER_CHARS, Exchange, SessionDoc

_CONV = "conversations.json"
_PART_KEYS = ("filename", "file_name", "name", "path", "file")
_PART_RE = re.compile(r"conversations-\d+")


@dataclass(frozen=True)
class Export:
    sessions: list[SessionDoc]
    export_date: str        # the manifest's created_at if it has one, else max updated_at over conversations, ISO
    export_id: str          # manifest file name stem, else sha256 of the sorted conversation uuids (first 16 hex)
    complete: bool


def _texts(blocks) -> list[str]:
    out = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str) and b["text"]:
            out.append(b["text"])
    return out


def _message_text(m: dict) -> str:
    content = m.get("content")
    if isinstance(content, list) and content:
        return "\n\n".join(_texts(content))
    text = m.get("text")
    return text if isinstance(text, str) else ""


def _tool_names(m: dict) -> list[str]:
    content = m.get("content")
    if not isinstance(content, list):
        return []
    return [b["name"] for b in content
            if isinstance(b, dict) and b.get("type") == "tool_use" and isinstance(b.get("name"), str)]


def _s(v) -> str:
    return v if isinstance(v, str) else ""


def session_of(conv: dict) -> SessionDoc:
    uuid = _s(conv.get("uuid"))
    msgs = [m for m in (conv.get("chat_messages") or []) if isinstance(m, dict)]
    humans = [m for m in msgs if m.get("sender") == "human" and isinstance(m.get("uuid"), str)]
    humans.sort(key=lambda m: _s(m.get("created_at")))   # stable: export order breaks ties
    children: dict[str, list[dict]] = {}
    for m in msgs:
        if m.get("sender") == "assistant" and isinstance(m.get("parent_message_uuid"), str):
            children.setdefault(m["parent_message_uuid"], []).append(m)
    exchanges = []
    for h in humans:
        replies = sorted(children.get(h["uuid"], []), key=lambda m: _s(m.get("created_at")))
        texts = [x for x in (_message_text(a) for a in replies) if x]
        tools: list[str] = []
        for a in replies:
            for name in _tool_names(a):
                if name not in tools:
                    tools.append(name)
        exchanges.append(Exchange(turn_id=h["uuid"], at=_s(h.get("created_at")),
                                  user_text=_message_text(h)[:MAX_USER_CHARS],
                                  assistant_text="\n\n".join(texts), tools=tuple(tools)))
    return SessionDoc(surface="web", native_id=uuid, title=_s(conv.get("name")), project=None,
                      url=f"https://claude.ai/chat/{uuid}", started_at=_s(conv.get("created_at")),
                      updated_at=_s(conv.get("updated_at")), exchanges=tuple(exchanges))


def _part_id(name: str) -> str:
    """`conversations-000.zip` and `conversations-000/conversations.json` both name part `conversations-000`."""
    p = Path(name)
    if p.name == _CONV:
        return p.parent.name or _CONV
    return p.name[:-4] if p.name.endswith(".zip") else p.name


def _from_zip(path: Path) -> list:
    out: list = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if not info.is_dir() and info.filename.rsplit("/", 1)[-1] == _CONV:
                with z.open(info) as f:
                    out.extend(_conv_list(json.load(f)))
    return out


def _conv_list(data) -> list[dict]:
    return [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []


def _read_manifest(manifest: Path) -> tuple[set[str] | None, str]:
    """(the conversations parts the manifest lists, its created_at or ""). Parts is None if the manifest cannot be
    read or an entry names no file; an empty set means it lists none. Both count as incomplete."""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, ""
    if not isinstance(data, dict):
        return None, ""
    created = _s(data.get("created_at"))
    files = data.get("data_files")
    if not isinstance(files, list):
        return None, created
    parts = set()
    for entry in files:
        if not isinstance(entry, dict) or entry.get("category") != "conversations":
            continue
        name = next((entry[k] for k in _PART_KEYS if isinstance(entry.get(k), str)), None)
        if name is None:
            return None, created
        parts.add(_part_id(name))
    return parts, created


def _is_part_name(name: str) -> bool:
    """`conversations-000` and the like: one part of a possibly multi-part export."""
    return bool(_PART_RE.fullmatch(name))


def load_export(path: Path) -> Export:
    path = Path(path)
    convs: list[dict] = []
    manifest: Path | None = None
    read_parts: set[str] = set()
    bare = False            # a lone conversations.json with no manifest beside it and no part marker
    if path.is_file():
        if path.suffix == ".zip":
            convs = _from_zip(path)     # a zip is one part; alone it cannot show the export is whole
        else:
            convs = _conv_list(json.loads(path.read_bytes()))
            bare = not _is_part_name(path.parent.name) and not any(path.parent.glob("manifest-*.json"))
    elif path.is_dir():
        manifests = sorted(path.glob("manifest-*.json"))
        manifest = manifests[-1] if manifests else None
        for z in sorted(path.glob("*.zip")):
            with zipfile.ZipFile(z) as zf:
                has = any(n.rsplit("/", 1)[-1] == _CONV for n in zf.namelist())
            if has:
                convs.extend(_from_zip(z))
                read_parts.add(_part_id(z.name))
        for j in sorted(path.rglob(_CONV)):
            convs.extend(_conv_list(json.loads(j.read_bytes())))
            read_parts.add(_part_id(str(j.relative_to(path))))
    else:
        raise FileNotFoundError(path)

    newest: dict[str, dict] = {}
    for c in convs:
        uuid = c.get("uuid")
        if not isinstance(uuid, str) or not uuid:
            continue
        old = newest.get(uuid)
        if old is None or _s(c.get("updated_at")) > _s(old.get("updated_at")):
            newest[uuid] = c
    sessions = [session_of(newest[u]) for u in sorted(newest)]

    # Complete (so missing chats may be deleted) only when proven: a manifest listing at least one conversations
    # part with every listed part read, or a bare conversations.json. Anything else may be one part of many.
    created = ""
    if manifest is None:
        complete = bare
        export_id = hashlib.sha256("\n".join(sorted(newest)).encode("utf-8")).hexdigest()[:16]
    else:
        listed, created = _read_manifest(manifest)
        complete = bool(listed) and listed <= read_parts
        export_id = manifest.stem
    export_date = created or max((s.updated_at for s in sessions), default="")
    return Export(sessions=sessions, export_date=export_date, export_id=export_id, complete=complete)
