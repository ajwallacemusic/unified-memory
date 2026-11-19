"""File tools confined to one directory, for model-driven reading and editing of a memory store.

Every failure comes back as a string starting with "ERROR:" so the model can see it and recover;
nothing raises to the caller.
"""
from __future__ import annotations

import re
from pathlib import Path

_MAX_VIEW_CHARS = 60_000
_MAX_GREP_LINES = 200


class _ToolError(Exception):
    pass


class Toolbox:
    def __init__(self, root: Path, writable: bool):
        self.root = Path(root).resolve()
        self.writable = writable
        self.root.mkdir(parents=True, exist_ok=True)

    # -- path safety -------------------------------------------------------------------------

    def _resolve(self, path: str) -> Path:
        if not isinstance(path, str):
            raise _ToolError("path must be a string")
        candidate = Path(path)
        if candidate.is_absolute():
            raise _ToolError("absolute paths are not allowed; give a path relative to the store")
        resolved = (self.root / candidate).resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise _ToolError(f"{path!r} is outside the store")
        return resolved

    def _rel(self, p: Path) -> str:
        return str(p.relative_to(self.root))

    def _need_write(self) -> None:
        if not self.writable:
            raise _ToolError("this store is read-only")

    # -- tools -------------------------------------------------------------------------------

    def view(self, path: str = "") -> str:
        return self._guard(self._view, path)

    def grep(self, pattern: str, path: str = "") -> str:
        return self._guard(self._grep, pattern, path)

    def write(self, path: str, content: str) -> str:
        return self._guard(self._write, path, content)

    def str_replace(self, path: str, old: str, new: str) -> str:
        return self._guard(self._str_replace, path, old, new)

    def delete(self, path: str) -> str:
        return self._guard(self._delete, path)

    def _view(self, path: str = "") -> str:
        target = self._resolve(path)
        if not target.exists():
            raise _ToolError(f"{path!r} does not exist")
        if target.is_dir():
            entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
            lines = [f"{e.name}/" if e.is_dir() else f"{e.name}  ({e.stat().st_size} bytes)" for e in entries]
            return "\n".join(lines) if lines else "(empty directory)"
        text = target.read_text(errors="replace")
        truncated = len(text) > _MAX_VIEW_CHARS
        numbered = "\n".join(f"{n:>5}\t{line}" for n, line in enumerate(text[:_MAX_VIEW_CHARS].splitlines(), 1))
        return numbered + ("\n[truncated]" if truncated else "")

    def _grep(self, pattern: str, path: str = "") -> str:
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            raise _ToolError(f"invalid pattern: {e}")
        target = self._resolve(path)
        if not target.exists():
            raise _ToolError(f"{path!r} does not exist")
        files = [target] if target.is_file() else sorted(p for p in target.rglob("*") if p.is_file())
        hits: list[str] = []
        for f in files:
            if self.root not in f.resolve().parents:
                continue  # a symlink pointing out of the store
            for n, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{self._rel(f)}:{n}: {line[:300]}")
                    if len(hits) >= _MAX_GREP_LINES:
                        return "\n".join(hits) + "\n[more matches not shown]"
        return "\n".join(hits) if hits else "(no matches)"

    def _write(self, path: str, content: str) -> str:
        self._need_write()
        target = self._resolve(path)
        if target == self.root or target.is_dir():
            raise _ToolError(f"{path!r} is a directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return f"wrote {len(content)} characters to {self._rel(target)}"

    def _str_replace(self, path: str, old: str, new: str) -> str:
        self._need_write()
        target = self._resolve(path)
        if not target.is_file():
            raise _ToolError(f"{path!r} is not a file")
        text = target.read_text()
        count = text.count(old)
        if count != 1:
            raise _ToolError(f"expected exactly one occurrence of the old text in {path!r}, found {count}")
        target.write_text(text.replace(old, new))
        return f"replaced one occurrence in {self._rel(target)}"

    def _delete(self, path: str) -> str:
        self._need_write()
        target = self._resolve(path)
        if not target.is_file():
            raise _ToolError(f"{path!r} is not a file")
        target.unlink()
        return f"deleted {self._rel(target)}"

    # -- dispatch ----------------------------------------------------------------------------

    def _guard(self, fn, *args) -> str:
        try:
            return fn(*args)
        except _ToolError as e:
            return f"ERROR: {e}"
        except OSError as e:
            return f"ERROR: {e.strerror or e}"

    def specs(self) -> list[dict]:
        def tool(name: str, description: str, props: dict, required: list[str]) -> dict:
            return {
                "name": name,
                "description": description,
                "input_schema": {"type": "object", "properties": props, "required": required},
            }

        s = {"type": "string"}
        tools = [
            tool("view", "List a directory, or show a file with line numbers. Paths are relative to the store; "
                 "an empty path is the store root.", {"path": s}, []),
            tool("grep", "Search files for a regular expression (case-insensitive). Returns file:line: text.",
                 {"pattern": s, "path": s}, ["pattern"]),
        ]
        if self.writable:
            tools += [
                tool("write", "Create or overwrite a file with the given content.", {"path": s, "content": s},
                     ["path", "content"]),
                tool("str_replace", "Replace text in a file. The old text must occur exactly once.",
                     {"path": s, "old": s, "new": s}, ["path", "old", "new"]),
                tool("delete", "Delete a file.", {"path": s}, ["path"]),
            ]
        return tools

    def call(self, name: str, args: dict) -> str:
        allowed = {s["name"] for s in self.specs()}
        if name not in allowed:
            known = name in {"view", "grep", "write", "str_replace", "delete"}
            return "ERROR: this store is read-only" if known else f"ERROR: unknown tool {name!r}"
        try:
            return getattr(self, name)(**args)
        except TypeError as e:
            return f"ERROR: bad arguments for {name}: {e}"
