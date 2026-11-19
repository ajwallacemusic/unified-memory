import json
import os
import stat

import pytest

from um.bench.cc_run import CONDITIONS, make_workdir, run_probe


@pytest.fixture
def profile(tmp_path):
    p = tmp_path / "src-profile"
    (p / "topics").mkdir(parents=True)
    (p / "profile.md").write_text("---\nname: profile\n---\n- [stated] Name: Sam\n")
    (p / "topics" / "music.md").write_text("---\nname: music\ndescription: Sam's instruments\n---\n"
                                           "- [stated] Plays a mandolin nicknamed KESTREL-17\n")
    return p


def test_none_has_no_profile_at_all(profile, tmp_path):
    w = make_workdir("none", profile, tmp_path / "runs")
    assert not (w / "CLAUDE.md").exists() and not (w / ".claude" / "settings.json").exists()
    assert not any("KESTREL" in f.read_text() for f in w.rglob("*") if f.is_file())


def test_index_inlines_profile_md_and_lists_other_files(profile, tmp_path):
    w = make_workdir("index", profile, tmp_path / "runs")
    text = (w / "CLAUDE.md").read_text()
    assert "Name: Sam" in text and "music.md — Sam's instruments" in text and "KESTREL" not in text
    assert not (w / ".claude" / "settings.json").exists()


def test_full_inlines_every_file(profile, tmp_path):
    text = (make_workdir("full", profile, tmp_path / "runs") / "CLAUDE.md").read_text()
    assert "Name: Sam" in text and "KESTREL-17" in text and "topics/music.md" in text


def test_hook_is_the_index_plus_a_prompt_hook_on_the_copied_profile(profile, tmp_path):
    w = make_workdir("hook", profile, tmp_path / "runs")
    assert "KESTREL" not in (w / "CLAUDE.md").read_text()
    hooks = json.loads((w / ".claude" / "settings.json").read_text())["hooks"]["UserPromptSubmit"]
    cmd = hooks[0]["hooks"][0]["command"]
    assert "um.hooks.profile_context" in cmd and "UM_PROFILE=" in cmd and str(profile) not in cmd


def test_workdirs_are_not_git_repos_and_conditions_are_known(profile, tmp_path):
    for c in CONDITIONS:
        assert not (make_workdir(c, profile, tmp_path / "runs") / ".git").exists()
    with pytest.raises(ValueError):
        make_workdir("bogus", profile, tmp_path / "runs")


def test_run_probe_isolates_the_session_and_parses_usage(profile, tmp_path):
    w = make_workdir("none", profile, tmp_path / "runs")
    fake = tmp_path / "claude"
    log = tmp_path / "argv.json"
    fake.write_text("#!/usr/bin/env python3\nimport json, os, sys\n"
                    f"json.dump({{'argv': sys.argv[1:], 'git': os.environ.get('GIT_CONFIG_GLOBAL'), 'cwd': os.getcwd(), 'stdin_tty_or_empty': sys.stdin.read() == ''}}, open({str(log)!r}, 'w'))\n"
                    "print(json.dumps({'result': 'KESTREL-17', 'usage': {'input_tokens': 3, "
                    "'cache_read_input_tokens': 100, 'cache_creation_input_tokens': 10, 'output_tokens': 7}}))\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    r = run_probe(w, "mandolin?", model="haiku", claude=str(fake))
    seen = json.loads(log.read_text())
    assert r["answer"] == "KESTREL-17" and r["input_tokens"] == 113 and r["output_tokens"] == 7 and r["error"] is None
    assert seen["git"] == os.devnull and os.path.realpath(seen["cwd"]) == os.path.realpath(w)
    a = seen["argv"]
    assert a[a.index("--setting-sources") + 1] == "project" and "--strict-mcp-config" in a
    assert a[a.index("--model") + 1] == "haiku" and a[:2] == ["-p", "mandolin?"]
    assert a[a.index("--tools") + 1] == "Read,Glob,Grep" and seen["stdin_tty_or_empty"]
    assert "--allowedTools" not in a  # a blanket allow let sessions read the whole disk; scope is cwd + profile


@pytest.mark.parametrize("cond,expect", [("none", False), ("full", False), ("index", True), ("hook", True)])
def test_only_index_and_hook_sessions_can_reach_the_profile_folder(profile, tmp_path, cond, expect):
    w = make_workdir(cond, profile, tmp_path / "runs")
    fake = tmp_path / "claude"
    log = tmp_path / "argv.json"
    fake.write_text(f"#!/usr/bin/env python3\nimport json, sys\njson.dump(sys.argv[1:], open({str(log)!r}, 'w'))\nprint('{{}}')\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    run_probe(w, "q", claude=str(fake))
    assert ("--add-dir" in json.loads(log.read_text())) is expect


def test_run_probe_reports_a_failure_instead_of_raising(profile, tmp_path):
    w = make_workdir("none", profile, tmp_path / "runs")
    r = run_probe(w, "q", claude=str(tmp_path / "missing-binary"))
    assert r["answer"] is None and r["error"]


def test_the_copied_profile_keeps_its_expansion_words_but_no_other_bookkeeping(profile, tmp_path):
    (profile / ".um").mkdir()
    (profile / ".um" / "expansions.json").write_text("{}")
    (profile / ".um" / "build.json").write_text("{}")
    make_workdir("hook", profile, tmp_path / "runs")
    assert (tmp_path / "runs" / "profile" / ".um" / "expansions.json").exists()
    assert not (tmp_path / "runs" / "profile" / ".um" / "build.json").exists()


def test_only_standing_and_hook_carry_standing_preferences(profile, tmp_path):
    import json as _j
    from um.expand import line_key
    (profile / ".um").mkdir()
    (profile / ".um" / "standing.json").write_text(_j.dumps(
        {line_key("- [stated] Plays a mandolin nicknamed KESTREL-17"): "standing"}))
    for c, expect in (("index", False), ("standing", True), ("hook", True)):
        text = (make_workdir(c, profile, tmp_path / "runs") / "CLAUDE.md").read_text()
        assert ("KESTREL-17" in text) is expect, c


def test_a_project_claude_md_sits_beside_the_profile_in_every_setup(profile, tmp_path):
    proj = tmp_path / "proj.md"
    proj.write_text("# routekit\nRun make test.\n")
    for c in CONDITIONS:
        text = (make_workdir(c, profile, tmp_path / "runs", project_md=proj) / "CLAUDE.md").read_text()
        assert "Run make test." in text
        assert ("Name: Sam" in text) is (c != "none")
