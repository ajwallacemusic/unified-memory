import json

from um.synth.report import build_report


def week(root, user, arm, w, rows, questions=0, outcome="ok", usd=0.01, pass_record=None):
    d = root / user / arm / f"week-{w}"
    (d / "out").mkdir(parents=True)
    (d / ".done").write_text(json.dumps({"rows": rows, "pass": {"user": user, "arm": arm, "week": w, "arm_outcome": outcome,
                                                                 "questions_asked": questions, "input_tokens": 100,
                                                                 "output_tokens": 10, "usd": usd, "writer_outcomes": ["ok"]}}))
    if pass_record:
        (d / "out" / ".pass.json").write_text(json.dumps(pass_record))


def rows(user, arm, w, labels):
    cats = ["updated", "old-valid", "attacked", "system"]
    return [{"user": user, "arm": arm, "week": w, "probe_id": f"{user}-w{w}-{n}", "category": cats[n % 4], "label": lab, "answer": ""}
            for n, lab in enumerate(labels)]


def test_report_has_every_metric_arm_comparison_and_the_caveat(tmp_path):
    for arm, labels in (("z", ["stale", "missing", "planted", "stale"]), ("a0", ["current", "missing", "planted", "stale"]),
                        ("a", ["current", "current", "planted", "current"]), ("b", ["current", "current", "current", "stale"])):
        week(tmp_path, "user01", arm, 1, rows("user01", arm, 1, labels), questions=2 if arm == "b" else 0,
             outcome="compile_failed" if arm == "b" else "ok",
             pass_record={"changes": [{"decision": "hold", "reason": "tool output cannot override an existing line"},
                                      {"decision": "reject", "reason": "quote not found in e001"}]} if arm == "b" else None)
    text = build_report(tmp_path)
    for needle in ("stale served", "false stale", "planted accepted", "combined error", "| z |", "| a0 |", "| a |", "| b |",
                   "b minus a", "a minus a0", "b minus z", "templated", "Questions asked per week", "compile_failed",
                   "tool output cannot override", "quote not found", "Not run", "oracle", "origin header"):
        assert needle in text, needle
    assert "100% (1/1" in text   # z's planted acceptance


def test_report_paired_table_has_stale_served_and_nohook_arm(tmp_path):
    for arm, labels in (("z", ["stale", "current", "planted", "stale"]), ("b-nohook", ["current", "current", "planted", "current"])):
        week(tmp_path, "user01", arm, 1, rows("user01", arm, 1, labels))
    text = build_report(tmp_path)
    assert "| b-nohook |" in text
    assert any(line.startswith("| b-nohook minus z | stale served |") for line in text.splitlines())


def test_report_has_erase_row(tmp_path):
    r = [{"user": "user01", "arm": "z", "week": 4, "probe_id": "p1", "category": "erased", "label": "leaked", "answer": "",
          "file_leaks": ["memory/work.md"]},
         {"user": "user01", "arm": "z", "week": 4, "probe_id": "p2", "category": "erased", "label": "clean", "answer": "",
          "file_leaks": ["memory/work.md"]}]
    week(tmp_path, "user01", "z", 4, r)
    text = build_report(tmp_path)
    assert "erase leaks" in text and "50% (1/2" in text
    assert "Files still holding an erased value" in text and "| z | 1 |" in text


def test_report_rebuilds_from_a_published_rows_file_without_week_folders(tmp_path):
    rs = rows("user01", "a", 1, ["current", "current"]) + rows("user01", "z", 1, ["current", "current"])
    (tmp_path / "rows.jsonl").write_text("\n".join(json.dumps(r) for r in rs) + "\n")
    text = build_report(tmp_path)
    assert "4 scored probe answers" in text and "| a |" in text and "| z |" in text
    assert "Per-pass records (outcomes, tokens, dollars, questions) are not published" in text


def test_pass_records_in_a_published_rows_file_fill_the_passes_table(tmp_path):
    rs = rows("user01", "a", 1, ["current"])
    p = {"pass": {"user": "user01", "arm": "a", "week": 1, "arm_outcome": "ok", "questions_asked": 0,
                  "input_tokens": 100, "output_tokens": 10, "usd": 0.5, "writer_outcomes": ["ok"]}}
    (tmp_path / "rows.jsonl").write_text("\n".join(json.dumps(r) for r in rs + [p]) + "\n")
    text = build_report(tmp_path)
    assert "1 scored probe answers" in text and "$0.50" in text
