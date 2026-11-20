"""Spend ledger with a hard dollar cap for API calls.

Prices are dollars per million tokens, from a table cached on 2026-10-06. Recheck them against the
live pricing page before the first paid run and correct them here if they differ.
"""
from __future__ import annotations

import fcntl
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Rates:
    input: float
    output: float
    cache_write: float  # five-minute cache write
    cache_read: float


@dataclass(frozen=True)
class Price:
    base: Rates
    # Some models charge more when the whole prompt (cached tokens included) is long.
    long_prompt_threshold: int | None = None
    long: Rates | None = None


PRICES: dict[str, Price] = {
    "claude-haiku-5-5": Price(Rates(0.10, 0.50, 0.125, 0.01), long_prompt_threshold=100_000,
                              long=Rates(0.50, 2.50, 0.625, 0.05)),
    "claude-sonnet-5-5": Price(Rates(2.00, 10.00, 2.50, 0.10)),
    # OpenAI, standard tier, prompts up to 272K tokens: https://developers.openai.com/api/docs/pricing (read
    # 2026-11-19). OpenAI has no cache-write charge; reasoning tokens are billed as output.
    # OPENAI_JUDGE_PRICE="input,cached,output" overrides the judge model's row (see um/llm_openai.py).
    "gpt-6.2-astra": Price(Rates(8.00, 40.00, 8.00, 0.40)),
    "gpt-6.2-sol": Price(Rates(2.00, 10.00, 2.00, 0.10)),
    "gpt-6-luna": Price(Rates(0.10, 0.50, 0.10, 0.01)),
}


class BudgetExceeded(Exception):
    """Raised when a call would take total spend past the cap."""


def cost_usd(model: str, input_tokens: int, output_tokens: int, cache_write_tokens: int = 0,
             cache_read_tokens: int = 0) -> float:
    """`input_tokens` is the uncached part of the prompt; cached tokens are passed separately."""
    price = PRICES[model]
    prompt_tokens = input_tokens + cache_write_tokens + cache_read_tokens
    long_prompt = price.long_prompt_threshold is not None and prompt_tokens > price.long_prompt_threshold
    r = price.long if long_prompt else price.base
    return (input_tokens * r.input + output_tokens * r.output + cache_write_tokens * r.cache_write
            + cache_read_tokens * r.cache_read) / 1_000_000


class Budget:
    """Tracks spend in a JSON-lines ledger and refuses calls that would cross the cap."""

    def __init__(self, cap_usd: float, ledger_path: Path):
        self.cap_usd = float(cap_usd)
        self.ledger_path = Path(ledger_path)
        self._lock = threading.Lock()
        self._spent = 0.0      # total of every row in the ledger file, whoever wrote it
        self._offset = 0       # how far into the file that total reaches
        self._reserved = 0.0   # worst-case cost of this process's calls that are in flight
        with self._lock:
            self._sync()

    def _sync(self) -> None:
        """Add rows appended since the last read, including other processes'. Caller holds the lock."""
        if not self.ledger_path.exists():
            return
        with self.ledger_path.open("rb") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                f.seek(self._offset)
                data = f.read()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        end = data.rfind(b"\n") + 1   # only whole lines
        for line in data[:end].splitlines():
            if line.strip():
                self._spent += json.loads(line)["usd"]
        self._offset += end

    def spent(self) -> float:
        with self._lock:
            self._sync()
            return self._spent

    def check(self, model: str, est_input_tokens: int, max_output_tokens: int) -> float:
        """Reserve the worst-case cost of a call, or raise. Pass the returned amount to `charge`
        (or `release` if the call never happened) so the reservation is settled.

        Reservations are per process: another process's in-flight calls are not visible, so the
        cap can be passed by at most those calls' cost.
        """
        worst_case = cost_usd(model, est_input_tokens, max_output_tokens)
        with self._lock:
            self._sync()
            if self._spent + self._reserved + worst_case > self.cap_usd:
                raise BudgetExceeded(
                    f"call could cost ${worst_case:.4f}; ${self._spent:.4f} spent and ${self._reserved:.4f} "
                    f"in flight of ${self.cap_usd:.2f} cap"
                )
            self._reserved += worst_case
        return worst_case

    def release(self, reserved: float) -> None:
        with self._lock:
            self._reserved = max(0.0, self._reserved - reserved)

    def charge(self, model: str, input_tokens: int, output_tokens: int, label: str,
               cache_write_tokens: int = 0, cache_read_tokens: int = 0, reserved: float = 0.0) -> float:
        usd = cost_usd(model, input_tokens, output_tokens, cache_write_tokens, cache_read_tokens)
        row = {
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_write_tokens": cache_write_tokens,
            "cache_read_tokens": cache_read_tokens,
            "usd": usd,
            "label": label,
        }
        with self._lock:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self.ledger_path.open("a") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.write(json.dumps(row) + "\n")
                    f.flush()
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
            self._reserved = max(0.0, self._reserved - reserved)
            self._sync()
        return usd
