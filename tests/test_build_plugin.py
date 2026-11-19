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
