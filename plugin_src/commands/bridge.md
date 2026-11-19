---
description: Connect the profile to Claude's account memory (chat, mobile) through a claude.ai scheduled task
allowed-tools: Bash(cd:*)
---
Walk the user through the bridge, one step at a time, waiting for them between steps. The bridge is a scheduled task in the Claude desktop app bound to this Mac. Local code decides what may go into account memory; the task only copies files, checks versions so a chat's edit is never overwritten, pulls memory's changes back, and logs. It starts in propose-only mode, which writes nothing to memory.

1. Prepare the first outbox: `cd "${CLAUDE_PLUGIN_ROOT}" && python3 -m um.bridge.prepare --mode propose-only`. Show what it would push and what policy kept back.
2. Print the task prompt: `cd "${CLAUDE_PLUGIN_ROOT}" && python3 -m um.cli bridge-prompt`. Tell them: in a claude.ai chat in the desktop app, ask Claude to create a daily scheduled task with the profile folder attached, and paste the whole prompt as its prompt. The web form's "Set up manually" has no folder field, so a task made there cannot reach the folder. The desktop app must be open for every run.
3. First run: they run the task once; it asks for folder access on the Mac, and they click Allow once.
4. Review: they read `outbox/PROPOSAL.md` in the profile folder. Then record the review with `cd "${CLAUDE_PLUGIN_ROOT}" && python3 -m um.cli bridge-review --rejected <number of proposed files they reject>`.
5. Going live needs two reviewed propose-only runs in a row with something proposed and nothing rejected; `python3 -m um.bridge.prepare --mode live` refuses until then. Live mode writes to their real account memory, so get their explicit yes before running it, and say that each mirrored file is replaced by the filtered copy.

Never run live mode, delete a memory file, or edit the scheduled task yourself without their yes in this session.
