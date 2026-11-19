"""Interval statistics for small samples."""
from __future__ import annotations

import math
import random
from typing import Sequence


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k successes out of n."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    lo = 0.0 if k == 0 else max(0.0, centre - half)
    hi = 1.0 if k == n else min(1.0, centre + half)
    return (lo, hi)


def paired_diff(a: Sequence[bool], b: Sequence[bool], n_boot: int = 10_000, seed: int = 0) -> tuple[float, float, float]:
    """Mean of a minus mean of b on the same items, with a 95% bootstrap interval over paired resamples."""
    if len(a) != len(b):
        raise ValueError("paired samples must be the same length")
    n = len(a)
    if n == 0:
        return (0.0, 0.0, 0.0)
    diffs = [int(x) - int(y) for x, y in zip(a, b)]
    point = sum(diffs) / n
    if not any(diffs):
        return (0.0, 0.0, 0.0)
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(n_boot))
    return (point, means[int(0.025 * n_boot)], means[min(n_boot - 1, int(0.975 * n_boot))])
