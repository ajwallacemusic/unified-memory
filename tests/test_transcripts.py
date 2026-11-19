import json
from datetime import date

from um.evidence import load_evidence
from um.transcripts import evidence_from_transcript

SID = "abcdef12-0000"


def u(content, ts, origin=None, meta=None, tool=False, side=False):
    d = {"type": "user", "sessionId": SID, "timestamp": ts, "isSidechain": side, "uuid": "x",
         "message": {"role": "user", "content": content}}
    if origin:
        d["origin"] = origin
    if meta:
        d["isMeta"] = True
    if tool:
        d["toolUseResult"] = {"stdout": "..."}
    return d


def a(text, ts):
    return {"type": "assistant", "sessionId": SID, "timestamp": ts, "isSidechain": False, "uuid": "y",
            "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "secret plan"},
                                                         {"type": "text", "text": text},
                                                         {"type": "tool_use", "name": "Bash", "input": {}}]}}


LINES = [
    {"type": "mode", "mode": "x"},
    u("I work at Brightline now.", "2026-11-09T10:00:00Z", origin={"kind": "human"}),
    u([{"type": "text", "text": "My squat is 405."}, {"type": "image"}], "2026-11-10T10:00:00Z", origin={"kind": "human"}),
    u("Old-format typed prompt about Larchgate.", "2026-11-10T10:01:00Z"),
    u("<command-name>/clear</command-name>", "2026-11-10T10:02:00Z"),
    u([{"type": "text", "text": "<system-reminder>be careful</system-reminder>"}], "2026-11-10T10:03:00Z", meta=True),
    u("Task finished: sync report says employer Oakfield", "2026-11-10T10:04:00Z",
      origin={"kind": "task-notification", "producer": "session-task"}),
    u([{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "Sync report: employer is Zentrix"}]}],
      "2026-11-10T10:05:00Z", tool=True),
    u([{"type": "tool_result", "tool_use_id": "t2", "content": "plain string result Quillon"}], "2026-11-10T10:06:00Z", tool=True),
    u("sidechain prompt Mirebrook", "2026-11-10T10:07:00Z", origin={"kind": "human"}, side=True),
    a("Noted, you work at Brightline.", "2026-11-10T10:08:00Z"),
]


def write(tmp_path, lines=LINES):
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
    return p


def by_origin(out):
    return {e.origin: e for e in load_evidence(out).values()}


def test_typed_prompts_are_user_said_and_nothing_else_is(tmp_path):
    out = tmp_path / "ev"
    evidence_from_transcript(write(tmp_path), out)
    ev = by_origin(out)
    us = ev["user-said"].text
    assert "Brightline" in us and "squat is 405" in us and "Larchgate" in us
    for bad in ("command-name", "system-reminder", "Oakfield", "Zentrix", "Quillon", "Mirebrook"):
        assert bad not in us, bad


def test_tool_results_are_tool_output(tmp_path):
    out = tmp_path / "ev"
    evidence_from_transcript(write(tmp_path), out)
    t = by_origin(out)["tool-output"].text
    assert "Zentrix" in t and "Quillon" in t


def test_assistant_text_without_thinking(tmp_path):
    out = tmp_path / "ev"
    evidence_from_transcript(write(tmp_path), out)
    t = by_origin(out)["assistant"].text
    assert "Noted, you work at Brightline." in t and "secret plan" not in t


def test_since_excludes_older_messages_and_dates_are_set(tmp_path):
    out = tmp_path / "ev"
    paths = evidence_from_transcript(write(tmp_path), out, since=date(2026, 11, 10))
    ev = by_origin(out)
    assert "Brightline now" not in ev["user-said"].text and "squat" in ev["user-said"].text
    assert all(e.date == "2026-11-10" for e in ev.values())
    assert {p.name for p in paths} == {"sabcdef12-user.md", "sabcdef12-assistant.md", "sabcdef12-tool.md"}


def test_after_excludes_messages_a_build_has_already_read(tmp_path):
    out = tmp_path / "ev"
    evidence_from_transcript(write(tmp_path), out, since=date(2026, 11, 10), after="2026-11-10T10:00:30Z")
    us = by_origin(out)["user-said"].text
    assert "squat" not in us and "Larchgate" in us


def test_compile_reads_a_transcript_message_only_once(tmp_path):
    import subprocess
    from um.cli import main
    from um.llm import FakeLLM, Reply
    p = tmp_path / "profile"
    (p / "areas").mkdir(parents=True)
    (p / "areas" / "x.md").write_text("# X\n- [stated] a\n")
    subprocess.run(["git", "init", "-q"], cwd=p, check=True)
    proj = tmp_path / "projects" / "-x"
    proj.mkdir(parents=True)
    (proj / "s.jsonl").write_text(json.dumps(u("My codeword is FINCH-11.", "2026-11-11T09:00:00Z",
                                                origin={"kind": "human"})) + "\n")
    first, second = FakeLLM([Reply("[]", "end_turn", 1, 1)]), FakeLLM([Reply("[]", "end_turn", 1, 1)])
    main(["compile", "--profile", str(p), "--projects", str(tmp_path / "projects"), "--today", "2026-11-11"], llm=first)
    main(["compile", "--profile", str(p), "--projects", str(tmp_path / "projects"), "--today", "2026-11-11"], llm=second)
    assert "FINCH-11" in first.calls[0]["user"]
    assert not second.calls or "FINCH-11" not in second.calls[0]["user"]
