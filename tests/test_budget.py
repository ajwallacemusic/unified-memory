from concurrent.futures import ThreadPoolExecutor

import pytest

from um.budget import Budget, BudgetExceeded, cost_usd


def test_haiku_tier_switches_above_100k():
    assert cost_usd("claude-haiku-5-5", 100_000, 0) == pytest.approx(0.01)
    assert cost_usd("claude-haiku-5-5", 115_000, 1_000) == pytest.approx(0.0575 + 0.0025)


def test_check_refuses_before_the_cap_is_crossed(tmp_path):
    b = Budget(0.02, tmp_path / "l.jsonl")
    b.charge("claude-haiku-5-5", 100_000, 0, "x")
    with pytest.raises(BudgetExceeded):
        b.check("claude-haiku-5-5", 100_000, 2_000)


def test_ledger_survives_restart_and_concurrent_charges(tmp_path):
    p = tmp_path / "l.jsonl"
    b = Budget(5, p)
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda _: b.charge("claude-sonnet-5-5", 1_000, 100, "x"), range(200)))
    assert Budget(5, p).spent() == pytest.approx(200 * 0.003)


def test_unknown_model_is_an_error():
    with pytest.raises(KeyError):
        cost_usd("not-a-model", 1, 1)


def test_cache_tokens_are_priced_at_their_own_rates():
    assert cost_usd("claude-haiku-5-5", 1_000, 0, cache_write_tokens=20_000, cache_read_tokens=40_000) == pytest.approx(0.003)
    assert cost_usd("claude-sonnet-5-5", 0, 0, cache_write_tokens=1_000_000, cache_read_tokens=1_000_000) == pytest.approx(2.60)


def test_cached_tokens_count_toward_the_long_prompt_tier():
    assert cost_usd("claude-haiku-5-5", 10_000, 0, cache_read_tokens=95_000) == pytest.approx(0.00975)


def test_charge_records_cache_tokens(tmp_path):
    b = Budget(1, tmp_path / "l.jsonl")
    assert b.charge("claude-haiku-5-5", 1_000, 0, "x", cache_write_tokens=20_000, cache_read_tokens=40_000) == pytest.approx(0.003)
    assert Budget(1, tmp_path / "l.jsonl").spent() == pytest.approx(0.003)


SONNET_CALL = ("claude-sonnet-5-5", 1_000, 100)   # costs $0.003


def test_concurrent_checks_cannot_all_pass_when_one_call_fits(tmp_path):
    b = Budget(0.0035, tmp_path / "l.jsonl")

    def attempt(_):
        try:
            b.check(*SONNET_CALL)
            return True
        except BudgetExceeded:
            return False

    with ThreadPoolExecutor(8) as ex:
        assert sum(ex.map(attempt, range(8))) == 1


def test_release_and_charge_settle_a_reservation(tmp_path):
    b = Budget(0.0035, tmp_path / "l.jsonl")
    b.release(b.check(*SONNET_CALL))
    reserved = b.check(*SONNET_CALL)            # passes again because the first reservation was released
    b2 = Budget(0.0065, tmp_path / "m.jsonl")
    r = b2.check(*SONNET_CALL)
    b2.charge(*SONNET_CALL, "x", reserved=r)
    b2.check(*SONNET_CALL)                      # 0.003 spent + 0.003 reserved fits under 0.0065
    assert reserved == pytest.approx(0.003)


def test_a_second_process_sees_the_first_ones_spend(tmp_path):
    p = tmp_path / "l.jsonl"
    a, b = Budget(0.004, p), Budget(0.004, p)
    a.charge(*SONNET_CALL, "x")
    assert b.spent() == pytest.approx(0.003)
    with pytest.raises(BudgetExceeded):
        b.check(*SONNET_CALL)
