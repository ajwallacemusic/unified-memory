"""OpenAI client with the `LLM.complete` interface, standard library only, for a judge from another model family.

Calls the Responses API (POST https://api.openai.com/v1/responses), which OpenAI's text guide recommends over
Chat Completions (https://developers.openai.com/api/docs/guides/text, read 2026-11-19). Reasoning effort is
"medium", matching the Claude calls (um/llm.py EFFORT); no temperature is sent. `max_output_tokens` counts the
model's hidden reasoning tokens too (https://developers.openai.com/api/docs/guides/reasoning), so a tight limit
can end a call with status "incomplete" before any text; that comes back as stop_reason "max_tokens".

The key is read from os.environ["OPENAI_API_KEY"] at call time and only placed in the Authorization header; it is
never logged or put in an error message. Every call checks the shared spend cap first and writes a ledger row
afterwards, like `AnthropicLLM`. Prices: um/budget.py PRICES; `prices=` or OPENAI_JUDGE_PRICE="in,cached,out"
(dollars per million tokens, applied to the default judge model) adds or overrides a row.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from um.budget import PRICES, Budget, Price, Rates
from um.llm import EFFORT, Reply, _estimate_tokens

URL = "https://api.openai.com/v1/responses"
# OpenAI's models page names gpt-6.2-astra as the place to start; Sol is its "balance of intelligence and cost"
# tier at a quarter of the price (https://developers.openai.com/api/docs/models, read 2026-11-19). A rejudge of
# ~2,100 calls fits the remaining project cap on Sol; set OPENAI_JUDGE_MODEL=gpt-6.2-astra to use the flagship.
DEFAULT_MODEL = "gpt-6.2-sol"
RETRY_STATUSES = (408, 409, 429, 500, 502, 503, 504)


class OpenAIKeyMissing(RuntimeError):
    pass


class OpenAIError(RuntimeError):
    pass


def default_model() -> str:
    return os.environ.get("OPENAI_JUDGE_MODEL") or DEFAULT_MODEL


def _urllib_post(url: str, headers: dict, data: bytes, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def register_prices(prices: dict[str, tuple[float, float, float]]) -> None:
    for model, (inp, cached, out) in prices.items():
        PRICES[model] = Price(Rates(float(inp), float(out), float(inp), float(cached)))


def _env_prices() -> dict:
    raw = os.environ.get("OPENAI_JUDGE_PRICE")
    if not raw:
        return {}
    parts = [float(x) for x in raw.split(",")]
    if len(parts) != 3:
        raise ValueError('OPENAI_JUDGE_PRICE must be "input,cached_input,output" in dollars per million tokens')
    return {default_model(): tuple(parts)}


def _parse(data: dict) -> tuple[str, str]:
    texts, refused = [], False
    for item in data.get("output") or []:
        if item.get("type") != "message":
            continue
        for c in item.get("content") or []:
            if c.get("type") == "output_text":
                texts.append(c.get("text") or "")
            elif c.get("type") == "refusal":
                refused = True
    reason = (data.get("incomplete_details") or {}).get("reason")
    if refused or reason == "content_filter":
        stop = "refusal"
    elif data.get("status") == "incomplete":
        stop = "max_tokens" if reason == "max_output_tokens" else (reason or "incomplete")
    else:
        stop = "end_turn"
    return "".join(texts), stop


class OpenAILLM:
    def __init__(self, budget: Budget, *, http=None, sleep=time.sleep, prices: dict | None = None,
                 timeout: float = 120.0, max_retries: int = 4):
        self.budget = budget
        self.http = http or _urllib_post
        self.sleep = sleep
        self.timeout = timeout
        self.max_retries = max_retries
        register_prices({**_env_prices(), **(prices or {})})

    def complete(self, *, model: str, system: str, user: str, max_tokens: int, label: str) -> Reply:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise OpenAIKeyMissing("OPENAI_API_KEY is not set; export it in this shell before running the OpenAI judge")
        if model not in PRICES:
            raise ValueError(f"no price for {model}; add it to um/budget.py PRICES or set OPENAI_JUDGE_PRICE")
        body = {"model": model, "input": user, "max_output_tokens": max_tokens, "reasoning": {"effort": EFFORT},
                "store": False}
        if system:
            body["instructions"] = system
        reserved = self.budget.check(model, _estimate_tokens(system, user), max_tokens)
        try:
            data = self._post(body, key)
        except BaseException:
            self.budget.release(reserved)
            raise
        u = data.get("usage") or {}
        tin = int(u.get("input_tokens") or 0)
        cached = int((u.get("input_tokens_details") or {}).get("cached_tokens") or 0)
        tout = int(u.get("output_tokens") or 0)
        usd = self.budget.charge(model, tin - cached, tout, label, cache_read_tokens=cached, reserved=reserved)
        text, stop = _parse(data)
        return Reply(text, stop, tin, tout, backend="openai", usd=usd)

    def _post(self, body: dict, key: str) -> dict:
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
        payload = json.dumps(body).encode()
        for attempt in range(self.max_retries + 1):
            try:
                status, raw = self.http(URL, headers, payload, self.timeout)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt == self.max_retries:
                    raise OpenAIError(f"OpenAI request failed: {type(e).__name__}") from None
                self.sleep(min(30, 2 ** attempt))
                continue
            if status == 200:
                return json.loads(raw)
            if status in RETRY_STATUSES and attempt < self.max_retries:
                self.sleep(min(30, 2 ** attempt))
                continue
            try:
                msg = (json.loads(raw).get("error") or {}).get("message", "")
            except ValueError:
                msg = raw[:300].decode(errors="replace")
            raise OpenAIError(f"OpenAI API returned {status}: {msg}"[:500])
        raise OpenAIError("OpenAI request failed")  # not reached

    def run_tools(self, **kw) -> Reply:
        raise NotImplementedError("OpenAILLM is a judge backend; tool loops are not supported")
