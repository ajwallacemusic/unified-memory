import pytest

from conftest import tree_hash
from um.profile import ORIGIN_RANK, Change, Lineage, apply_changes, lines_of


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "stores"
    (r / "memory").mkdir(parents=True)
    (r / "memory" / "work.md").write_text("# Work\n\n- Works at Oakfield\n- Team: Larchgate\n")
    (r / "memory" / "home.md").write_text("- Lives in Aldermoor\n- Lives in Aldermoor\n")
    return r


def test_origin_ranks():
    assert ORIGIN_RANK["user-said"] > ORIGIN_RANK["assistant"] == ORIGIN_RANK["legacy"] > ORIGIN_RANK["tool-output"]


def test_lines_of_lists_every_non_empty_line_with_its_file(root):
    assert ("memory/work.md", "- Works at Oakfield") in lines_of(root)
    assert len(lines_of(root)) == 5


def test_replace_changes_one_line_and_never_touches_the_source(tmp_path, root):
    before = tree_hash(root)
    c = Change("replace", "memory/work.md", "- Works at Oakfield", "- Works at Brightline", [{"evidence": "u1", "quote": "q"}])
    apply_changes(root, tmp_path / "out", [c], {0: "user-said"}, "2026-01-08")
    assert tree_hash(root) == before
    assert (tmp_path / "out/memory/work.md").read_text() == "# Work\n\n- Works at Brightline\n- Team: Larchgate\n"


def test_add_and_remove(tmp_path, root):
    changes = [Change("add", "memory/tools.md", None, "- Editor: Quillforge", [{"evidence": "u2", "quote": "q"}]),
               Change("remove", "memory/work.md", "- Team: Larchgate", None, [{"evidence": "u3", "quote": "q"}]),
               Change("add", "memory/work.md", None, "- Manager: Wrenholt", [{"evidence": "u4", "quote": "q"}])]
    apply_changes(root, tmp_path / "out", changes, {0: "user-said", 1: "user-said", 2: "assistant"}, "2026-01-08")
    assert (tmp_path / "out/memory/tools.md").read_text() == "- Editor: Quillforge\n"
    assert (tmp_path / "out/memory/work.md").read_text() == "# Work\n\n- Works at Oakfield\n- Manager: Wrenholt\n"


def test_an_old_line_that_is_missing_or_ambiguous_is_an_error(tmp_path, root):
    for old, file in (("- Works at Nowhere", "memory/work.md"), ("- Lives in Aldermoor", "memory/home.md")):
        with pytest.raises(ValueError):
            apply_changes(root, tmp_path / "o", [Change("replace", file, old, "- x", [])], {0: "user-said"}, "2026-01-08")


def test_lineage_records_new_lines_and_calls_everything_else_legacy(tmp_path, root):
    c = Change("replace", "memory/work.md", "- Works at Oakfield", "- Works at Brightline", [{"evidence": "u1", "quote": "q"}])
    apply_changes(root, tmp_path / "out", [c], {0: "user-said"}, "2026-01-08")
    lin = Lineage(tmp_path / "out")
    assert lin.origin_of("memory/work.md", "- Works at Brightline") == "user-said"
    assert lin.origin_of("memory/work.md", "- Team: Larchgate") == "legacy"
    assert ".lineage.jsonl" not in {f for f, _ in lines_of(tmp_path / "out")}


def test_lineage_is_carried_into_the_next_version(tmp_path, root):
    c = Change("add", "memory/work.md", None, "- Manager: Wrenholt", [{"evidence": "u4", "quote": "q"}])
    apply_changes(root, tmp_path / "v1", [c], {0: "user-said"}, "2026-01-08")
    apply_changes(tmp_path / "v1", tmp_path / "v2", [], {}, "2026-01-15")
    assert Lineage(tmp_path / "v2").origin_of("memory/work.md", "- Manager: Wrenholt") == "user-said"


def test_every_evidence_origin_has_a_rank_and_file_edits_never_carry_user_authority():
    from um.evidence import ORIGINS
    assert set(ORIGINS) <= set(ORIGIN_RANK)
    assert ORIGIN_RANK["file-edit"] < ORIGIN_RANK["user-said"] and ORIGIN_RANK["file-edit"] <= ORIGIN_RANK["tool-output"]
    assert ORIGIN_RANK["probe"] > ORIGIN_RANK["tool-output"]
