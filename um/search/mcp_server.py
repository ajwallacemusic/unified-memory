"""stdio MCP server for conversation search (spec, "How Claude Code reaches it").

Hand-written JSON-RPC 2.0 over newline-delimited stdin/stdout, standard library only. It speaks the
initialize-handshake ("legacy") revisions of MCP. A dual-era client first probes with `server/discover`; this
server answers that with -32601, which the MCP stdio transport's backward-compatibility rules treat as "legacy
server, fall back to initialize". Nothing but JSON-RPC is written to stdout.

`handle` and `serve` take the tool implementation by injection (`call(name, args) -> {"text", "structured"}`,
raising ValueError for bad arguments), so they are tested without an index. `main` wires the real tools.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Callable

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "um-search", "version": "0.1.0"}

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602


def _error(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _result(id_, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _tool_error(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def handle(msg, *, call: Callable[[str, dict], dict], specs: list[dict], instructions: str) -> dict | None:
    """One JSON-RPC message in, a response (or None for a notification) out. Never raises."""
    if not isinstance(msg, dict):
        return _error(None, INVALID_REQUEST, "invalid request")
    method = msg.get("method")
    if "id" not in msg:
        return None                                   # notifications get no response
    id_ = msg["id"]
    if not isinstance(method, str):
        return _error(id_, INVALID_REQUEST, "invalid request")
    params = msg.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _error(id_, INVALID_PARAMS, "params must be an object")

    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return _result(id_, {"protocolVersion": version, "capabilities": {"tools": {}},
                             "serverInfo": dict(SERVER_INFO), "instructions": instructions})
    if method == "ping":
        return _result(id_, {})
    if method == "tools/list":
        return _result(id_, {"tools": specs})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments")
        if args is None:
            args = {}
        if not isinstance(name, str) or not isinstance(args, dict):
            return _error(id_, INVALID_PARAMS, "tools/call needs a string name and object arguments")
        try:
            out = call(name, args)
        except ValueError as e:
            return _result(id_, _tool_error(str(e) or "invalid arguments"))
        except Exception as e:                        # do not echo the exception text: it may quote stored data
            return _result(id_, _tool_error(f"search failed: {type(e).__name__}"))
        return _result(id_, {"content": [{"type": "text", "text": out["text"]}],
                             "structuredContent": out["structured"], "isError": False})
    return _error(id_, METHOD_NOT_FOUND, f"method not found: {method}")


def serve(stdin, stdout, *, call, specs, instructions) -> None:
    """Read newline-delimited JSON-RPC from `stdin` until EOF; write one JSON line per response and flush."""
    for line in iter(stdin.readline, ""):
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            resp = _error(None, PARSE_ERROR, "parse error")
        else:
            try:
                resp = handle(msg, call=call, specs=specs, instructions=instructions)
            except Exception as e:                    # handle should not raise; never let the loop die
                resp = _error(msg.get("id") if isinstance(msg, dict) else None, -32603,
                              f"internal error: {type(e).__name__}")
        if resp is None:
            continue
        try:
            text = json.dumps(resp, ensure_ascii=False)
        except (TypeError, ValueError) as e:          # a non-serialisable result from `call`
            text = json.dumps(_result(resp.get("id"), _tool_error(f"search failed: {type(e).__name__}")))
        stdout.write(text + "\n")
        stdout.flush()


def _desktop_root() -> Path | None:
    p = Path.home() / "Library/Application Support/Claude/local-agent-mode-sessions"
    return p if p.is_dir() else None


def _catch_up(index) -> dict:
    from um import config
    from um.search.ingest import catch_up
    return catch_up(index, projects=Path.home() / ".claude" / "projects", desktop=_desktop_root(),
                    now=time.time(), include_sdk=config.search_include_sdk())


def make_call(*, before_query: Callable | None = None, env=None) -> Callable[[str, dict], dict]:
    """The real tool implementation. The off switch is read on every call (no restart needed): when search is off
    the tools say so and nothing is opened or caught up. On the first open, an index cut with other chunk
    parameters is re-chunked in place. `before_query(index)` defaults to the catch-up."""
    before_query = before_query or _catch_up
    state: dict = {}

    def call(name: str, args: dict) -> dict:
        from um import config
        from um.search.tools import call_tool
        if not config.search_enabled():
            return {"text": config.SEARCH_OFF, "structured": {"search": "off", "results": []}}
        if "error" in state:
            raise ValueError(state["error"])
        if "index" not in state:
            from um.search.index import Index, check_index_path
            path = config.search_index_path()
            try:
                check_index_path(path, config.profile_path())
                index = Index(path)
            except ValueError as e:
                state["error"] = str(e)
                raise
            index.ensure_chunk_params()
            state["index"] = index
        index = state["index"]
        return call_tool(index, name, args, env=os.environ if env is None else env,
                         before_query=lambda: before_query(index))

    return call


def main() -> None:
    """Wire the real tools. Imports and the index open happen on the first tools/call, so start is fast."""
    from um.search.tools import INSTRUCTIONS, TOOL_SPECS

    call = make_call()
    out = sys.stdout
    sys.stdout = sys.stderr                           # a stray print anywhere must not corrupt the protocol
    serve(sys.stdin, out, call=call, specs=TOOL_SPECS, instructions=INSTRUCTIONS)


if __name__ == "__main__":
    main()
