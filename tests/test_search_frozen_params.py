import json
from pathlib import Path

from um.search.model import CHUNK_CHARS, LEAD_CHARS
from um.search.tools import DEFAULT_PARAMS

FROZEN = json.loads((Path(__file__).resolve().parents[1] / "results/search-gate/2026-11-tune/params.json").read_text())


def test_shipped_defaults_are_the_parameters_frozen_on_the_dev_split():
    assert (CHUNK_CHARS, LEAD_CHARS) == (FROZEN["chunk_chars"], FROZEN["lead_chars"])
    assert DEFAULT_PARAMS == {"per_session": FROZEN["per_session"], "half_life_days": FROZEN["half_life_days"]}
