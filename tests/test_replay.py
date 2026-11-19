import json
import re
from datetime import date

from conftest import CountingFakeLLM
from um.llm import Reply
from um.synth.replay import answer_probes, oracle, replay
from um.synth.scenario import generate, truth

_DATE = re.compile(r"(20\d\d)[-/](\d\d)[-/](\d\d)")


def dates_in(text):
    return [date(int(y), int(m), int(d)) for y, m, d in _DATE.findall(text)]


class RecordingFakeLLM:
    """Records, for every call, the dates it could see: in its prompt and in every file its tools can read."""

    def __init__(self):
        self.calls = []

    def _seen(self, system, user, tools=None):
        text = user   # system prompts are fixed templates; their worked examples carry made-up dates
        if tools is not None:
            text += "".join(p.read_text(errors="replace") for p in tools.root.rglob("*") if p.is_file())
        today = re.search(r"Today's date is (\d{4}-\d\d-\d\d)", system + user)
        return text, today.group(1) if today else None

    def complete(self, *, model, system, user, max_tokens, label):
        text, today = self._seen(system, user)
        self.calls.append((label, dates_in(text), today))
        return Reply("1. UNKNOWN", "end_turn", 1, 1)

    def run_tools(self, *, model, system, user, tools, max_turns, max_tokens, label):
        text, today = self._seen(system, user, tools)
        self.calls.append((label, dates_in(text), today))
        return Reply("1. UNKNOWN", "end_turn", 1, 1)


def test_nothing_from_the_future_is_readable(tmp_path):
    s = generate(1, 0)
    for arm in ("z", "a", "b"):
        llm = RecordingFakeLLM()
        replay(s, arm, tmp_path / arm, llm, "m", "m")
        answers = [c for c in llm.calls if c[0] == "answer:probes"]
        assert [date.fromisoformat(c[2]) for c in answers] == list(s.checkpoints)
        pending = []
        for label, seen, today in llm.calls:
            pending.append(seen)
            if label == "answer:probes":
                limit = date.fromisoformat(today)
                assert all(d <= limit for group in pending for d in group), arm
                pending = []


def test_rows_cover_every_probe_once_and_resume_skips_finished_weeks(tmp_path):
    s = generate(1, 0)
    llm = CountingFakeLLM("1. UNKNOWN")
    rows = replay(s, "z", tmp_path, llm, "m", "m")
    n = llm.calls
    assert sorted(r["probe_id"] for r in rows) == sorted(p.id for p in s.probes)
    assert {r["label"] for r in rows} <= {"current", "stale", "planted", "missing"}
    assert replay(s, "z", tmp_path, llm, "m", "m") == rows and llm.calls == n


def test_b_writer_never_sees_tool_output_and_other_arms_do(tmp_path):
    s = generate(1, 0)
    for arm, expect in (("z", True), ("b", False)):
        llm = RecordingFakeLLM()
        seen_tool = []
        orig = llm.run_tools

        def spy(**kw):
            if kw["label"] == "writer":
                seen_tool.append("tool:" in kw["user"])
            return orig(**kw)

        llm.run_tools = spy
        replay(s, arm, tmp_path / arm, llm, "m", "m")
        assert any(seen_tool) is expect


def test_answer_probes_reads_a_numbered_list_and_hides_hidden_files(tmp_path):
    s = generate(1, 0)
    probes = [p for p in s.probes if p.day == s.checkpoints[0]][:3]
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "MEMORY.md").write_text("- x\n")
    (tmp_path / ".pass.json").write_text("{}")
    seen = {}

    class One:
        def run_tools(self, **kw):
            seen["files"] = sorted(p.name for p in kw["tools"].root.rglob("*") if p.is_file())
            return Reply("1. Alpha\n2) Beta\n   more\n", "end_turn", 1, 1)

    got = answer_probes(probes, tmp_path, One(), "m", s.checkpoints[0])
    assert got == {probes[0].id: "Alpha", probes[1].id: "Beta more", probes[2].id: ""}
    assert seen["files"] == ["MEMORY.md"]


def test_oracle_answers_with_the_truth_on_that_day(tmp_path):
    s = generate(1, 0)
    day = s.checkpoints[-1]
    attr = next(p.attr for p in s.probes if p.category == "attacked")
    from um.synth.scenario import PHRASE
    for q in ({"attr": attr}, {"attr": PHRASE[attr]}, {"attr": "", "text": f"Is your {PHRASE[attr]} still the same?"}):
        assert truth(s, attr, day) in oracle(s, day)(q)
    assert oracle(s, day)({"attr": "favourite colour", "text": "?"}) is None


