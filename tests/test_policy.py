import json

import pytest

from um.bridge.policy import DEFAULT_POLICY, STATES, blocked_pattern, decide_line, load_policy

ID = "identity-work-projects-preferences"


@pytest.mark.parametrize("line", [
    "- Card on file: 4111 1111 1111 1111",
    "- Card: 4111-1111-1111-1111 for groceries",
    "- SSN 123-45-6789",
    "- API key sk-" + "a1B2c3D4e5" * 3,
    "- GitHub token ghp_" + "x" * 36,
    "- AWS key AKIAABCDEFGHIJKLMNOP",
    "- The wifi password is hunter22",
    "- password: correct horse",
])
def test_number_and_secret_patterns_are_never_stored_whatever_the_label(line):
    assert blocked_pattern(line) is not None
    assert decide_line(line, ID, DEFAULT_POLICY)[0] == "never"


@pytest.mark.parametrize("line", [
    "- Phone: +1 (512) 555-0134",
    "- Order 1234567812345678 shipped",          # 16 digits, not Luhn-valid
    "- Squat 405 lb, bench 285 lb, deadlift 500 lb in March 2026",
    "- Works at Brightline since 2025-06-01",
])
def test_ordinary_numbers_pass(line):
    assert blocked_pattern(line) is None
    assert decide_line(line, ID, DEFAULT_POLICY)[0] == "push"


def test_states_from_the_spec_table():
    assert set(DEFAULT_POLICY.values()) <= set(STATES)
    assert DEFAULT_POLICY["training-lifts"] == "local"
    assert DEFAULT_POLICY["budgeting-setup"] == "local"
    assert DEFAULT_POLICY["body-weight-nutrition"] == "local"
    assert DEFAULT_POLICY["employer-client-knowledge"] == "local"
    for c in ("financial-figures", "account-ids-credentials", "medical"):
        assert DEFAULT_POLICY[c] == "never"
    assert decide_line("- Weighs 190 lb", "body-weight-nutrition", DEFAULT_POLICY)[0] == "local"


def test_unlisted_or_missing_category_is_local_and_asked_once():
    for cat in (None, "other", "astrology"):
        state, reason = decide_line("- Likes jazz", cat, DEFAULT_POLICY)
        assert state == "local" and reason == "category not in policy: ask once"


def test_load_policy_overrides_defaults_and_rejects_bad_states(tmp_path):
    p = tmp_path / "policy.json"
    p.write_text(json.dumps({"body-weight-nutrition": "push"}))
    pol = load_policy(p)
    assert pol["body-weight-nutrition"] == "push" and pol["medical"] == "never"
    p.write_text(json.dumps({"medical": "sometimes"}))
    with pytest.raises(ValueError):
        load_policy(p)
    assert load_policy(tmp_path / "missing.json") == DEFAULT_POLICY


import pytest as _pytest


@_pytest.mark.parametrize("line", [
    "- Card 4111 1111 1111 1111 12/27",
    "- Card 4111111111111111 123",
    "- Visa-4111111111111111",
    "- Card 4111.1111.1111.1111",
    "- SSN 123456789",
    "- SSN 123 45 6789",
    "- IBAN DE89 3704 0044 0532 0130 00",
    "- Checking account 000123456789, routing 021000021",
])
def test_number_patterns_found_in_more_shapes(line):
    from um.bridge.policy import blocked_pattern
    assert blocked_pattern(line), line


@_pytest.mark.parametrize("line", ["- Squat 405 lb on 2026-11-10", "- Phone area code 314", "- Born 1985, 2 kids"])
def test_ordinary_numbers_are_not_blocked(line):
    from um.bridge.policy import blocked_pattern
    assert blocked_pattern(line) is None
