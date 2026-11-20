"""stdio MCP server (plan 5, Task 7). Driven with io.StringIO and a fake tool implementation."""
import io
import json

from um.search.mcp_server import PROTOCOL_VERSIONS, handle, serve

SPECS = [{"name": "conversation_search", "description": "d", "inputSchema": {"type": "object"}},
         {"name": "recent_chats", "description": "d", "inputSchema": {"type": "object"}}]
INSTR = "Use the profile for what is true now."


def fake_call(name, args):
    if name == "bad":
        raise ValueError("max_results must be an integer")
    if name == "boom":
        raise RuntimeError("secret text")
    return {"text": f"ran {name} with {args.get('query')}\nline two", "structured": {"results": [], "name": name}}


def run(*msgs, call=fake_call):
    lines = [m if isinstance(m, str) else json.dumps(m) for m in msgs]
    out = io.StringIO()
    serve(io.StringIO("\n".join(lines) + "\n"), out, call=call, specs=SPECS, instructions=INSTR)
    return [json.loads(line) for line in out.getvalue().splitlines()]


def req(i, method, params=None):
    m = {"jsonrpc": "2.0", "id": i, "method": method}
    if params is not None:
        m["params"] = params
    return m


def init(version):
    return req(1, "initialize", {"protocolVersion": version, "capabilities": {},
                                 "clientInfo": {"name": "t", "version": "1"}})


def test_initialize_negotiates_version_and_sends_instructions():
    for v in PROTOCOL_VERSIONS:
        [r] = run(init(v))
        assert r["id"] == 1 and r["jsonrpc"] == "2.0"
        res = r["result"]
        assert res["protocolVersion"] == v
        assert res["capabilities"] == {"tools": {}}
        assert res["serverInfo"] == {"name": "um-search", "version": "0.1.0"}
        assert res["instructions"] == INSTR


def test_unknown_client_version_gets_ours():
    [r] = run(init("1999-01-01"))
    assert r["result"]["protocolVersion"] == PROTOCOL_VERSIONS[0]


def test_tools_list_returns_specs():
    [r] = run(req(2, "tools/list"))
    assert r["result"] == {"tools": SPECS}


def test_ping():
    [r] = run(req(3, "ping"))
    assert r == {"jsonrpc": "2.0", "id": 3, "result": {}}


def test_tools_call_wraps_text_and_structured():
    [r] = run(req(4, "tools/call", {"name": "conversation_search", "arguments": {"query": "kiln"}}))
    assert r["result"] == {"content": [{"type": "text", "text": "ran conversation_search with kiln\nline two"}],
                           "structuredContent": {"results": [], "name": "conversation_search"},
                           "isError": False}


def test_tools_call_without_arguments_passes_empty_dict():
    seen = []
    run(req(4, "tools/call", {"name": "recent_chats"}),
        call=lambda n, a: seen.append((n, a)) or {"text": "", "structured": {}})
    assert seen == [("recent_chats", {})]


def test_bad_arguments_are_a_tool_error_not_a_crash():
    rs = run(req(5, "tools/call", {"name": "bad", "arguments": {}}), req(6, "ping"))
    assert rs[0]["id"] == 5 and "error" not in rs[0]
    assert rs[0]["result"]["isError"] is True
    assert rs[0]["result"]["content"] == [{"type": "text", "text": "max_results must be an integer"}]
    assert rs[1] == {"jsonrpc": "2.0", "id": 6, "result": {}}


def test_unexpected_exception_does_not_leak_or_exit():
    out = io.StringIO()
    lines = [json.dumps(req(7, "tools/call", {"name": "boom", "arguments": {}})), json.dumps(req(8, "ping"))]
    serve(io.StringIO("\n".join(lines) + "\n"), out, call=fake_call, specs=SPECS, instructions=INSTR)
    assert "secret text" not in out.getvalue()
    rs = [json.loads(x) for x in out.getvalue().splitlines()]
    assert rs[0]["result"]["isError"] is True
    assert rs[0]["result"]["content"][0]["text"] == "search failed: RuntimeError"
    assert rs[1]["id"] == 8


def test_notification_gets_no_response():
    assert run({"jsonrpc": "2.0", "method": "notifications/initialized"},
               {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}}) == []
    assert handle({"jsonrpc": "2.0", "method": "notifications/initialized"},
                  call=fake_call, specs=SPECS, instructions=INSTR) is None


def test_unknown_method_and_garbage_line():
    rs = run(req(9, "resources/list"), "{not json", "", req(10, "ping"))
    assert rs[0]["id"] == 9 and rs[0]["error"]["code"] == -32601
    assert rs[1]["id"] is None and rs[1]["error"]["code"] == -32700
    assert rs[2] == {"jsonrpc": "2.0", "id": 10, "result": {}}
    assert len(rs) == 3                      # the blank line is ignored


def test_modern_discover_probe_gets_an_error_so_client_falls_back():
    # A dual-era client probes with server/discover; a legacy server answers with an error (spec, stdio,
    # "Backward Compatibility"), which makes the client fall back to initialize.
    [r] = run(req(11, "server/discover"))
    assert r["error"]["code"] == -32601


def test_non_object_messages_and_bad_params_are_rejected_not_fatal():
    rs = run("[1, 2]", "42", req(12, "tools/call", {"name": "recent_chats", "arguments": "x"}),
             req(13, "tools/call", "nope"), req(14, "ping"))
    assert rs[0]["error"]["code"] == -32600 and rs[0]["id"] is None
    assert rs[1]["error"]["code"] == -32600
    assert rs[2]["id"] == 12 and rs[2]["error"]["code"] == -32602
    assert rs[3]["id"] == 13 and rs[3]["error"]["code"] == -32602
    assert rs[4]["id"] == 14


def test_stdout_has_only_json_lines():
    out = io.StringIO()
    lines = [json.dumps(init("2025-06-18")), json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
             json.dumps(req(2, "tools/list")),
             json.dumps(req(3, "tools/call", {"name": "conversation_search", "arguments": {"query": "a\nb"}})),
             "garbage", json.dumps(req(4, "nope"))]
    serve(io.StringIO("\n".join(lines)), out, call=fake_call, specs=SPECS, instructions=INSTR)
    text = out.getvalue()
    assert text.endswith("\n")
    rows = text.splitlines()
    assert len(rows) == 5
    for row in rows:
        assert json.loads(row)["jsonrpc"] == "2.0"


def test_serve_flushes_after_each_response():
    class Out(io.StringIO):
        flushes = 0

        def flush(self):
            Out.flushes += 1
            super().flush()

    out = Out()
    serve(io.StringIO(json.dumps(req(1, "ping")) + "\n" + json.dumps(req(2, "ping")) + "\n"), out,
          call=fake_call, specs=SPECS, instructions=INSTR)
    assert Out.flushes >= 2
