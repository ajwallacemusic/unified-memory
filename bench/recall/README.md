# Recall benchmark data

Does Claude Code know facts about its user when those facts sit in a stored profile? This folder holds a
profile, questions that can only be answered from it, and prompts where nothing from it should be used.

## The person

Wren Halvorsen is fictional and is not based on anyone. She is a 36-year-old staff backend engineer at
Quillhaven, an invented freight-routing software company, and works remotely from Minneapolis, where she
moved from Madison in August 2026. She lives with her husband Idris, a chemistry teacher, their
seven-year-old daughter Linnea and a retired racing greyhound. The profile covers her job and its main project,
an open-source tool she maintains, a house and a kitchen remodel, two trips, a notebook-making side business,
hobbies (running, cello, board games, gardening), everyday routines, and the people around her. The company,
the side business and every private individual are made up; cities, public products and published books are
real.

## Files

`profile/` mirrors the layout of Claude's account memory: `profile.md` (8 core lines), `areas/` (10 files),
`topics/` (15) and `people/` (8); 34 files and 271 fact lines in all. Every file starts with

    ---
    name: <slug>
    description: <one line, written like a person's index note>
    ---

followed by fact lines of the form `- [stated] <fact>`. A few end with the date they were stated, such as
`(2026-11-02)`. The profile is written as of mid-November 2026.

`questions.jsonl` has 90 rows:

    {"id": "q001", "split": "dev", "kind": "direct", "question": "...", "answer_terms": ["..."], "file": "topics/x.md"}

- `kind`: `direct` (27) reuses the fact line's key words. `paraphrase` (45) asks for the same fact without
  them: synonyms, an indirect description, or the need behind the question. `multi` (18) needs facts from
  two files, and its `file` is a list.
- `split`: `dev` or `test`, 45 each, alternating within each kind (direct 14/13, paraphrase 22/23, multi 9/9).
- `file`: the profile file or files that hold the answer.

`offtopic.jsonl` has 40 rows, `{"id": "o01", "prompt": "..."}`: coding tasks, repo chores, shell and general
questions where nothing personal is needed. About half share an everyday word with a profile line (release,
branch, budget, trip, kitchen, Friday), which is where a word-matching retriever goes wrong.

## Scoring

An answer is a hit if any of the question's `answer_terms` appears in it, ignoring case. The terms are short and
distinctive. `um.bench.recall_data.validate` checks that each term appears verbatim in the cited file, does not
appear in the question, and, for `direct` and `paraphrase`, appears in no other profile file.

Limits of this scoring:

- It is a string match. A correct answer worded differently from the profile is a miss, so the questions mostly
  ask for names and plain numbers and avoid dates.
- A few terms could be guessed without the profile (an editor, a keyboard layout). Run the questions with no
  profile to measure that rate before reading the other results.
- For `multi`, a term comes from one of the two files; the question is written so that finding it takes the
  other file, but the match itself does not prove both were used.

## Who wrote it

Claude (Fable 5.2) wrote the profile, the questions, the answer terms and the off-topic prompts in one
session in November 2026. No person wrote or checked the labels.

## Implicit set

`questions.jsonl` asks about Wren directly, and Claude Code opens the profile when asked about its user.
`implicit.jsonl` measures the other case: an ordinary task that never asks about her, where one stored fact
should change the answer. A reply that ignores the fact is still a plausible generic reply; it just clashes
with the fact (the wrong shell, a dish someone at the table can't eat, a meeting in a blocked slot).

It has 40 rows:

    {"id": "i01", "split": "dev", "prompt": "...", "file": "topics/x.md", "fact": "- [stated] ...", "check": "..."}

- `prompt`: a request Wren would type (draft, write code, plan, schedule, recommend, cook, buy, reply). It
  does not state the fact or use its distinctive words.
- `file` and `fact`: the profile file and the one fact line, verbatim, that the reply should reflect. The 40
  facts are all different and come from 28 files.
- `check`: a yes/no question about the reply alone. "Yes" means the reply respected or used the fact.
- `i01` to `i20` are work and coding tasks; `i21` to `i40` are life tasks. `split` alternates, so `dev` and
  `test` each hold 10 of each.

Scoring: a judge model reads the reply and answers `check`; nothing is string-matched. Run the set with no
profile first, because some checks can come out "yes" by chance.

Limits:

- Where the fact is a scheduling rule, the prompt has to name the day or date that collides with it (i09, i10,
  i14, i18, i28), and a few prompts name the person or subject the fact is about (i16, i17, i37).
- Some replies can pass through a different profile fact: a vegetarian menu passes i22 without the line
  about Idris.
- Each check covers one fact, though several prompts touch more than one.

Claude (Fable 5.2) wrote the prompts, picked the facts and wrote the checks in one session in November 2026.
No person checked them. Results: docs/RESULTS.md.
