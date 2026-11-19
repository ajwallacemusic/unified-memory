from um.compile import Change
from um.profile import Lineage, apply_each


def store(tmp_path, body):
    src = tmp_path / "src"
    (src / "areas").mkdir(parents=True)
    (src / "areas" / "trip.md").write_text(body)
    return src


def test_a_replace_keeps_the_tag_of_the_line_it_replaces(tmp_path):
    src = store(tmp_path, "# Trip\n- [stated] Going to Lisbon in May\n")
    out = tmp_path / "out"
    c = Change("replace", "areas/trip.md", "- [stated] Going to Lisbon in May", "- Went to Lisbon in May (2026-06-01)", ["e1"], None, None)
    assert apply_each(src, out, [c], {0: "user-said"}, "2026-06-01") == [True]
    assert "- [stated] Went to Lisbon in May (2026-06-01)\n" in (out / "areas" / "trip.md").read_text()
    assert Lineage(out).origin_of("areas/trip.md", "- [stated] Went to Lisbon in May (2026-06-01)") == "user-said"


def test_an_add_takes_the_tag_every_line_in_the_file_carries(tmp_path):
    src = store(tmp_path, "# Trip\n- [stated] Going to Lisbon\n- [stated] Staying a week\n")
    out = tmp_path / "out"
    apply_each(src, out, [Change("add", "areas/trip.md", None, "- Flying TAP", ["e1"], None, None)], {0: "user-said"}, "2026-06-01")
    assert (out / "areas" / "trip.md").read_text().endswith("- [stated] Flying TAP\n")


def test_untagged_files_and_already_tagged_lines_are_left_alone(tmp_path):
    src = store(tmp_path, "# Trip\n- Going to Lisbon\n")
    out = tmp_path / "out"
    apply_each(src, out, [Change("add", "areas/trip.md", None, "- Flying TAP", ["e1"], None, None),
                          Change("replace", "areas/trip.md", "- Going to Lisbon", "- [stated] Going to Porto", ["e1"], None, None)],
               {0: "user-said", 1: "user-said"}, "2026-06-01")
    assert (out / "areas" / "trip.md").read_text() == "# Trip\n- [stated] Going to Porto\n- Flying TAP\n"
