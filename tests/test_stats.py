from um.bench.stats import paired_diff, wilson


def test_wilson_matches_known_values():
    lo, hi = wilson(19, 23)
    assert round(lo, 2) == 0.63 and round(hi, 2) == 0.93


def test_wilson_handles_empty_and_extreme_counts():
    assert wilson(0, 0) == (0.0, 1.0)
    lo, hi = wilson(10, 10)
    assert 0.6 < lo < 0.8 and hi == 1.0
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and 0.2 < hi < 0.4


def test_paired_diff_is_zero_for_identical_arms():
    d, lo, hi = paired_diff([True, False] * 20, [True, False] * 20)
    assert d == lo == hi == 0.0


def test_paired_diff_sees_a_clear_difference_and_is_repeatable():
    a, b = [True] * 30 + [False] * 10, [True] * 10 + [False] * 30
    d, lo, hi = paired_diff(a, b, seed=1)
    assert d == 0.5 and 0.25 < lo < 0.5 < hi < 0.75
    assert paired_diff(a, b, seed=1) == (d, lo, hi)
    assert paired_diff([], []) == (0.0, 0.0, 0.0)
