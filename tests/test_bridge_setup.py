import json
from pathlib import Path

from um import cli

ROOT = Path(__file__).resolve().parents[1]


def test_the_shipped_task_prompt_is_a_template_with_no_personal_path():
    text = (ROOT / "bridge" / "task-prompt.md").read_text()
    assert "{{PROFILE}}" in text and "{{MOUNT}}" in text and "develop/claude-profile" not in text


def test_bridge_prompt_fills_in_the_profile_folder(tmp_path, capsys):
    target = tmp_path / "my profile"
    cli.main(["init", "--profile", str(target)])
    capsys.readouterr()
    cli.main(["bridge-prompt"])
    out = capsys.readouterr().out
    assert f"`{target.resolve()}`" in out and "$HOME/mnt/my profile" in out and "{{" not in out


def test_bridge_review_marks_the_last_run(tmp_path, capsys):
    target = tmp_path / "p"
    cli.main(["init", "--profile", str(target)])
    log = target / "bridge-log.jsonl"
    log.write_text(json.dumps({"mode": "propose-only", "proposed": 3, "rejected": 0, "reviewed": False}) + "\n" +
                   json.dumps({"mode": "propose-only", "proposed": 2, "rejected": 0, "reviewed": False}) + "\n")
    cli.main(["bridge-review", "--rejected", "1"])
    rows = [json.loads(x) for x in log.read_text().splitlines()]
    assert rows[0]["reviewed"] is False and rows[1]["reviewed"] is True and rows[1]["rejected"] == 1
    assert log.read_text().endswith("}\n") and "\n\n" not in log.read_text()


def test_bridge_review_with_no_runs_says_so(tmp_path):
    target = tmp_path / "p"
    cli.main(["init", "--profile", str(target)])
    try:
        cli.main(["bridge-review"])
        raise AssertionError("expected SystemExit")
    except SystemExit as e:
        assert "no bridge run" in str(e)


def test_prepare_uses_the_configured_profile(tmp_path, capsys):
    from um.bridge import prepare
    target = tmp_path / "p"
    cli.main(["init", "--profile", str(target)])
    capsys.readouterr()
    prepare.main(["--mode", "propose-only"])
    assert (target / "outbox" / "manifest.json").exists()
