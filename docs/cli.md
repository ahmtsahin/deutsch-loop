# Using the CLI directly

[Back to the README](../README.md) · [Full command contract](../references/cli-contract.md)

Run these examples from the cloned skill folder.


The agent drives the CLI; you can use it directly too. Every command prints JSON, compact when an agent reads it and indented in your terminal; `show` returns a pattern's full history. `recap`, `summary`, `due`, `show`, `vocab-due`, and `vocab-list` also take `--format text` for German cards, and `list --format text` prints a table of the pattern keys.

```bash
python scripts/deutsch_loop.py init --name "Alex" --level B2 --native-language tr
python scripts/deutsch_loop.py record --original "Ich spreche mit mein Chef." --corrected "Ich spreche mit meinem Chef." --category case --pattern "mit + dative" --rule "mit always governs the dative"
python scripts/deutsch_loop.py summary --format text
```

| Command | What it does |
| --- | --- |
| `recap` | The session opener; `--format card` prints the German board of patterns in progress |
| `record` | File a mistake under its root cause, or count a recurrence; the reply says whether the correction was minimal |
| `observe` | Count a correct, unprompted use of a tracked pattern |
| `coach` | Remember an actual practice attempt and the hint used, without changing the review schedule |
| `due`, `grade` | Spaced-repetition reviews |
| `summary` | The FehlerDNA profile with root causes |
| `dashboard` | Export a portable offline HTML view of your patterns, hints, milestones, and saved timelines |
| `show` | The journey of one pattern |
| `list`, `undo`, `forget`, `merge`, `rename` | Inspect and repair the memory; `undo` also reverts a merge |
| `speak`, `roleplay-start` | Begin a scene with corrections deferred to the end |
| `scenarios` | Fifteen roleplay frames with openings and example situations; does not initialize state |
| `mission-create`, `mission-list`, `mission-show` | Save and inspect continuing preparation for a real-life goal and known date |
| `mission-start` | Start or resume its current adaptive scene |
| `mission-assess` | Record an actual communication-task result using learner turn IDs and help used |
| `mission-undo`, `mission-update` | Repair the latest assessment, change the goal/date, or cancel preparation |
| `roleplay-turn`, `roleplay-stop` | Save actual turns and freeze scene duration before feedback |
| `roleplay-vocab`, `roleplay-finish`, `roleplay-show` | Source-backed vocabulary and the session debrief |
| `vocab-due`, `vocab-grade` | Spaced reviews of the words from your scenes |
| `vocab-list`, `vocab-undo`, `vocab-forget` | Your word deck, and repairs to it |

State lives in `~/.deutschloop`; set `DEUTSCHLOOP_HOME` or pass `--home` before the command to use another directory. Each command locks that directory, so an agent can run several commands in parallel without losing a write. The full contract, including idempotency and scoring, is in [references/cli-contract.md](../references/cli-contract.md).

Export a [visual learning story](dashboard.md), then open the file in your browser:

```bash
python scripts/deutsch_loop.py dashboard --output my-progress.html
```

The export leaves learning records unchanged and works without a server or network connection. Use `--force` to replace an existing HTML export. A missing learner directory produces an empty view without creating memory.

Reviews require the actual new task and learner answer:

```bash
python scripts/deutsch_loop.py grade m_... --result pass --prompt "Dein Verkehrsmittel ist der Bus. Wie kommst du zur Arbeit?" --answer "Ich fahre mit dem Bus."
```

The engine rejects early reviews, reused prompts, copied answers, and passes with hints. Before the due time, use `coach` for practice. Save a learner-stated goal with `init --goal "Morgen möchte ich einen Termin mit meinem Chef klären."`; roleplay combines a relevant goal with a due or active pattern. See [the learning loop](../references/learning-loop.md) for the complete conversation flow.

For a goal across several scenes, use [missions](missions.md):

```bash
python scripts/deutsch_loop.py mission-create --goal "Cuma Almanca iş görüşmem var." --scenario interview --deadline cuma
python scripts/deutsch_loop.py mission-start g_...
```

The engine selects active mistakes from the previous scene before other due patterns and returns actual previous answers and notes for adaptation. Mark real partner help in `roleplay-turn --support hint/shown`; a mission result of `achieved` requires no help and source learner turns. Mission progress is separate from grammar mastery.
