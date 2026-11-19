import json

from um.arms import b
from um.bench.public import pipeline as pl
from um.evidence import load_evidence
from um.hooks.profile_context import HEADER
from um.llm import FakeLLM, Reply


def S(n, date, *turns):
    return pl.Session(f"x{n}", date, tuple(turns))


SESSIONS = [
    S(2, "2026-02-03", ("user", "I moved to Larkspur last week."), ("assistant", "Congratulations on the move!")),
    S(1, "2026-02-01", ("user", "My dog is called Pepper."), ("assistant", "Pepper is a lovely name.")),
]


def reply(changes, **kw):
    return Reply(json.dumps(changes), "end_turn", 100, 20, **kw)


def test_write_evidence_marks_user_and_assistant_turns_by_structure(tmp_path):
    ids = pl.write_evidence(SESSIONS[:1], tmp_path / "ev", start=7)
    ev = load_evidence(tmp_path / "ev")
    assert ids == ["s007-user", "s007-assistant"]
    assert ev["s007-user"].origin == "user-said" and ev["s007-user"].date == "2026-02-03"
    assert ev["s007-assistant"].origin == "assistant" and "Congratulations" in ev["s007-assistant"].text
    assert "Larkspur" not in ev["s007-assistant"].text


def test_batches_are_in_date_order_and_under_the_token_limit():
    many = [S(i, f"2026-03-{i + 1:02d}", ("user", "x" * 400)) for i in range(5)]   # ~100 tokens each
    got = pl.batches(list(reversed(many)), max_tokens=250)
    assert [[s.date for s in bt] for bt in got] == [["2026-03-01", "2026-03-02"], ["2026-03-03", "2026-03-04"], ["2026-03-05"]]
    # a session bigger than the limit still gets a batch of its own
    assert len(pl.batches([S(9, "2026-03-09", ("user", "y" * 4000))], max_tokens=10)) == 1


def test_profile_from_sessions_chains_b_passes_and_maps_memory_files_to_topics(tmp_path):
    first = [{"op": "add", "file": "memory/pets.md", "new": "- Dog: Pepper (2026-02-01)",
              "citations": [{"evidence": "s001-user", "quote": "My dog is called Pepper"}]}]
    second = [{"op": "add", "file": "memory/home.md", "new": "- Home town: Larkspur (2026-02-03)",
               "citations": [{"evidence": "s002-user", "quote": "I moved to Larkspur"}]}]
    llm = FakeLLM([reply(first), reply(second)])
    prof = pl.profile_from_sessions(SESSIONS, llm, "m", tmp_path / "w", max_evidence_tokens=10)
    assert (prof / "topics" / "pets.md").read_text().strip() == "- Dog: Pepper (2026-02-01)"
    assert "Larkspur" in (prof / "topics" / "home.md").read_text()
    assert not (prof / "memory").exists()
    # the second compile sees the first pass's line and only its own evidence
    assert "- Dog: Pepper" in llm.calls[1]["user"] and "s001-user" not in llm.calls[1]["user"]
    assert "Today's date: 2026-02-03" in llm.calls[1]["user"]
    log = [json.loads(x) for x in (tmp_path / "w" / "compile.jsonl").read_text().splitlines()]
    assert [(r["batch"], r["outcome"], r["applied"], r["as_of"]) for r in log] == [
        (1, "ok", 1, "2026-02-01"), (2, "ok", 1, "2026-02-03")]
    assert log[0]["input_tokens"] == 100 and log[0]["output_tokens"] == 20


def test_profile_from_sessions_resumes_finished_batches(tmp_path):
    ok = [{"op": "add", "file": "memory/pets.md", "new": "- Dog: Pepper (2026-02-01)",
           "citations": [{"evidence": "s001-user", "quote": "My dog is called Pepper"}]}]
    pl.profile_from_sessions(SESSIONS[1:], FakeLLM([reply(ok)]), "m", tmp_path / "w")
    again = pl.profile_from_sessions(SESSIONS[1:], FakeLLM([]), "m", tmp_path / "w")   # no call needed
    assert "Pepper" in (again / "topics" / "pets.md").read_text()


def test_a_failed_compile_keeps_the_previous_store_and_is_logged(tmp_path):
    prof = pl.profile_from_sessions(SESSIONS[1:], FakeLLM([Reply("not json", "end_turn", 5, 5)]), "m", tmp_path / "w")
    assert list(prof.rglob("*.md")) == []
    row = json.loads((tmp_path / "w" / "compile.jsonl").read_text())
    assert row["outcome"] == "compile_failed"


def _adds(n):
    return [{"op": "add", "file": "memory/facts.md", "new": f"- Fact {i}: Value{i}",
             "citations": [{"evidence": "e1", "quote": f"Value{i}"}]} for i in range(n)]


