---
description: Create your profile (or reuse an existing one) and let every Claude Code session read it
allowed-tools: Bash(cd:*)
---
Set up Unified Memory for the user.

1. Ask where the profile should live. Suggest `~/claude-profile`. It must be a new or empty folder, or an existing profile, and it must not be under `~/.claude` (the claude.ai bridge cannot reach folders there).
2. Run `cd "${CLAUDE_PLUGIN_ROOT}" && python3 -m um.cli init --profile "<folder>"` and show its output. It creates a git repository in the account-memory layout and remembers the folder in `~/.config/unified-memory/config.json`.
3. The output ends with an import line starting with `@`. Explain that adding it to `~/.claude/CLAUDE.md` makes every Claude Code session load the profile's index. This is what lets Claude Code use the profile; an optional prompt hook (set `"prompt_hook": true` in `~/.config/unified-memory/config.json`) also adds matching lines to each prompt, but on the project's recall benchmark it showed no measured gain over the index alone. Ask before changing that file. If they agree and the line is not already there, append it on its own line and show the file's last lines. Change nothing else in that file.
4. Tell them how facts get in: `/unified-memory:compile` reads their recent Claude Code sessions and adds what they said about themselves, with a receipt; `/unified-memory:bridge` connects Claude's account memory (chat, mobile) so the two stay in step.

Model calls go through `claude -p` on the user's own plan by default; no API key is needed.
