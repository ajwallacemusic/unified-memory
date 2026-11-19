import pytest

from um.evidence import contains_quote, load_evidence


def write(d, name, body):
    d.mkdir(exist_ok=True)
    (d / name).write_text(body)


def test_load_reads_origin_date_and_text(tmp_path):
    write(tmp_path, "e001.md", "origin: user-said\ndate: 2026-01-03\n\nuser: I just started at Brightline.\nassistant: Noted.\n")
    ev = load_evidence(tmp_path)["e001"]
    assert (ev.id, ev.origin, ev.date) == ("e001", "user-said", "2026-01-03") and "Brightline" in ev.text


def test_a_file_without_the_two_header_lines_is_an_error(tmp_path):
    write(tmp_path, "bad.md", "user: hello\n")
    with pytest.raises(ValueError, match="bad.md"):
        load_evidence(tmp_path)
    write(tmp_path, "bad.md", "origin: rumour\ndate: 2026-01-03\n\nx\n")
    with pytest.raises(ValueError, match="bad.md"):
        load_evidence(tmp_path)


def test_quotes_must_be_in_the_text_whitespace_aside(tmp_path):
    write(tmp_path, "e001.md", "origin: user-said\ndate: 2026-01-03\n\nuser: I just started\nat Brightline.\n")
    ev = load_evidence(tmp_path)["e001"]
    assert contains_quote(ev, "I just started at   Brightline")
    assert not contains_quote(ev, "I just started at Brightlane")
    assert not contains_quote(ev, "") and not contains_quote(ev, "   ")
    assert not contains_quote(ev, "origin: user-said")
