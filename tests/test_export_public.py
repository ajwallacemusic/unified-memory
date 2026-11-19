import importlib.util
import subprocess
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "export_public", Path(__file__).resolve().parents[1] / "scripts" / "export_public.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
ExportError, export, find_terms = _mod.ExportError, _mod.export, _mod.find_terms


@pytest.fixture
def src(tmp_path):
    s = tmp_path / "src"
    for rel, text in {"um/a.py": "x = 1\n", "um/hooks/b.py": "y = 2\n", "tests/test_a.py": "def test(): pass\n",
                      "docs/research/notes.md": "notes\n", "docs/public/README.md": "# Hello\n",
                      "data/private/x.md": "secret\n", "results/spend.jsonl": "{}\n", "bench/recall/q.jsonl": "{}\n",
                      "plugin_src/x.md": "p\n"}.items():
        p = s / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    subprocess.run(["git", "init", "-q", str(s)], check=True)
    subprocess.run(["git", "-C", str(s), "add", "-A", "-f"], check=True)
    return s


ALLOW = ["um/", "tests/", "bench/", "plugin_src/", "docs/public/", "docs/research/"]


def test_copies_only_allowlisted_tracked_files_and_maps_public_docs(src, tmp_path):
    out = tmp_path / "out"
    files = export(src, out, allow=ALLOW, deny_terms=[])
    assert "um/a.py" in files and "bench/recall/q.jsonl" in files
    assert "README.md" in files and (out / "README.md").read_text() == "# Hello\n"
    assert not (out / "data").exists() and not (out / "results" / "spend.jsonl").exists()


def test_never_copies_private_or_research_paths_even_if_allowed(src, tmp_path):
    files = export(src, tmp_path / "out", allow=ALLOW + ["data/"], deny_terms=[])
    assert not any(f.startswith(("data/", "docs/research/")) for f in files)


def test_refuses_on_a_denylisted_term_naming_file_and_line(src, tmp_path):
    (src / "um" / "a.py").write_text("x = 1\nhome = '/Users/Quill/thing'\n")
    with pytest.raises(ExportError) as e:
        export(src, tmp_path / "out", allow=ALLOW, deny_terms=["quill"])
    assert "um/a.py:2" in str(e.value) and "quill" in str(e.value).lower()
    assert not (tmp_path / "out").exists()


def test_term_matching_is_whole_word_and_case_insensitive_and_sees_json_escapes():
    text = 'broakfielder\n{"t": "Works at OAKFIELD"}\n{"u": "caf\\u00e9 Quill\\u0027s"}\n'
    hits = find_terms(text, ["oakfield", "quill's", "café"])
    assert [(n, t) for n, t in hits] == [(2, "oakfield"), (3, "quill's"), (3, "café")]


def test_marketplace_file_lands_where_claude_code_looks(src, tmp_path):
    (src / "marketplace").mkdir()
    (src / "marketplace" / "marketplace.json").write_text("{}\n")
    subprocess.run(["git", "-C", str(src), "add", "-A", "-f"], check=True)
    files = export(src, tmp_path / "out", allow=ALLOW + ["marketplace/"], deny_terms=[])
    assert ".claude-plugin/marketplace.json" in files


def test_a_reviewed_hit_can_be_exempted_for_one_file_only(src, tmp_path):
    (src / "um" / "a.py").write_text("car = 'Hyundai Quill'\n")
    (src / "um" / "hooks" / "b.py").write_text("x = 'Quill'\n")
    with pytest.raises(ExportError) as e:
        export(src, tmp_path / "out", allow=ALLOW, deny_terms=["quill"], exempt={("um/a.py", "quill")})
    assert "um/hooks/b.py" in str(e.value) and "um/a.py" not in str(e.value)


def test_tracked_files_the_public_gitignore_would_drop_are_left_out(src, tmp_path):
    (src / ".gitignore").write_text("results/**/week-*/\n")
    (src / "results" / "s" / "week-1").mkdir(parents=True)
    (src / "results" / "s" / "week-1" / "x.md").write_text("w\n")
    (src / "results" / "s" / "rows.jsonl").write_text("{}\n")
    subprocess.run(["git", "-C", str(src), "add", "-A", "-f"], check=True)
    files = export(src, tmp_path / "out", allow=ALLOW + ["results/s/"], deny_terms=[])
    assert "results/s/rows.jsonl" in files and "results/s/week-1/x.md" not in files


def test_the_plugin_copy_of_the_private_data_reader_is_never_exported(src, tmp_path):
    (src / "plugin" / "um").mkdir(parents=True)
    (src / "plugin" / "um" / "realdata.py").write_text("x\n")
    subprocess.run(["git", "-C", str(src), "add", "-A", "-f"], check=True)
    assert "plugin/um/realdata.py" not in export(src, tmp_path / "out", allow=ALLOW + ["plugin/"], deny_terms=[])