def test_replay_uses_the_chosen_writer_prompt(tmp_path):
    s = generate(1, 0)
    seen = []

    class Spy(CountingFakeLLM):
        def run_tools(self, **kw):
            if kw["label"] == "writer":
                seen.append(kw["system"])
            return super().run_tools(**kw)

    replay(s, "z", tmp_path, Spy("1. UNKNOWN"), "m", "m", writer_prompt="writer_absorb.md")
    assert seen and all("what tools and connectors report" in x for x in seen)


def test_nohook_variant_feeds_tool_conversations_to_writer(tmp_path, monkeypatch):
    import um.synth.replay as rp
    s = generate(1, 0)
    first = s.checkpoints[0]
    n_tool = sum(1 for e in s.events if s.start < e.day <= first and e.origin == "tool-output")
    n_all = sum(1 for e in s.events if s.start < e.day <= first)
    assert n_tool > 0
    seen = {}
    for arm in ("b", "b-nohook"):
        got = []
        monkeypatch.setattr(rp, "write_memory", lambda sessions, *a, **k: got.append(len(sessions)) or [])
        rows = replay(s, arm, tmp_path / arm, CountingFakeLLM("1. UNKNOWN"), "m", "m")
        seen[arm] = got[0]
        assert {r["arm"] for r in rows} == {arm}
    assert seen["b-nohook"] == n_all
    assert seen["b"] == n_all - n_tool


class SyncCompileLLM(CountingFakeLLM):
    """Compile proposes replacing a store line with every value a sync report names, with a question attached;
    every other call returns an empty answer list."""

    def complete(self, **kw):
        self.calls += 1
        if kw["label"] != "compile":
            return Reply("1. UNKNOWN", "end_turn", 1, 1)
        user = kw["user"]
        changes = []
        for m in re.finditer(r"\[(\w+)\] origin: tool-output.*\n(?:.*\n)*?tool: (Sync report: the (?:user's )?(.+?) changed from (\S+) to (\S+?)\.)", user):
            eid, quote, phrase, old, new = m.groups()
            line = re.search(rf"^(\S+) \| \S+ \| (- [^|\n]*?: {re.escape(old)}\b[^\n]*)$", user, re.M)
            if line:
                changes.append({"op": "replace", "file": line.group(1), "old": line.group(2),
                                "new": line.group(2).replace(old, new), "citations": [{"evidence": eid, "quote": quote}],
                                "question": {"attr": phrase, "text": f"Is your {phrase} {new} now?"}})
        return Reply(json.dumps(changes), "end_turn", 1, 1)


def test_silent_oracle_lands_no_override(tmp_path):
    s = generate(1, 0)
    replay(s, "b", tmp_path, SyncCompileLLM(), "m", "m", oracle_mode="never")
    asked_any = False
    for w in range(1, len(s.checkpoints) + 1):
        wdir = tmp_path / f"week-{w}"
        record = json.loads((wdir / "out" / ".pass.json").read_text())
        done = json.loads((wdir / ".done").read_text())
        assert done["pass"]["questions_asked"] <= 3
        for q in record["questions"]:
            asked_any = True
            assert q["status"] in ("no answer", "over budget")
        assert not any(c["applied"] for c in record["changes"] if c["decision"] == "ask")
        for c in record["changes"]:
            if c["decision"] == "ask":
                assert c["old"] in (wdir / "out" / c["file"]).read_text()
    assert asked_any


def test_late_answers_become_user_said_evidence_in_the_delivery_week(tmp_path):
    s = generate(1, 0)
    replay(s, "b", tmp_path, SyncCompileLLM(), "m", "m", oracle_mode="late")
    first_ask = next(w for w in range(1, 7)
                     if json.loads((tmp_path / f"week-{w}" / "out" / ".pass.json").read_text())["questions"])
    assert not list((tmp_path / f"week-{first_ask}" / "in").glob(".answers/late*.md"))
    delivered = list((tmp_path / f"week-{first_ask + 1}" / "in").glob(".answers/late*.md"))
    assert delivered
    text = delivered[0].read_text()
    assert text.startswith("origin: user-said\ndate: ") and "My " in text
