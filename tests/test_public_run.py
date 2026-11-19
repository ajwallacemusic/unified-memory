import json
from dataclasses import dataclass

import pytest

from um.bench.public import run as pr
from um.bench.public.pipeline import Session
from um.llm import Reply
from um.llm_sub import SubscriptionError


class ByLabel:
    """A fake client that answers by call label and records every call."""

    def __init__(self):
        self.calls = []

    def complete(self, *, model, system, user, max_tokens, label):
        self.calls.append({"model": model, "system": system, "user": user, "label": label})
        if label == "compile":
            ev = "s001-user"
            return Reply(json.dumps([{"op": "add", "file": "memory/pets.md", "new": "- Dog called Pepper, a terrier",
                                      "citations": [{"evidence": ev, "quote": "My dog Pepper is a terrier"}]}]),
                         "end_turn", 50, 10, backend="subscription")
        if label.startswith("judge"):
            return Reply("yes" if "Pepper" in user else "no", "end_turn", 5, 1)
        return Reply("Pepper" if "Pepper" in system else "I do not know", "end_turn", len(system) // 4 + 10, 3,
                     usd=0.001)


@dataclass(frozen=True)
class It:
    id: str
    q: str


def fake_bench():
    hist = [Session("a", "2026-01-01", (("user", "My dog Pepper is a terrier."), ("assistant", "Lovely."))),
            Session("b", "2026-01-02", (("user", "It rained all day."), ("assistant", "Stay dry.")))]
    return pr.Bench(
        name="fake", items=[It("i1", "What breed is my dog Pepper?"), It("i2", "Which terrier is my dog Pepper?")],
        key=lambda it: "shared", sessions=lambda it, llm, wd: hist, question=lambda it: it.q, query=lambda it: it.q,
        instructions=lambda it, c: f"Answer ({c}).",
        grade=lambda it, text, llm: {"correct": llm.complete(model="j", system="", user=text, max_tokens=5,
                                                              label="judge:fake").text == "yes"},
        max_tokens=50, extra={"last-write": lambda it: "1. My dog Pepper is a terrier."})


def test_run_answers_every_condition_and_compiles_once_per_profile(tmp_path):
    llm = ByLabel()
    pr.run(fake_bench(), tmp_path, llm, answer_model="a", compile_model="c", judge_model="j",
           conditions=pr.ALL + ("last-write",))
    rows = [json.loads(x) for x in (tmp_path / "results.jsonl").read_text().splitlines()]
    assert len(rows) == 12 and {r["condition"] for r in rows} == set(pr.ALL) | {"last-write"}
    assert sum(1 for c in llm.calls if c["label"] == "compile") == 1
    by = {(r["item"], r["condition"]): r for r in rows}
    assert by[("i1", "none")]["correct"] is False and by[("i1", "full-history")]["correct"] is True
    assert by[("i1", "profile-hook")]["correct"] is True and by[("i1", "profile-full")]["correct"] is True
    assert by[("i1", "raw-retrieval")]["correct"] is True and by[("i1", "last-write")]["correct"] is True
    r = by[("i1", "profile-hook")]
    assert r["input_tokens"] > 10 and r["context_chars"] > 0 and r["answer"] == "Pepper" and r["backend"] == "api"
    assert by[("i1", "none")]["context_chars"] == 0
    answer_calls = [c for c in llm.calls if c["label"].startswith("answer")]
    assert all(c["model"] == "a" for c in answer_calls) and all(c["system"].startswith("Answer (") for c in answer_calls)
    # resumable: a second run makes no calls
    again = ByLabel()
    pr.run(fake_bench(), tmp_path, again, answer_model="a", compile_model="c", judge_model="j",
           conditions=pr.ALL + ("last-write",))
    assert again.calls == []


def test_a_failing_item_is_logged_and_the_rest_continue(tmp_path):
    bench = fake_bench()

    def boom(it, llm, wd):
        if it.id == "i1":
            raise RuntimeError("bad item")
        return fake_bench().sessions(it, llm, wd)

    bench.sessions = boom
    pr.run(bench, tmp_path, ByLabel(), answer_model="a", compile_model="c", judge_model="j", conditions=("none",))
    rows = [json.loads(x) for x in (tmp_path / "results.jsonl").read_text().splitlines()]
    assert [r["item"] for r in rows] == ["i2"]
    assert "bad item" in (tmp_path / "errors.jsonl").read_text()


class Gate:
    def __init__(self, open_):
        self.open_ = open_

    def is_open(self):
        return self.open_


class Rec:
    def __init__(self, name, fail=0):
        self.name, self.fail, self.n = name, fail, 0

    def complete(self, **kw):
        self.n += 1
        if self.fail:
            self.fail -= 1
            raise SubscriptionError("flaky")
        return Reply(self.name, "end_turn", 1, 1)


def test_router_sends_compiles_to_the_subscription_and_the_rest_to_the_api():
    api, sub = Rec("api"), Rec("sub", fail=1)
    r = pr.Router(api, sub, Gate(True))
    kw = dict(model="m", system="", user="u", max_tokens=5)
    assert r.complete(label="compile", **kw).text == "sub" and sub.n == 2      # one retry after a failure
    assert r.complete(label="answer:x", **kw).text == "api"
    with pytest.raises(pr.SubscriptionClosed):
        pr.Router(api, sub, Gate(False)).complete(label="compile", **kw)


def test_enrichment_calls_go_to_the_subscription_by_default():
    from um.bench.public.run import Router
    r = Router(api=None, sub=None, gate=None)
    assert all(lbl.startswith(r.sub_prefixes) for lbl in ("compile:x", "expand", "standing"))
