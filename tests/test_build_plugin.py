import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import importlib.util

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("build_plugin", ROOT / "scripts" / "build_plugin.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
build_plugin = _mod.build_plugin
EXCLUDED = ("data/", "results/", "prototype/", "docs/research/", "tests/", ".venv", "um/synth/", "um/bench/", "um/recall/")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("p") / "plugin"
    files = build_plugin(ROOT, out)
    return out, files


def test_built_plugin_has_no_excluded_paths(built):
    out, files = built
    assert files and all(not f.startswith(EXCLUDED) and "/__pycache__/" not in f for f in files)
    for must in (".claude-plugin/plugin.json", "hooks/hooks.json", "commands/compile.md", "um/cli.py",
                 "um/hooks/memory_guard.py", "um/prompts/compile.md", "um/prompts/categorize.md", "bridge/task-prompt.md"):
        assert (out / must).exists(), must


def test_built_plugin_imports_from_its_own_root(built):
    out, _ = built
    code = "import um.cli, um.hooks.memory_guard, um.bridge.prepare, um.bridge.categorize; print('ok')"
    r = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(out)!r}); {code}"],
                       capture_output=True, text=True, cwd=out)
    assert r.stdout.strip() == "ok", r.stderr


def test_no_private_text_in_the_plugin(built):
    out, _ = built
    cases = ROOT / "data/private/real-stores/2026-11-10/cases.json"
    if not cases.exists():
        pytest.skip("no private case file on this machine")
    patterns = [re.compile(c["stale_pattern"], re.I) for c in json.loads(cases.read_text())]
    for f in out.rglob("*"):
        if f.is_file():
            text = f.read_text(errors="ignore")
            assert not any(p.search(text) for p in patterns), f
    assert not any("@gmail.com" in f.read_text(errors="ignore") for f in out.rglob("*") if f.is_file())


# --- Plan 5 Task 11: the search server ships in the plugin. Synthetic fixtures only; HOME is a temp dir. ---

import os
import time


def _server_env(tmp_path, plugin):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("UM_", "CLAUDE_"))}
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env.update(PYTHONPATH=str(plugin), HOME=str(home), UM_CONFIG=str(tmp_path / "cfg" / "config.json"),
               UM_PROFILE=str(tmp_path / "claude-profile"), UM_SEARCH_INDEX=str(tmp_path / "x" / "i.sqlite"))
    return env, home


def _rpc(env, cwd, messages, timeout=5):
    lines = "".join(json.dumps(m) + "\n" for m in messages)
    r = subprocess.run(["python3", "-m", "um.search.mcp_server"], input=lines, capture_output=True, text=True,
                       env=env, cwd=cwd, timeout=timeout)
    return [json.loads(x) for x in r.stdout.splitlines() if x.strip()], r


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}


def test_plugin_ships_search(tmp_path):
    files = build_plugin(ROOT, tmp_path / "plugin")
    assert ".mcp.json" in files and "um/search/mcp_server.py" in files and "um/search/sources/web.py" in files
    cfg = json.loads((tmp_path / "plugin" / ".mcp.json").read_text())["mcpServers"]["um-search"]
    assert cfg["command"] == "python3" and cfg["args"] == ["-m", "um.search.mcp_server"] and cfg["alwaysLoad"] is True
    assert cfg["env"] == {"PYTHONPATH": "${CLAUDE_PLUGIN_ROOT}"}
    assert not any(f.startswith("um/bench/") for f in files)


def test_plugin_search_has_no_bench_import(tmp_path):
    out = tmp_path / "plugin"
    build_plugin(ROOT, out)
    env, _ = _server_env(tmp_path, out)
    r = subprocess.run(["python3", "-c", "import um.search.mcp_server, um.search.tools, um.search.ingest; print('ok')"],
                       capture_output=True, text=True, env=env, cwd=tmp_path)
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr


def test_session_start_hook_is_async():
    hooks = json.loads((ROOT / "plugin_src" / "hooks" / "hooks.json").read_text())
    h = hooks["hooks"]["SessionStart"][0]["hooks"][0]
    assert h["async"] is True and h["type"] == "command" and "search index" in h["command"]
    assert "search" in hooks["description"].lower()


def test_server_answers_initialize_from_built_plugin(tmp_path):
    out = tmp_path / "plugin"
    build_plugin(ROOT, out)
    env, _ = _server_env(tmp_path, out)
    t0 = time.monotonic()
    got, r = _rpc(env, tmp_path, [INIT, INITIALIZED, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
    assert time.monotonic() - t0 < 5
    assert [m["id"] for m in got] == [1, 2], r.stderr
    assert got[0]["result"]["protocolVersion"] == "2025-06-18"
    assert got[0]["result"]["serverInfo"]["name"] == "um-search"
    assert {t["name"] for t in got[1]["result"]["tools"]} == {"conversation_search", "recent_chats"}
    assert not (tmp_path / "x" / "i.sqlite").exists()          # opened lazily, on the first tools/call


def test_server_search_call_end_to_end(tmp_path):
    out = tmp_path / "plugin"
    build_plugin(ROOT, out)
    env, home = _server_env(tmp_path, out)
    sid = "fixture-sess-7c1"
    path = home / ".claude" / "projects" / "-work-proj" / f"{sid}.jsonl"
    path.parent.mkdir(parents=True)
    recs = [{"type": "user", "uuid": "u1", "timestamp": "2026-01-01T00:01:00Z", "sessionId": sid, "cwd": "/work/proj",
             "entrypoint": "cli", "origin": {"kind": "human"},
             "message": {"role": "user", "content": "which harbor did the zephyrine ferry leave from"}},
            {"type": "assistant", "uuid": "a1", "timestamp": "2026-01-01T00:01:30Z", "sessionId": sid,
             "cwd": "/work/proj", "entrypoint": "cli",
             "message": {"role": "assistant", "content": [{"type": "text", "text": "It left from Port Quillon."}]}}]
    path.write_text("".join(json.dumps(r) + "\n" for r in recs))
    old = time.time() - 3600
    os.utime(path, (old, old))
    call = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "conversation_search", "arguments": {"query": "zephyrine ferry harbor"}}}
    got, r = _rpc(env, tmp_path, [INIT, INITIALIZED, call], timeout=20)
    res = got[-1]["result"]
    assert res["isError"] is False, res
    assert sid in res["content"][0]["text"]


def test_the_committed_plugin_is_a_fresh_build(tmp_path):
    """marketplace.json installs ./plugin and the export ships it, so it must match the source exactly."""
    import filecmp
    root = Path(__file__).resolve().parents[1]
    fresh = sorted(build_plugin(root, tmp_path / "plugin"))
    committed = sorted(p.relative_to(root / "plugin").as_posix() for p in (root / "plugin").rglob("*")
                       if p.is_file() and "__pycache__" not in p.parts)
    assert committed == fresh
    stale = [f for f in fresh if not filecmp.cmp(root / "plugin" / f, tmp_path / "plugin" / f, shallow=False)]
    assert stale == []
