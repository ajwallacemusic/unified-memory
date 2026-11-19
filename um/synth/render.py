"""Render a scenario into stores and dated evidence files. All text comes from templates."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from um.bench.longmemeval import Session, Turn
from um.synth.pools import SYSTEM_ATTRS, USER_ATTRS
from um.synth.scenario import PHRASE, Scenario, truth

_ORDER = [a for a, _, _ in USER_ATTRS + SYSTEM_ATTRS]
_TOPICS = (
    ("work.md", "Work", "job, team and project", ("employer", "job_title", "team_name", "manager", "project_codename", "standup_room")),
    ("home.md", "Home and services", "where they live and who they use", ("home_city", "gym", "dentist", "bank", "phone_carrier", "insurer", "accountant")),
    ("things.md", "Things and habits", "car, coffee, food, books, running, holidays", ("car_model", "coffee_order", "restaurant", "book_club_pick", "running_route", "holiday_spot")),
    ("tools.md", "Tools", "editor, laptop and apps", ("code_editor", "laptop", "backup_service", "password_manager", "calendar_app")),
    ("systems.md", "Systems", "connector, repository and deployment set-up", tuple(a for a, _, _ in SYSTEM_ATTRS)),
)


def _sentence(scn: Scenario, attr: str) -> str:
    return f"The user's {PHRASE[attr]} is {truth(scn, attr, scn.start)}."


def render_static(scn: Scenario, root: Path) -> None:
    """Lay down the four stores as they stand on day 0."""
    root = Path(root)
    memory = root / "memory"
    memory.mkdir(parents=True, exist_ok=True)
    index = []
    for name, title, covers, attrs in _TOPICS:
        lines = [f"# {title}", ""] + [f"- {PHRASE[a].capitalize()}: {truth(scn, a, scn.start)} (noted before {scn.start.isoformat()})"
                                      for a in attrs]
        (memory / name).write_text("\n".join(lines) + "\n")
        index.append(f"- [{title}]({name}): {covers}")
    (memory / "MEMORY.md").write_text("\n".join(index) + "\n")

    skill = root / "skills" / "helper"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        "---\nname: helper\ndescription: Drafts short documents and messages for the user in their own voice.\n---\n\n"
        "# Drafting helper\n\n"
        "Use this skill when the user asks for a short document, a bio, a cover note or a status message.\n\n"
        "## Steps\n\n1. Ask what the document is for if it is not clear.\n2. Draft it in plain, direct sentences.\n"
        "3. Check every fact about the user against the profile below before sending.\n4. Offer one shorter version.\n\n"
        "## Profile to draw on\n\n" + "\n".join(f"- {_sentence(scn, a)}" for a in scn.embedded["skill"]) + "\n")

    instructions = root / "instructions"
    instructions.mkdir(parents=True, exist_ok=True)
    (instructions / "CLAUDE.md").write_text(
        "# Working notes for this workspace\n\n"
        "Keep answers short. Prefer plain text over tables. Ask before running anything that changes files outside this folder. "
        "When writing commit messages, use the imperative mood and keep the first line under seventy characters.\n\n"
        "## About the user\n\n" + "\n".join(f"- {_sentence(scn, a)}" for a in scn.embedded["instructions"]) + "\n")

    tasks = root / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    (tasks / "weekly-task.md").write_text(
        "Weekly summary task. Every Monday morning, gather what changed last week and write the user a five-line summary. "
        "Read the calendar first, then the issue tracker, then any notes left by the last run. Report only; do not send messages "
        "to anyone else and do not change settings. If a source is unavailable, say so in the last line and carry on.\n\n"
        "Working knowledge to use:\n" + "\n".join(f"- {_sentence(scn, a)}" for a in scn.embedded["task"]) + "\n")


def render_evidence(scn: Scenario, since: date, until: date, out_dir: Path) -> list[Path]:
    """One file per event dated after `since` and on or before `until`."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for e in scn.events:
        if not (since < e.day <= until):
            continue
        if e.origin == "tool-output":
            turns = ["user: Please check what came in and tell me if anything needs me.", "assistant: I'll take a look.",
                     f"tool: {e.text}", "assistant: I've read what came back."]
        else:
            speaker = "assistant" if e.origin == "assistant" else "user"
            turns = [f"{speaker}: {e.text}", "assistant: Noted." if speaker == "user" else "user: OK."]
        path = out_dir / f"{e.id}.md"
        path.write_text(f"origin: {e.origin}\ndate: {e.day.isoformat()}\n\n" + "\n".join(turns) + "\n")
        paths.append(path)
    return paths


def as_sessions(paths: list[Path]) -> list[Session]:
    """Evidence files as chat sessions for the memory writer."""
    sessions = []
    for p in sorted(paths):
        lines = Path(p).read_text().splitlines()
        day = date.fromisoformat(lines[1].split(": ", 1)[1])
        turns = tuple(Turn(*line.split(": ", 1)) for line in lines[3:] if ": " in line)
        sessions.append(Session(Path(p).stem, day.strftime("%Y/%m/%d (%a) 09:00"), turns))
    return sessions
