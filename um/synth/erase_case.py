"""The erase case in the replay: which facts to erase, their values, and the scenario after the erase.

After an erase the person does not mention the fact again, so later events that assert it are dropped,
and later probes about it expect no value at all (category "erased")."""
from __future__ import annotations

from dataclasses import replace
from datetime import date

from um.synth.scenario import Scenario


def erase_targets(scn: Scenario) -> list[str]:
    """The alphabetically first attribute with "updated" probes after the third checkpoint, and the first
    with "old-valid" probes after it that no event asserts after week 3."""
    cut = scn.checkpoints[2]
    later = [p for p in scn.probes if p.day > cut]
    asserted_later = {a for e in scn.events if e.day > cut for a, _ in e.asserts}
    updated = sorted({p.attr for p in later if p.category == "updated"})
    old_valid = sorted({p.attr for p in later if p.category == "old-valid"} - asserted_later)
    return [updated[0], old_valid[0]]


def values_of(scn: Scenario, attr: str) -> list[str]:
    """Every value the attribute has had, plus planted values aimed at it."""
    vals = [f.value for f in scn.facts if f.attr == attr]
    vals += [v for e in scn.events if e.planted for a, v in e.asserts if a == attr]
    return list(dict.fromkeys(vals))


def after_erase(scn: Scenario, attrs: list[str], day: date) -> Scenario:
    targets = set(attrs)
    events = tuple(e for e in scn.events if not (e.day > day and any(a in targets for a, _ in e.asserts)))
    probes = tuple(replace(p, category="erased", current="", stale=tuple(values_of(scn, p.attr)), planted=())
                   if p.day > day and p.attr in targets else p for p in scn.probes)
    return replace(scn, events=events, probes=probes)
