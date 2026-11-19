"""MemoryAgentBench FactConsolidation adapter, on fictional facts."""
import json

import pytest

from um.bench.public import mab

CONTEXT = ("Here is a list of facts:\n"
           "0. Ondrel Vask plays the position of goalkeeper.\n"
           "1. The capital of Merovia is Tallgrave.\n"
           "2. Ondrel Vask is a citizen of Merovia.\n"
           "3. Ondrel Vask plays the position of striker.\n"
           "4. The capital of Merovia is Dunmere.\n")


@pytest.fixture
def path(tmp_path):
    rows = [{"context": CONTEXT, "questions": ["Which position does Ondrel Vask play?", "What is the capital of Merovia?"],
             "answers": [["striker"], ["Dunmere", "Dunmere City"]],
             "metadata": {"source": "factconsolidation_sh_6k", "qa_pair_ids": ["fc_no0", "fc_no1"]}},
            {"context": "Here is a list of facts:\n0. x.\n", "questions": ["q"], "answers": [["a"]],
             "metadata": {"source": "factconsolidation_mh_6k", "qa_pair_ids": ["mh_no0"]}}]
    p = tmp_path / "cr.json"
    p.write_text(json.dumps(rows))
    return p


def test_load_one_source(path):
    ctx = mab.load(path, "factconsolidation_sh_6k")
    assert [f for f in ctx.facts][:2] == [(0, "Ondrel Vask plays the position of goalkeeper."),
                                          (1, "The capital of Merovia is Tallgrave.")]
    assert [(q.id, q.answers) for q in ctx.items] == [("fc_no0", ["striker"]), ("fc_no1", ["Dunmere", "Dunmere City"])]
    with pytest.raises(KeyError):
        mab.load(path, "factconsolidation_sh_32k")


def test_sessions_chunk_facts_in_serial_order_on_rising_dates(path):
    ss = mab.sessions(mab.load(path, "factconsolidation_sh_6k"), per_session=2)
    assert [s.date for s in ss] == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert ss[0].turns[0][0] == "user" and "0. Ondrel Vask plays the position of goalkeeper." in ss[0].turns[0][1]
    assert "4. The capital of Merovia is Dunmere." in ss[2].turns[0][1]


def test_official_metric_is_substring_exact_match_over_raw_and_parsed_output():
    assert mab.sub_em("Answer: The striker.", [["striker"]]) is True
    assert mab.sub_em("goalkeeper", ["striker"]) is False
    assert mab.sub_em("Dunmere", ["Dunmere City", "Dunmere"]) is True
    assert mab.normalize_answer("The  Dunmère, City!") == "dunmère city"


def test_last_write_picks_the_newest_of_the_best_matching_facts(path):
    ctx = mab.load(path, "factconsolidation_sh_6k")
    assert mab.last_write(ctx, "Which position does Ondrel Vask play?") == "3. Ondrel Vask plays the position of striker."
    assert mab.last_write(ctx, "What is the capital of Merovia?") == "4. The capital of Merovia is Dunmere."
    assert mab.last_write(ctx, "Who painted the ceiling?") == ""


def test_query_uses_the_official_template():
    q = mab.query("What is the capital of Merovia?")
    assert q.startswith("Pretend you are a knowledge management system.")
    assert q.endswith("Based on the provided Knowledge Pool, What is the capital of Merovia? \nAnswer:")
