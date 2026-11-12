# Analyser

Local web tool for the test task "What to improve in a car voice assistant" (see `assistant-test-20pct-users/TASK.md`).
It imports the supplied history sample into SQLite and shows two research cards with links to the source records.

## Run

Python 3.12, no other services. Run from the `analyser/` directory.

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python scripts/import_data.py        # JSON -> data/app.db
uvicorn app.main:app --reload        # http://localhost:8000
```

`import_data.py` reads `../assistant-test-20pct-users/data/threadhistories_20pct_users.json` by default
(`--src` and `--db` override the paths). It streams the file and writes rows with `INSERT OR REPLACE`
by the original `id`, so importing the same file again does not duplicate anything. After the import it checks the
numbers against `data/dataset-profile.json` (260 232 records, 6 875 with `deletedAt=null`, 999 keys, 130 934 / 129 298 by role).
Measured import time on the development machine: about 6 s (first run) and 5 s (repeat).
Restart the server after a re-import: the card calculations are cached in memory.

## Storage

SQLite `data/app.db` (not committed). Table `records` keeps every source field under its original name; dates stay as text,
quality and type fields stay text because their scales are undocumented. `records_fts` is an FTS5 index over `text`.
The browser only gets pages of 50 rows; the JSON is never sent to it.

## Pages

- `/` — cards, data quality summary, scope switch (whole corpus / `deletedAt=null`).
- `/cards/need`, `/cards/hypothesis` — research cards. Numbers are recomputed for the chosen scope; the most active key can be excluded.
- `/matches` — all records matched by the card rule, with filters.
- `/records` — text search and filters (period, role, `userLanguage`, `deletedAt`), `/records/<id>` — one record with its time context, `/go?id=` — jump to an id.

Time context = 5 nearest records before and after with the same `usersid_hash` ordered by (`createdAt`, `id`). It is not a confirmed dialogue.

## Code

- `app/rules.py` — selection rules (body-control commands, repeats), shared by the scripts and the app.
- `scripts/analyze_need.py`, `scripts/analyze_hypothesis.py` — print the card numbers, example ids and robustness checks (seed 20261105).

## Notes

**Established (for this sample, not for all users):**
- Voice control of windows, curtains, hatch and trunk is a regular request in both languages: 4 683 user messages from 616 keys (3.6% of user messages), 2 929 in `ru-RU` and 1 708 in `uz-UZ`. The count is a lower bound.
- After a reply without an action code the same command is repeated within 120 s more often (18.2%, 170 commands) than after a reply with one (6.9%, 4 431 commands). The gap holds when the most active key is excluded and when replies with a code inside the text are excluded.

**Still a hypothesis:**
- A repeat is a signal, not proof that the command failed. Whether an empty `actions` means "not executed" needs device logs or documentation of the codes.
- The no-action group is small (170); the whole-corpus result does not carry over to the `deletedAt=null` scope (3 such replies), where the card says there is not enough data.
- The `ru-RU` and `uz-UZ` gaps differ, the reasons were not investigated.

**Not done:**
- No automated tests; the rules were checked by hand on samples.
- Only two cards; timing fields (`timeSTT`, `timeGPT`) and `stt_quality` / `ai_quality` were not analysed because their units and scales are unknown.
- The period filter is available on the records page only, not on the cards.

**Use of AI:** Claude Code wrote the import script, the selection rules, the cards and the pages. Results were checked by running the scripts against the database (record counts match `dataset-profile.json`, re-import keeps the count), by reading samples of matched messages, by excluding the most active key, and by a code review in which one claimed bug (FTS query alias) was tested and turned out to be false.
