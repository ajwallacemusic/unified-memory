---
description: Compile the profile from recent sessions and the bridge inbox; code decides which cited changes land
allowed-tools: Bash(cd:*)
---
Run `cd "${CLAUDE_PLUGIN_ROOT}" && python3 -m um.cli compile` with the Bash tool. Then find the profile folder with `cd "${CLAUDE_PLUGIN_ROOT}" && python3 -c "from um.config import profile_path; print(profile_path())"` and show the user the newest file in its `digest/` folder (the receipt) and any open questions in `digest/pending.md`. Do not edit profile files yourself.
