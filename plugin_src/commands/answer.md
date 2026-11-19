---
description: Answer a pending profile question; the answer is kept as something you said
argument-hint: <your answer>
allowed-tools: Bash(cd:*)
---
Run `cd "${CLAUDE_PLUGIN_ROOT}" && python3 -m um.cli answer --text "$ARGUMENTS"` with the user's words exactly as given, quoted for the shell. Report where it was kept.
