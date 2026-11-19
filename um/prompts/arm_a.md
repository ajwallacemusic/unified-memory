You are doing a clean-up pass over the notes an assistant keeps about one person. The notes are
Markdown files: memory notes with an index, `MEMORY.md`, and possibly other files that also state
facts about the person, such as a skill, an instruction file or a task prompt. You have tools to
view, search, write, edit and delete files. Today's date is {as_of}. If there is an `evidence/`
folder, it holds the conversations since the last pass; read it, but change only the notes.

Read every file before changing anything. Then make the notes accurate as of today:

- Where two notes disagree, work out which one is current from the dates and the wording, and make
  the notes say the current thing once.
- Where a fact changed over time, keep the current value and one short line of history, for example
  `until 2023-05-20: worked at Oakfield`.
- Where the same fact appears more than once in the memory notes, keep one copy in the file where it
  belongs. Copies in a skill, instruction file or task prompt stay where they are but should say the
  current thing.
- Where a note is out of date as of today, such as a plan for a date that has passed, say so in the
  note; do not delete what happened.
- Keep every date that is in the notes. Never invent a date or a fact that is not there.
- If you are not sure a note is wrong, leave it as it is.
- Finish by rewriting each `MEMORY.md` index so it lists every file in its folder with one line
  saying what it covers.

Reply with one line saying what you changed.
