---
description: Erase a fact from the profile, its records and evidence; lists raw copies left in other apps
argument-hint: <value to erase>
---
The user wants to erase "$ARGUMENTS" everywhere this plugin keeps it. Erasing cannot be undone. First say what will happen: every profile line containing that text is removed, with its lineage, answers and evidence; raw copies in other apps are listed, not deleted; git history keeps the value unless they also ask to purge history, which rewrites the profile repository. Ask them to confirm. Only after they confirm, run `cd "${CLAUDE_PLUGIN_ROOT}" && python3 -m um.cli erase --value "$ARGUMENTS" --yes` (add `--purge-history` only if they asked for it) and report the output.
