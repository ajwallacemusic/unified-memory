from pathlib import Path

import pytest

from um.bench.longmemeval import SAMPLE_COUNTS, SEED, load, materialize, sample

TINY = Path(__file__).parent / "data" / "lme_tiny.json"


def test_load_orders_sessions_by_date_and_keeps_turns():
    items = {i.qid: i for i in load(TINY)}
    assert len(items) == 3
    ku = items["ku01"]
    assert [s.id for s in ku.sessions] == ["s_a", "s_c", "s_b"]
    assert ku.sessions[0].turns[0].role == "user" and "Oakfield" in ku.sessions[0].turns[0].content
    assert ku.question_date == "2023/06/01 (Thu) 09:00"


def test_abstention_items_get_their_own_type_and_answers_are_text():
    items = {i.qid: i for i in load(TINY)}
    assert items["ms01_abs"].is_abstention and items["ms01_abs"].qtype == "abstention"
    assert not items["ku01"].is_abstention and items["ku01"].qtype == "knowledge-update"
    assert items["tr01"].answer == "14"


def test_sample_is_deterministic_and_sorted():
    items = load(TINY)
    counts = {"knowledge-update": 1, "abstention": 1}
    a, b = sample(items, counts, seed=7), sample(items, counts, seed=7)
    assert [i.qid for i in a] == [i.qid for i in b] == ["ku01", "ms01_abs"]


def test_sample_refuses_when_a_type_is_short():
    with pytest.raises(ValueError):
        sample(load(TINY), {"knowledge-update": 2}, seed=7)


def test_default_sample_is_one_hundred():
    assert sum(SAMPLE_COUNTS.values()) == 100 and SEED == 20261110


def test_materialize_writes_one_dated_file_per_session_in_order(tmp_path):
    ku = next(i for i in load(TINY) if i.qid == "ku01")
    materialize(ku, tmp_path)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert len(names) == 3 and names[0].startswith("001_2023-03-02") and names[2].startswith("003_2023-05-20")
    first = (tmp_path / names[0]).read_text()
    assert "2023/03/02" in first and "user: I work at Oakfield." in first and "assistant: Noted." in first
