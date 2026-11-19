from um.bench.longmemeval import Session, Turn
from um.llm import FakeLLM, Reply
from um.writer import write_memory


def session(n, chars=30_000):
    return Session(f"s{n}", f"2023/05/{n:02d} (Mon) 10:00", (Turn("user", "x" * chars),))


def test_sessions_are_fed_in_chunks_under_the_token_limit(tmp_path):
    llm = FakeLLM([Reply("ok", "end_turn", 1, 1)] * 3)
    outcomes = write_memory([session(n) for n in range(1, 7)], tmp_path, llm, "m", chunk_tokens=20_000)
    assert outcomes == ["ok", "ok", "ok"] and len(llm.calls) == 3
    for call, days in zip(llm.calls, (("05/01", "05/02"), ("05/03", "05/04"), ("05/05", "05/06"))):
        assert call["kind"] == "run_tools" and all(f"2023/{d}" in call["user"] for d in days)
    assert "2023/05/03" not in llm.calls[0]["user"]


def test_an_oversized_session_gets_its_own_chunk(tmp_path):
    llm = FakeLLM([Reply("ok", "end_turn", 1, 1)] * 3)
    write_memory([session(1, 10_000), session(2, 200_000), session(3, 10_000)], tmp_path, llm, "m", chunk_tokens=20_000)
    assert len(llm.calls) == 3


def test_writer_gets_a_writable_store_and_reports_non_ok_outcomes(tmp_path):
    llm = FakeLLM([{"tool": "write", "args": {"path": "MEMORY.md", "content": "- [Work](work.md): job"}},
                   Reply("", "refusal", 1, 0)])
    assert write_memory([session(1, 100)], tmp_path, llm, "m") == ["refusal"]
    assert (tmp_path / "MEMORY.md").exists()


def test_the_writer_prompt_can_be_chosen(tmp_path):
    llm = FakeLLM([Reply("ok", "end_turn", 1, 1), Reply("ok", "end_turn", 1, 1)])
    write_memory([session(1, 100)], tmp_path, llm, "m")
    write_memory([session(1, 100)], tmp_path, llm, "m", prompt="writer_absorb.md")
    assert "what tools and connectors report" not in llm.calls[0]["system"]
    assert "what tools and connectors report" in llm.calls[1]["system"]
