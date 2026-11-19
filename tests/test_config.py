import json
import subprocess
from pathlib import Path

import pytest

from um import cli
from um.config import config_path, llm_mode, load_config, profile_path


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("UM_CONFIG", str(tmp_path / "cfg" / "config.json"))
    monkeypatch.delenv("UM_PROFILE", raising=False)
    monkeypatch.delenv("UM_LLM", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def test_defaults_without_a_config_file():
    assert load_config() == {}
    assert profile_path() == Path.home() / "claude-profile"
    assert llm_mode() == "subscription"


def test_order_is_explicit_then_env_then_config(tmp_path, monkeypatch):
    config_path().parent.mkdir(parents=True)
    config_path().write_text(json.dumps({"profile": str(tmp_path / "from-config"), "llm": "hybrid"}))
    assert profile_path() == tmp_path / "from-config" and llm_mode() == "hybrid"
    monkeypatch.setenv("UM_PROFILE", str(tmp_path / "from-env"))
    monkeypatch.setenv("UM_LLM", "api")
    assert profile_path() == tmp_path / "from-env" and llm_mode() == "api"
    assert profile_path(tmp_path / "explicit") == tmp_path / "explicit"


def test_a_broken_config_falls_back_to_defaults():
    config_path().parent.mkdir(parents=True)
    config_path().write_text("{not json")
    assert load_config() == {} and llm_mode() == "subscription"


def test_init_creates_a_profile_repo_and_config_and_prints_the_import_line(tmp_path, capsys):
    target = tmp_path / "me"
    cli.main(["init", "--profile", str(target)])
    out = capsys.readouterr().out
    assert (target / "profile.md").read_text().startswith("---\nname: profile\n")
    assert all((target / d).is_dir() for d in ("areas", "topics", "people"))
    assert (target / ".git").is_dir() and (target / "claude-code.md").exists()
    assert subprocess.run(["git", "-C", str(target), "log", "--oneline"], capture_output=True, text=True).stdout.strip()
    assert json.loads(config_path().read_text())["profile"] == str(target)
    assert f"@{target / 'claude-code.md'}" in out


def test_init_keeps_an_existing_profile(tmp_path, capsys):
    target = tmp_path / "me"
    target.mkdir()
    (target / "profile.md").write_text("---\nname: profile\n---\n- [stated] Name: Sam\n")
    cli.main(["init", "--profile", str(target)])
    assert "Name: Sam" in (target / "profile.md").read_text()


def test_init_refuses_a_non_empty_folder_that_is_not_a_profile(tmp_path):
    target = tmp_path / "busy"
    target.mkdir()
    (target / "notes.txt").write_text("mine")
    with pytest.raises(SystemExit):
        cli.main(["init", "--profile", str(target)])
    assert not config_path().exists()


def test_commands_use_the_configured_profile(tmp_path, capsys):
    target = tmp_path / "me"
    cli.main(["init", "--profile", str(target)])
    capsys.readouterr()
    cli.main(["answer", "--text", "I moved to Lisbon"])
    assert list((target / ".answers").glob("*.md"))
