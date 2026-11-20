import hashlib
from pathlib import Path

import pytest

from um.llm import Reply


def tree_hash(root) -> str:
    root = Path(root)
    h = hashlib.sha256()
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        h.update(str(p.relative_to(root)).encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


@pytest.fixture
def store(tmp_path):
    s = tmp_path / "store"
    s.mkdir()
    (s / "MEMORY.md").write_text("- [Work](topic1.md): job and employer\n- [Home](topic2.md): house and family\n")
    (s / "topic1.md").write_text("- Works at Oakfield (2023-03-02)\n- Started at Brightline (2023-05-20)\n" * 5)
    (s / "topic2.md").write_text("- Lives in a brick house (2023-04-11)\n" * 5)
    return s


@pytest.fixture
def tiny_data():
    return Path(__file__).parent / "data" / "lme_tiny.json"


class CountingFakeLLM:
    """Answers every call with an ok reply and counts calls."""

    def __init__(self, text="yes"):
        self.text = text
        self.calls = 0

    def complete(self, **kw):
        self.calls += 1
        return Reply(self.text, "end_turn", 10, 2)

    def run_tools(self, **kw):
        self.calls += 1
        return Reply(self.text, "end_turn", 10, 2)


@pytest.fixture(autouse=True)
def _no_real_config(tmp_path_factory, monkeypatch):
    """No test reads the user's real ~/.config/unified-memory, profile or model route."""
    monkeypatch.setenv("UM_CONFIG", str(tmp_path_factory.mktemp("cfg") / "config.json"))
    monkeypatch.delenv("UM_LLM", raising=False)
    # `um.cli erase` reaches the search index when it exists: never the real one.
    monkeypatch.setenv("UM_SEARCH_INDEX", str(tmp_path_factory.mktemp("search") / "search.sqlite"))
