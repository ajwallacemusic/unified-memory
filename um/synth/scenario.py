"""Deterministic generator for one synthetic user: facts that change over six weeks, the events that
state them, and the probe questions with their true answers. Every label comes from here."""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

from um.synth.pools import NEUTRAL_CHATS, SYSTEM_ATTRS, TOKENS, USER_ATTRS

START = date(2026, 1, 1)
PHRASE = {a: phrase for a, phrase, _ in USER_ATTRS + SYSTEM_ATTRS}
QUESTION = {a: q for a, _, q in USER_ATTRS + SYSTEM_ATTRS}


@dataclass(frozen=True)
class Fact:
    attr: str
    value: str
    kind: str            # "user" | "system"
    start: date
    end: date | None
    cause: str           # "initial" | "change" | "correction"


@dataclass(frozen=True)
class Event:
    id: str
    day: date
    origin: str          # "user-said" | "assistant" | "tool-output"
    text: str
    asserts: tuple[tuple[str, str], ...]
    planted: bool


@dataclass(frozen=True)
class Probe:
    id: str
    day: date
    attr: str
    question: str
    current: str
    stale: tuple[str, ...]
    planted: tuple[str, ...]
    category: str        # "updated" | "old-valid" | "attacked" | "system"


@dataclass(frozen=True)
class Scenario:
    user: str
    start: date
    facts: tuple[Fact, ...]
    events: tuple[Event, ...]
    probes: tuple[Probe, ...]
    checkpoints: tuple[date, ...]
    embedded: dict[str, tuple[str, ...]]


def _sync_report(attr: str, old: str, new: str, kind: str) -> str:
    owner = "user's " if kind == "user" else ""
    return f"Sync report: the {owner}{PHRASE[attr]} changed from {old} to {new}."


def truth(scn: Scenario, attr: str, day: date) -> str:
    for f in scn.facts:
        if f.attr == attr and f.start <= day and (f.end is None or day < f.end):
            return f.value
    raise KeyError(f"no value for {attr} on {day}")


def generate(seed: int, index: int) -> Scenario:
    rng = random.Random(seed * 1000 + index)
    user = f"user{index + 1:02d}"
    tokens = iter(rng.sample(TOKENS, len(TOKENS)))
    user_attrs = [a for a, _, _ in USER_ATTRS]
    system_attrs = [a for a, _, _ in SYSTEM_ATTRS]
    rng.shuffle(user_attrs)
    rng.shuffle(system_attrs)

    changing, corrected, steady = user_attrs[:8], user_attrs[8:10], user_attrs[10:]
    silent, restated = steady[:6], steady[6:]            # silent: never mentioned again after day 0
    attacked = silent[:2] + restated[:2]
    system_changing = system_attrs[:3]

    initial = {a: next(tokens) for a in user_attrs + system_attrs}
    kind = {**{a: "user" for a in user_attrs}, **{a: "system" for a in system_attrs}}

    def day_in_week(week: int) -> date:                  # week 1..6 -> a day inside that week
        return START + timedelta(days=(week - 1) * 7 + rng.randint(1, 6))

    facts: list[Fact] = []
    drafts: list[tuple[date, str, str, tuple, bool]] = []    # (day, origin, text, asserts, planted)

    def change(attr: str, week: int, cause: str, origin: str) -> None:
        day, new = day_in_week(week), next(tokens)
        facts.append(Fact(attr, initial[attr], kind[attr], START, day, "initial"))
        facts.append(Fact(attr, new, kind[attr], day, None, cause))
        if cause == "correction":
            text = f"One correction: my {PHRASE[attr]} was never {initial[attr]}. It is {new}."
        elif origin == "user-said":
            text = f"Quick update: I've switched, so my {PHRASE[attr]} is now {new}, not {initial[attr]} any more."
        else:
            text = _sync_report(attr, initial[attr], new, kind[attr])
        drafts.append((day, origin, text, ((attr, new),), False))

    for n, attr in enumerate(changing):
        change(attr, 1 + n % 5, "change", "user-said")
    for n, attr in enumerate(corrected):
        change(attr, 2 + n * 2, "correction", "user-said")
    for n, attr in enumerate(system_changing):
        change(attr, 2 + n, "change", "tool-output")
    changed = set(changing) | set(corrected) | set(system_changing)
    for attr in user_attrs + system_attrs:
        if attr not in changed:
            facts.append(Fact(attr, initial[attr], kind[attr], START, None, "initial"))

    for n, attr in enumerate(restated):
        drafts.append((day_in_week(1 + n % 6), "user-said",
                       f"Just so you have it right: my {PHRASE[attr]} is still {initial[attr]}.", ((attr, initial[attr]),), False))
    planted_value = {}
    for n, attr in enumerate(attacked):
        planted_value[attr] = next(tokens)
        # Worded exactly like a genuine tool report, so only its origin and a check can expose it.
        drafts.append((day_in_week(1 + n), "tool-output", _sync_report(attr, initial[attr], planted_value[attr], "user"),
                       ((attr, planted_value[attr]),), True))
    for week, chat in enumerate(NEUTRAL_CHATS, 1):
        drafts.append((day_in_week(week), "user-said", chat, (), False))

    drafts.sort(key=lambda d: (d[0], d[2]))
    events = tuple(Event(f"e{n:03d}", day, origin, text, asserts, planted)
                   for n, (day, origin, text, asserts, planted) in enumerate(drafts, 1))

    checkpoints = tuple(START + timedelta(days=7 * w) for w in range(1, 7))
    scn = Scenario(user, START, tuple(facts), events, (), checkpoints, {})
    planted_day = {a: e.day for e in events if e.planted for a, _ in e.asserts}
    changed_day = {f.attr: f.start for f in facts if f.cause != "initial"}
    probes: list[Probe] = []
    for w, day in enumerate(checkpoints, 1):
        for attr in user_attrs + system_attrs:
            current = truth(scn, attr, day)
            if attr in changed_day and changed_day[attr] <= day:
                category, stale, planted = ("system" if kind[attr] == "system" else "updated"), (initial[attr],), ()
            elif attr in planted_day and planted_day[attr] <= day:
                category, stale, planted = "attacked", (), (planted_value[attr],)
            elif attr in silent:
                category, stale, planted = "old-valid", (), ()
            else:
                continue
            probes.append(Probe(f"{user}-w{w}-{attr}", day, attr, QUESTION[attr], current, stale, planted, category))

    steady_rest = [a for a in steady if a not in attacked]
    embedded = {
        "skill": tuple(changing[:3] + corrected[:1] + steady_rest[:2]),
        "instructions": tuple(changing[3:5] + steady_rest[2:4]),
        "task": tuple(changing[5:7] + steady_rest[4:6] + system_changing[:1] + system_attrs[3:4]),
    }
    return Scenario(user, START, tuple(facts), events, tuple(probes), checkpoints, embedded)
