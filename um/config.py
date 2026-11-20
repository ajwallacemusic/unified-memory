"""Where the profile lives and which model route to use, for every entry point (CLI, hooks, plugin commands).

    ~/.config/unified-memory/config.json   {"profile": "/path", "llm": "subscription" | "hybrid" | "api",
                                             "spend_log": "/path/spend.jsonl", "api_cap": 50,
                                             "search": true}

Order: an explicit argument, then UM_PROFILE / UM_LLM, then the config file, then the defaults
(~/claude-profile, subscription). `subscription` runs every model call through `claude -p` on the user's plan,
so no API key is needed. Written by `python -m um.cli init`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_PROFILE = "~/claude-profile"
MODES = ("subscription", "hybrid", "api")


def config_path() -> Path:
    return Path(os.environ.get("UM_CONFIG") or "~/.config/unified-memory/config.json").expanduser()


def load_config() -> dict:
    try:
        d = json.loads(config_path().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(**values) -> Path:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({**load_config(), **values}, indent=1) + "\n")
    return p


def profile_path(explicit: str | os.PathLike | None = None) -> Path:
    raw = explicit or os.environ.get("UM_PROFILE") or load_config().get("profile") or DEFAULT_PROFILE
    return Path(raw).expanduser()


def llm_mode() -> str:
    m = os.environ.get("UM_LLM") or load_config().get("llm") or "subscription"
    return m if m in MODES else "subscription"


def search_index_path() -> Path:
    """Where the conversation-search index lives: UM_SEARCH_INDEX, then config "search_index", then the default."""
    from um.search.index import DEFAULT_PATH
    raw = os.environ.get("UM_SEARCH_INDEX") or load_config().get("search_index") or DEFAULT_PATH
    return Path(raw).expanduser()


SEARCH_OFF = ('Conversation search is off ("search": false in ~/.config/unified-memory/config.json). '
              'Set it to true to turn it back on.')


def search_enabled() -> bool:
    """The off switch for conversation search (config "search"); on unless set to false. When off, the
    SessionStart catch-up does nothing, `search index` refuses, and the search tools say so without reading."""
    return load_config().get("search") is not False


def search_include_sdk() -> bool:
    """Whether `sdk-cli` sessions are indexed (config "search_include_sdk"); off by default."""
    return load_config().get("search_include_sdk") is True
