"""Made-up facts for the cross-surface recall test.

Each is stated on one surface and then asked about on every other surface. None is real personal
data. Each carries a unique codeword so a hit can be checked mechanically.
"""
from __future__ import annotations

from dataclasses import dataclass

SURFACES = ("chat", "task", "code:unified-memory", "code:home")

_PREFIX = "This is a test fact for my unified-memory project; please treat it as a real fact about me. "


@dataclass(frozen=True)
class Canary:
    id: str
    stated_on: str
    statement: str
    question: str
    token: str


def _c(id: str, stated_on: str, fact: str, question: str, token: str) -> Canary:
    return Canary(id, stated_on, _PREFIX + fact, question, token)


CANARIES: tuple[Canary, ...] = (
    _c("c01", "chat", "My practice mandolin is nicknamed KESTREL-17.", "What is my practice mandolin's nickname?", "KESTREL-17"),
    _c("c02", "chat", "The label I use for my garden log is JUNIPER-42.", "What label do I use for my garden log?", "JUNIPER-42"),
    _c("c03", "chat", "My reading group goes by the code name OSPREY-08.", "What is my reading group's code name?", "OSPREY-08"),
    _c("c04", "task", "The checklist I use before road trips is called TAMARACK-63.", "What is my road-trip checklist called?", "TAMARACK-63"),
    _c("c05", "task", "My shelf of board games is catalogued under MARLIN-29.", "Under what name is my board-game shelf catalogued?", "MARLIN-29"),
    _c("c06", "code:unified-memory", "My scratch branches are always prefixed HERON-51.", "What prefix do I always use for scratch branches?", "HERON-51"),
    _c("c07", "code:unified-memory", "My test fixtures folder is nicknamed BASALT-76.", "What is the nickname of my test fixtures folder?", "BASALT-76"),
    _c("c08", "code:unified-memory", "The name I give throwaway databases is LARCH-34.", "What name do I give throwaway databases?", "LARCH-34"),
    _c("c09", "code:home", "My backup drive is labelled CONDOR-90.", "What is my backup drive labelled?", "CONDOR-90"),
    _c("c10", "code:home", "My weekly review note is titled SORREL-25.", "What is my weekly review note titled?", "SORREL-25"),
)