def test_b_cap_floor_is_a_parameter_and_defaults_to_the_deployed_cap(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    ev = tmp_path / "ev"
    ev.mkdir()
    (ev / "e1.md").write_text("origin: user-said\ndate: 2026-01-01\n\n" + " ".join(f"Value{i}" for i in range(8)) + "\n")
    b.apply(src, tmp_path / "o1", FakeLLM([reply(_adds(8))]), "m", "2026-01-01", ev)
    assert len((tmp_path / "o1" / "memory/facts.md").read_text().splitlines()) == 5
    b.apply(src, tmp_path / "o2", FakeLLM([reply(_adds(8))]), "m", "2026-01-01", ev, cap_floor=100)
    assert len((tmp_path / "o2" / "memory/facts.md").read_text().splitlines()) == 8


def test_profile_log_counts_what_the_deployed_cap_would_have_held(tmp_path):
    sess = [S(1, "2026-01-01", ("user", " ".join(f"Value{i}" for i in range(8))))]
    adds = [{**c, "citations": [{"evidence": "s001-user", "quote": c["citations"][0]["quote"]}]} for c in _adds(8)]
    pl.profile_from_sessions(sess, FakeLLM([reply(adds)]), "m", tmp_path / "w", cap_floor=1000)
    row = json.loads((tmp_path / "w" / "compile.jsonl").read_text())
    assert row["applied"] == 8 and row["deployed_cap"] == 5 and row["over_deployed_cap"] == 3


def test_render_history_holds_every_turn_in_date_order():
    text = pl.render_history(SESSIONS)
    assert text.index("Pepper is a lovely") < text.index("Larkspur") and "2026-02-01" in text


def test_raw_retrieval_ranks_matching_lines_first_within_the_budget():
    filler = [S(10 + i, "2026-01-10", ("user", f"Unrelated chatter number {i} about weather and clouds.")) for i in range(50)]
    ctx = pl.raw_retrieval(SESSIONS + filler, "What is my dog called?", budget_chars=300)
    assert len(ctx) <= 300 + len(pl.RAW_HEADER) + 1
    assert ctx.startswith(pl.RAW_HEADER) and "My dog is called Pepper" in ctx.splitlines()[1]


def test_profile_contexts(tmp_path):
    prof = tmp_path / "p"
    (prof / "topics").mkdir(parents=True)
    (prof / "profile.md").write_text("# Profile\n- Name: Robin\n")
    (prof / "topics" / "pets.md").write_text("- Dog called Pepper, a terrier (2026-02-01)\n- Cat called Miso (2026-02-01)\n")
    (prof / "topics" / "home.md").write_text("- Lives in Larkspur (2026-02-03)\n")
    full = pl.profile_full(prof)
    assert "Pepper" in full and "Larkspur" in full and "Robin" in full and "# Profile" not in full
    hook = pl.profile_hook(prof, "Which terrier breed is my dog Pepper?")
    assert "- Name: Robin" in hook and HEADER in hook and "Pepper" in hook and "Larkspur" not in hook
    assert pl.profile_hook(prof, "Tell me a joke") == "- Name: Robin"


def test_answer_is_one_call_with_the_context_in_the_system_prompt():
    llm = FakeLLM([Reply("Pepper.", "end_turn", 42, 3)])
    r = pl.answer("What is my dog called?", "- Dog: Pepper", llm, "m", instructions="Be brief.", max_tokens=50)
    assert r.text == "Pepper." and len(llm.calls) == 1
    assert llm.calls[0]["system"] == "Be brief.\n\n- Dog: Pepper" and llm.calls[0]["user"] == "What is my dog called?"
    none =FakeLLM([Reply("x", "end_turn", 1, 1)])
    pl.answer("q", "", none, "m", instructions="Be brief.")
    assert none.calls[0]["system"] == "Be brief."


def test_profile_hook_carries_standing_lines_like_the_index_does(tmp_path):
    from um.expand import line_key
    prof = tmp_path / "p"
    (prof / "topics").mkdir(parents=True)
    (prof / "profile.md").write_text("# Profile\n- Name: Robin\n")
    (prof / "topics" / "food.md").write_text("- Allergic to shellfish (2026-02-01)\n- Tried oat milk once\n")
    (prof / ".um").mkdir()
    (prof / ".um" / "standing.json").write_text(json.dumps({line_key("- Allergic to shellfish (2026-02-01)"): "standing"}))
    ctx = pl.profile_hook(prof, "Tell me a joke")
    assert "Allergic to shellfish" in ctx and "oat milk" not in ctx


def test_enrich_writes_expansions_and_labels_once_and_survives_a_rebuilt_view(tmp_path):
    store = tmp_path / "store"
    (store / "memory").mkdir(parents=True)
    (store / "memory" / "food.md").write_text("- Allergic to shellfish\n")
    view = pl.profile_view(store, tmp_path / "view")
    llm = FakeLLM([Reply(json.dumps({"1": ["seafood"]}), "end_turn", 1, 1),
                   Reply(json.dumps({"1": "standing"}), "end_turn", 1, 1)])
    pl.enrich(view, llm, "m")
    view = pl.profile_view(store, tmp_path / "view")
    pl.enrich(view, FakeLLM([]), "m")
    assert (view / ".um" / "standing.json").exists() and (view / ".um" / "expansions.json").exists()
