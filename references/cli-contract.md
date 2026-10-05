# CLI contract

All commands print UTF-8 JSON to stdout regardless of the console code page: on one line when the output is piped to an agent, indented in a terminal. `recap`, `summary`, `due`, `show`, `vocab-due`, `vocab-list`, `roleplay-show`, and `roleplay-finish` also accept `--format text` for a German, human-readable card, `list --format text` prints a table of the pattern keys, and `recap --format card` prints the German board that opens a session. Errors print JSON to stderr and exit with status 2. An error that needs its own handling adds a `code`: `state_not_writable` means the state directory cannot be created or locked, typically because an agent sandbox blocks the folder.

JSON views are sized for an agent's context. List rows (`list`, `recap.board`, `due_patterns`, `next_focus`, `summary` rows) carry the ID, key, German label, status, counts, and schedule. A pattern that an agent acts on (`record`, `grade`, `coach`, `due`, `recap.callback`, repair commands) adds its rule, first and last example, and coaching memory. A word (`vocab-*`, `roleplay-vocab`) carries its term, meaning, latest scene sentence, recent review prompts, and schedule. `--verbose` returns full records with every history on `record`, `grade`, `coach`, `due`, `undo`, `merge`, `rename`, and `forget`, and adds the rule, examples, and coaching to the rows of `list`, `recap`, and `summary`. `show` always returns the full record.

## State

The state directory is selected in this order:

1. global `--home PATH` argument;
2. `DEUTSCHLOOP_HOME` environment variable, or `DEUTSCHDNA_HOME` from before the project was renamed;
3. `~/.deutschloop`, or `~/.deutschdna` when only that older folder exists.

The CLI creates `profile.json`, `mistakes.json`, `sessions.json`, and `vocabulary.json` atomically. Each command holds an exclusive lock on the directory (`.lock`) from its first read to its last write, so parallel calls, such as one `record` per pattern of one sentence, wait for each other instead of overwriting each other's changes. A command waits up to 20 seconds for the lock; the operating system releases it if a process dies. They are plain JSON for portability, but integrations must change them only through the CLI, never by hand. Mistake state from schema versions 1 and 2 is upgraded to version 3 on read and persisted on the next write; pattern IDs are kept. Migration cannot recover already-evicted examples.

Each pattern pins its `first_example`, latest successful `helpful_hint`, and latest `learning_proof` independently of the rolling histories (12 wrong examples and 30 events per history). `seen_prompts` and `seen_answers` retain normalized text fingerprints beyond those windows to reject repeated exercises; they are omitted from public output. Exact-text novelty checks ignore casing, punctuation, and whitespace but cannot prove semantic novelty or grade German. The teaching agent must still judge the target structure and whether a task requires a genuinely different production.

Stored times are UTC. Outputs add `*_local` twins such as `seen_at_local`, `next_review_local`, and `last_activity_local` in the machine's time zone, or in `DEUTSCHLOOP_UTC_OFFSET` (for example `+02:00`) when it is set. Day-based values follow the local calendar: streaks, today, yesterday, and days since the last activity. Rendering `summary --format text` records `last_full_profile_at` in the profile.

## Commands

| Command | Purpose |
| --- | --- |
| `init` | Create or update optional profile fields without clearing history. Supports `--goal`, `--explanation-language`, `--starting-point`, `--welcome-shown`, and `--onboarding-complete` as described below. |
| `record` | Add a new root-cause pattern or add a recurrence to an existing one. Use `--mistake-id` to recur a known pattern, or `--category`, `--pattern`, and `--rule` to name one; `--label` sets its German name. The response includes a local `minimality` check of the correction. |
| `observe` | Log a correct, unprompted use of one or more tracked patterns (by ID). |
| `coach` | Store an actual practice attempt (`independent`, `assisted`, `shown`, or `miss`) with its prompt, answer, and any strategy/hint; never changes accuracy or the review schedule. |
| `due` | Active patterns whose `next_review` is at or before the given time, each with its rule, examples, and coaching memory. |
| `grade` | Apply `pass`, `hard`, or `fail` to a due pattern. Requires the actual `--prompt` and `--answer`; records optional `--strategy` and `--hint` for supported attempts. |
| `list` | One row per pattern for `--status active`, `mastered`, or `all`, optionally filtered by `--category`; `--verbose` adds examples and coaching. |
| `show` | One pattern with its full history; `--format text` renders its journey as a timeline. |
| `undo` | Revert the latest `record`, `grade`, `observe`, `coach`, or `merge` on one pattern, including coaching evidence, novelty indexes, and the review schedule. One level deep; undoing the record that created a pattern removes it, and undoing a merge (on the target) restores both patterns and their scene references. |
| `forget` | Delete a pattern and its whole history, and drop it from session references. |
| `merge` | Fold the source pattern into the target: counts add up, histories interleave, the source key becomes an alias of the target. `undo <target-id>` reverts it. |
| `rename` | Change a pattern's key, category, rule, or German `--label`; an old key stays as an alias. Refuses to collide with an existing pattern and points to `merge`. |
| `summary` | The FehlerDNA profile: per-category accuracy, root-cause clusters, weakest and due patterns, streak. |
| `scenarios` | Fifteen roleplay frames with opening lines, example requests, and two variations. Runs without creating or locking learner state. |
| `mission-create` | Save a learner-stated `--goal`, supported `--scenario`, and optional `--deadline`; retries of an identical active goal reuse its ID. |
| `mission-list`, `mission-show` | Active goals by default, or one plan's communication steps, last assessment evidence, local date, pending scene, and `next_action`. `mission-list --status all` includes completed/cancelled goals. |
| `mission-start` | Start its current step or resume an unfinished scene/debrief/assessment. Returns prior actual answers, notes, corrections, and up to three active focus patterns. |
| `mission-assess` | Assess a completed linked scene as `achieved` or `practice`, with required actual `--support`, source `--evidence-turn-id` flags, and `--note`. |
| `mission-undo` | Undo the latest goal assessment, leaving grammar records intact; blocked while a newer scene is unassessed. |
| `mission-update` | Change `--goal`/`--deadline` or `--cancel` an active plan. End and finish an active/debriefing scene before cancelling. |
| `dashboard` | Export a self-contained offline HTML snapshot to `--output` (default `deutschloop-dashboard.html`). `--force` deliberately replaces an existing HTML export. Returns the absolute path, pattern count, frame count, and demo flag. Leaves learner JSON, profile-display markers, and schedules unchanged. |
| `recap` | The session opener: resumable `onboarding`, activity in the last `--days` (default 7), totals, `schedule`, `full_profile_due`, `board` with `board_more`, the rendered `card`, the `callback` pattern (the first due one, else the most recent mistake, with `reason`), and `needs_label` (active patterns still shown by their English key). |
| `speak`, `roleplay-start` | Start an uninterrupted scene with a target duration, input mode, relevant goal, and optional focus. `speak restaurant` defaults to five minutes. |
| `roleplay-turn` | Store one actual learner/partner utterance; returns the turn ID, elapsed time, learner-turn count, and `should_close` cue without grading. |
| `roleplay-stop` | Freeze duration and move the scene from `active` to `debriefing` before analysis. |
| `roleplay-vocab` | Add a useful term, meaning, and actual source turn to a stopped scene (at most five terms); the word also enters the word deck. |
| `vocab-due` | Deck words whose `next_review` is at or before the given time. |
| `vocab-grade` | Apply `pass`, `hard`, or `fail` to a due word. Requires the actual `--prompt` and the learner's `--answer`; `--correction` for a fail. |
| `vocab-list` | The word deck (`--status active`, `mastered`, or `all`) with an `overview`; `--format text` prints it as a German card. |
| `vocab-undo`, `vocab-forget` | Revert a word's latest grade or scene addition; remove a wrong word from the deck and its scene reports. |
| `roleplay-finish`, `roleplay-show` | Complete/inspect a scene; a finished scene exposes a grounded debrief, also available with `--format text`. |

Commands that record timestamps accept `--at ISO-8601` for deterministic integrations and tests. Use `python scripts/deutsch_loop.py COMMAND --help` for exact arguments.

## Speaking scenes and debriefs

`speak <scenario> [--minutes 5] [--input-mode text|transcript]` uses the same engine as `roleplay-start --scenario ...`. It accepts the five canonical scenarios plus `work`, `doctor`, `housing`, and `everyday` aliases. Minutes must be 1–60. This does not register a new host slash command or start audio capture.

`roleplay-turn <session-id> --speaker learner|partner --text "..." [--event-id ...]` stores the exact utterance and timestamp. Explicit event IDs are idempotent; reusing one for different content is rejected. Without an ID, only an immediately repeated identical speaker/text within five minutes is treated as a retry. Distinct actual messages should have distinct stable IDs, even if their text matches. Timestamps cannot precede the start or last turn.

A standalone learner control such as `Bitir`, `BİTİR!`, `bitirelim`, `konuşmayı bitir`, `rollenspiel beenden`, or `stop roleplay` ends the scene instead of becoming a learner utterance. It returns `status: scene_ended`, `control: end_scene`, and `next_action: prepare_debrief`; duration is frozen and answer counts are unchanged. If the scene was already complete, it returns the existing debrief with `next_action: present_debrief`. A quoted word inside a sentence or a partner's line is not an end control. Other natural-language stop requests are handled by the teaching agent through `roleplay-stop`.

Turn results expose elapsed wall-clock seconds, automatically counted learner turns, local start/end timestamps, and `should_close`. The cue turns true on a logged/read turn at or beyond the target; no background alarm or audio-duration measurement exists. `recap.active_roleplay` identifies the latest active/debriefing scene for resumption. `roleplay-show` returns the actual local utterances; an unfinished scene has `debrief: null`.

`roleplay-stop` freezes `ended_at`, duration, and learner turns and enters `debriefing`. Stop retries preserve the original timestamp. Later analysis time is excluded. Feedback can then be recorded using `record --session-id ... --turn-id ...`; both flags are required together and the original must occur verbatim in the referenced learner turn. Partner lines cannot become learner errors. Linked records use the turn timestamp, and identity includes the scene, turn, and pattern. Session evidence is retained separately from the 12-example rolling history, so retries and recurrence counts remain accurate after trimming. The agent should process occurrences chronologically. Transcript mode rejects spelling and punctuation categories; the agent must also resolve uncertain speech recognition.

`roleplay-vocab <id> --term "reservieren" --surface "reserviert" --meaning "rezervasyon yapmak" --turn-id ...` is allowed during debriefing. Surface defaults to term and must appear as a complete word/phrase in an actual partner or learner utterance. The agent judges the lemma and translation; the engine checks the source. Repeated terms are ignored and at most five are kept. These are scene vocabulary, not proof that a term was new to the learner. Each saved term also enters the word deck; see **Word deck**. The result reports `deck: added` for a new card or `deck: known` when an earlier scene already added the word, plus the `word` itself.

`roleplay-finish` completes the scene and derives a debrief from linked evidence. It counts distinct root-cause occurrences per learner sentence and shows up to three correction patterns, prioritizing previously tracked and recurring patterns. A known pattern may have one occurrence in this scene; lifetime totals are never substituted for the scene count. The report includes vocabulary and observed recurrences. Standalone mistake IDs without linked evidence do not create corrections. No evidence means “no confirmed errors saved,” not perfect performance. `undo` of a linked record removes that feedback; `merge`, `rename`, and `forget` repair references. The transcript remains the actual conversation even if an error classification is later withdrawn.

Finished scenes are idempotent and retain the stopped duration; all later feedback/turn writes are rejected. Legacy sessions without utterances still accept supplied `--turns` and `--duration-seconds`; provided duration is labelled as provided. Scenes with actual utterances reject mismatched turn counts and duration overrides. Duration is always labelled scene duration, never time spent speaking.

Completed `roleplay-show`, `roleplay-finish`, and repeated end controls also return `learner_message` (the full text report), `response_required: true`, and `next_action: present_debrief`. The JSON default therefore supplies ready-to-display text, not only internal records. Active/debriefing sessions have no prepared learner message and return `continue_scene`/`prepare_debrief`. These fields describe the remaining assistant action; they do not prove the user has seen anything. The assistant must include the report in its final visible response, unless the user explicitly declined feedback. Printing terminal output or saving the session does not satisfy that requirement. `recap.last_roleplay` locates the latest completed session for a requested missing report; reopening it is read-only and does not re-record mistakes.

## Offline dashboard export

`dashboard` uses a bundled `scripts/dashboard.html` template. It reads saved patterns without initializing or writing learner JSON; a missing home produces an empty view without creating that directory. Existing homes use the ordinary state lock for a consistent read. The output must end in `.html` or `.htm`, cannot overwrite the source template, and refuses existing files unless `--force` is supplied.

The embedded projection contains the learner's supplied name and level, pattern examples, helpful hints, current schedule, retained timeline events, historical learning proofs, active/completed missions and their latest evidence, and the roleplay catalog. Undo snapshots, novelty fingerprints, and unrelated roleplay transcripts are excluded. Learner strings are JSON-escaped before embedding and rendered as text in the browser; the page makes no network requests. Dates use the engine's local offset rather than the browser's time zone.

`--at` changes the clock used for due markers; it is not historical reconstruction. The demo renderer captures separate snapshots as its events happen instead. Neither exporting nor opening a view counts as practice, marks a profile as shown, or changes the review ladder. A saved milestone with a later error is explicitly historical; it does not claim the pattern is currently mastered.

## Continuing missions

`missions.json` is created only when a goal is saved; it has its own schema version 1 and does not migrate existing learning files. A mission stores its stated goal, scenario, date, three frozen communication steps, current index, status, and assessments. Each assessment retains actual learner turn IDs, verbatim evidence, the help used, and the teaching agent's note. Scenes hold `mission_id`, `mission_step_id`, and repairable `mission_focus_ids`. Scene creation and goal assessment each write one document atomically, so an interruption can resume an unassessed completed scene without creating a second attempt. All CLI mission commands use the ordinary state lock.

`--deadline` accepts `YYYY-MM-DD`, today/tomorrow, or a weekday in English/German/Turkish. It resolves on the engine's local calendar; a bare weekday includes today. `days_remaining` and `overdue` are computed from that calendar, with no guessed event time or automatic completion. An empty update clears the date. `recap.missions` exposes active preparation for a new chat; explicit learner requests take precedence over automatic opener exercises.

`mission-start` selects active errors from the prior completed scene before other due/recurring patterns. Its adaptation includes the actual previous evidence, support, note, and current scene corrections. A `practice` result keeps the step and uses a new opening with a repair policy; an `achieved` result advances one communication step and adds a challenge. Unknown personal facts and learning styles are never inferred.

Record actual partner help with `roleplay-turn --support hint/shown`; only partner turns accept these labels. `mission-assess` checks ownership and completion of the linked scene, real learner evidence turns, scene/assessment chronology, and recorded help. `achieved` rejects a hint/supplied answer even if the assessment claims `none`. Exact retries are idempotent; a changed judgment requires undo. A new pending scene blocks undo of the prior assessment so its sources cannot be reassigned to another step.

The tutor judges the communication criteria; the engine does not grade German or validate their semantics. Both `achieved` and `practice` are goal assessments, not grammar-review grades. They leave learning counts, helpful hints, mastery, and review dates untouched. Three achievements complete this practice plan, never a proficiency/readiness certificate. See [the mission protocol](missions.md) and [learner guide](../docs/missions.md).

## Onboarding and optional profile fields

The agent runs these commands; learners do not need to fill a profile or learn CLI syntax. See [onboarding](onboarding.md) for the conversation flow.

```text
init --explanation-language tr --welcome-shown
init --starting-point beginner
init --onboarding-complete
```

- `explanation_language` is the support-language preference, separate from the learner's stated `native_language`. An empty value clears the override. Onboarding falls back to a stated native language when no preference is stored.
- `starting_point` accepts `beginner`, `some`, `comfortable`, or `unsure`. It never changes `level`; only an explicitly supplied `--level` does that. Name, level, native language, and goal remain optional.
- `--welcome-shown` stores `welcome_shown_at` once, when the short introduction is shown. It does not count as learning activity.
- `--onboarding-complete` stores `onboarding_completed_at` once, after the learner's first actual German production. It counts as activity even when there is no error, but adds no mistake, correct-use count, review pass, or mastery score. Retrying the flag does not move the first-practice timestamp. The first `record` for a learner with no tracked patterns stores the same timestamp when it is missing and returns `onboarding: completed`; histories that already have patterns are left as they are.
- Ordinary `init` updates preserve these fields. Optional `--goal` stores a stated real-life goal; an empty value clears it.

`recap.onboarding.stage` is `welcome` for an untouched learner, `choose_start` after the introduction, `first_practice` when a starting preference or explicit A1–C2 level is known, and `complete` after a first practice or any existing learning activity. Existing learner histories therefore skip the new tour. Completion works without an error; do not route solely from the existence of mistakes. `onboarding` also exposes the support language, starting point, and local welcome/completion timestamps.

Do not show an empty board or an initial percentage. For newly onboarded learners, the automatic full profile waits at least seven days after completion, requires tracked patterns and activity after that baseline, and then follows the usual weekly policy. Explicit progress requests are always allowed.

## The record response

- `status`: `recorded` (new pattern), `updated` (recurrence), or `duplicate` (nothing changed).
- `resolved_by`: how an existing pattern was found: `mistake_id`, `id`, `pattern_key`, or `alias`.
- `recent.occurrences`: errors on this pattern in the last 7 days, including this one.
- `previous` (recurrences only): the pattern's `last_seen`, `review_step`, `status`, and `occurrences` before this error, plus `first_example`, `first_example_is_original`, and `last_example`. The first example is pinned; if the flag is false, migration could retain only a later example. Use that example's own date for the callback.
- `similar_patterns` and `hint` (new patterns only): existing patterns whose key is at least 72% similar and differs only by added words or a near-identical spelling, with a ready `merge` command. The same template with another word (`mit + dative` and `bei + dative`, `der-word` and `ein-word`) is a different pattern and is not listed.
- `onboarding` (first record only): `completed` when this record finished the learner's introduction.
- `minimality`: `status` (`minimal` or `possible_rewrite`), `changed_token_ratio`, and the token `changes` between the original and the correction. A rewrite means the correction changed more than grammar required. No tool checks whether the correction is right. Validator fields from the removed LanguageTool check (`verification_history`, `verification_status`) are dropped when state is read and disappear from disk with the next write.
- `mistake`: the pattern with its rule, first and last example, and coaching; `--verbose` returns the full record.

## German labels

Pattern keys stay English and stable; learners see German names. Every row and pattern in the output carries `label` and `label_source`:

- `custom`: set with `record --label` or `rename --label`.
- `catalog`: a built-in name for a catalog key, such as `Verb an Position 2` or `Nomen großschreiben`.
- `rule`: derived from the key, such as `Pizza ist feminin`, `sich treffen (reflexiv)`, `weil: Verb ans Ende`, or `warten auf + Akkusativ`.
- `key`: no German name is known yet; the key itself is shown. Give the pattern a label with `rename --label`.

Labels are at most 60 characters; the board shows up to 36 of them. Text views (`card`, `summary`, `show`, `due`, `recap --format text`) use labels; `list --format text` shows the keys.

## The observe response

Each entry in `results` carries `status` (`observed`, `observed_and_advanced`, `duplicate`, or `seen`), the new `correct_uses`, the schedule, and `last_mistake`: the latest stored wrong sentence, for the before-and-after line. A `duplicate` or `seen` entry carries only the ID, pattern, and status, because nothing was counted.

`--context` must contain the actual unprompted production. A sentence the pattern already knows, as an earlier answer, a correction, or an earlier use, returns `seen` and counts for nothing, in a later session too: an answer the learner gave after a hint does not become unaided evidence when they send it again. Prompted exercises belong to `coach` or `grade`, even when the answer is correct.

## Coaching and transfer evidence

```text
coach <id> --outcome assisted --prompt "..." --answer "..." --strategy "Kasusfrage" --hint "Mit wem?"
coach <id> --outcome independent --prompt "a new situation" --answer "a new answer"
```

Both `--prompt` and `--answer` must be real and nonempty. `assisted` and `shown` require both a strategy and the exact hint; `independent` refuses hints, reused prompts, and already-seen answers. `shown` means the coach supplied the answer and the learner repeated it. `miss` records an unsuccessful attempt, with strategy/hint if used, but does not record another error: use `record` once for a real new wrong production, or rely on the error already recorded by `grade fail`.

`coach` returns `status: coached` or `duplicate`, the attempt, and the pattern. Pattern views expose `coaching.helpful_hint`, `coaching.last_attempt`, and `coaching.learning_proof`; these are available to the next session via `recap.callback`, `due`, `show`, and `list --verbose`. Only `assisted` successes update the helpful hint. `grade hard` with a strategy/hint stores the same evidence atomically; hard reviews without a hint only record hesitation.

`coach`, `grade`, and each `observe` result return a top-level `learning_proof` for a newly detected transfer, otherwise null. It requires a new unaided answer on a later local day after assisted success, with no intervening recorded recurrence. The proof contains `with_help` and `independent`, each with the stored sentence and `at_local`; the latter distinguishes `practice`, `review`, and `spontaneous`. The same support event produces a milestone once. The stored proof survives history trimming, merge, and rename; undo restores it and forget deletes it. It is historical evidence about one pattern, not a CEFR score or a causal claim about the hint.

## Word deck

Every word saved with `roleplay-vocab` becomes a card in `vocabulary.json`. When that file does not exist yet, the CLI builds it from the vocabulary of all earlier scenes, so words saved before the deck existed are reviewed too. A card is identified by its term without a leading article, with ä/ö/ü/ß spelled out, and by whether it is a noun: a leading article or a capital first letter marks one. So `die Reservierung`, `Reservierung`, and `RESERVIERUNG` share one card, and `die Straße` and `Strasse` do too, while `der Morgen` and `morgen`, `das Essen` and `essen`, or `schon` and `schön` do not. A term with an article replaces the same bare term on its card (`Reservierung` becomes `die Reservierung`); the first meaning stays. A word met again in a later scene gains that scene as a source (the latest five are kept) and keeps its schedule.

Word reviews use the pattern ladder: the first review is one day after the word was met, and each pass moves one step through 1, 3, 7, 14, 30, and 60 days. The sixth pass marks the word `mastered`. `hard` schedules another attempt in one day without changing the step. `fail` returns the word to step 0, due again in one day, and counts it as `wrong`.

`vocab-grade` rejects words that are not active and due, missing prompts or answers, and previously used prompts. A pass also rejects a sentence already seen: the scene sentence the word came from, an earlier answer, or a correction. An identical retry within five minutes returns `status: duplicate`. The agent gives the meaning and a new situation, and judges whether the learner's sentence uses the word correctly; the engine cannot grade German.

`vocab-undo` reverts one change of one word: the latest grade, or its addition from a scene, which also removes it from that scene's report. `vocab-forget` deletes the card and removes the word from every scene report. `recap.vocabulary` and `summary.vocabulary` give `total`, `active`, `mastered`, `due_now`, and `next_local`. Once the deck has words, `recap --format card` and `summary --format text` add one **Wortschatz** line, and `recap --format text` names the due words. `recap.word_reviews` counts word reviews in the recap window by result, and word reviews count as activity for streaks.

`vocab-list` rows carry the ID, term, meaning, status, due flag, step, and next review; `--verbose` returns full cards with sources and review history. `vocab-due`, `vocab-grade`, and `roleplay-vocab` return the working view with the latest scene sentence and recent prompts. In a debrief, each scene word carries `review`: `active` while its card is reviewed, `mastered` when an earlier scene already mastered it. A `roleplay-vocab` retry returns `status: duplicate` and completes a card that an interrupted earlier call did not write.

## Pattern identity

A pattern's ID is a hash of its category and its *pattern key*. The key is the normalized pattern text: lower-cased, whitespace-collapsed, punctuation removed, with `Dativ`, `Dat`, `dat.` → `dative`; `Akkusativ`, `Akk`, `acc` → `accusative`; `Nominativ` → `nominative`; `Genitiv` → `genitive`; and `governs`, `takes`, `requires`, `needs` → `+`. The tokens `case`, `kasus`, and `the` are dropped. So `mit + Dativ`, `mit+dat.`, and `mit governs the dative` all resolve to `mit + dative`.

Resolution order on `record`: exact ID, then the same key in any category, then any alias created by `merge` or `rename`. A brand-new pattern is created only when nothing matches; the response then lists `similar_patterns` whose key differs only by added words or spelling, because the CLI cannot tell a respelled key from a new one on its own.

## Idempotency

- `record` never counts the same `--event-id` twice while that example is stored (the 12 most recent per pattern).
- `record` without `--event-id` derives one from the original and corrected text; an identical call within 30 minutes returns `status: duplicate` and changes nothing. A retry after a crash therefore cannot double-count.
- `grade` ignores an identical result/prompt/answer/support/correction retry within 5 minutes, before checking due time. A different answer is not a retry.
- `coach` ignores the same outcome/prompt/answer/strategy/hint within 5 minutes.
- `observe` ignores a repeat with the same `--context` within 5 minutes (`duplicate`); a later repeat returns `seen` and counts for nothing.
- `roleplay-finish` on a completed session returns it unchanged.
- `undo` works once per change: a second `undo` on the same pattern fails, and `rename` clears the snapshot. `merge` stores a snapshot of both patterns on the target. Full responses show `undo_available` instead of the stored snapshot.

## Review schedule

The successful review sequence is 1, 3, 7, 14, 30, then 60 days. Recording a recurrence or grading `fail` restarts the sequence at one day. `hard` schedules another one-day attempt without changing the step. Passing the final step marks the pattern `mastered` and sets `mastered_at`; a later recurrence reactivates it and records `reactivated_at` and `previously_mastered_at`.

`grade` rejects patterns that are not active and due, missing prompts/answers, and previously used prompts. A pass also rejects an answer already seen in a correction, exercise, or observation, and refuses a supplied hint. Use `coach` for practice before the due time, or for a shown answer. Never shift `--at` or add cosmetic changes to bypass these checks.

`grade` and `coach --outcome independent` also return `variety`: null, or the earlier prompt or answer of this pattern that shares at least 60% of its words with the new one (`field`, `similar_to`, `at_local`, `similarity`). It does not block the grade. It means the task reused a sentence frame, such as `Die Planung ist wichtig.` after `Die Einladung ist wichtig.`, which tests that frame rather than transfer to a new situation.

`observe` with a fresh production on an active pattern that is currently due counts as a pass (`source: observed`): a learner who uses the structure correctly in real writing does not need to be quizzed on it that day. On a pattern that is not due, it only increments `correct_uses`. A sentence the pattern already knows does neither.

## Scoring

- `occurrences` (shown as *falsch*): every recorded error, including review failures.
- *richtig*: `correct_uses` plus passes from real reviews.
- `accuracy_percent` = round(100 × (right + 1) / (right + wrong + 2)). The smoothing keeps a single error from reading as 0% and a single pass from reading as 100%.
- A pattern or category is `new` until it has at least one graded review or correct use. Text cards show `neu` instead of a percentage, and the weakest-pattern list skips new patterns: a first text is not a score.
- A category is `weak` when it is not new, its accuracy is below 60%, and it has at least two errors.
- A *cluster* (shown as **Ursache**) is a category with at least two active patterns and three errors among them. Clusters are ranked by how many different patterns in the family failed in the last 30 days (`recent_patterns`), then by recent errors, then by total errors. Breadth outranks depth: four different verb-plus-preposition mistakes say more about the rule than one pattern missed four times. The **Ursache** line states the family's share of all mistakes in the same 30 days (`recent_errors` of `recent_errors_total`).
- `mastery_percent` is the average review-ladder position per category (0–100), kept for integrations.
- `streak_days` counts consecutive local days with any recorded activity, ending today or yesterday.
- `full_profile_due` requires tracked patterns and activity. It uses the last full-profile date, or the onboarding completion date for a new learner, as a seven-day baseline and requires activity after that baseline. Existing histories without either marker retain their first-profile behavior.

Percentages describe tracked patterns only. A category with no recorded mistakes does not appear; it is unknown, not 0%. The text profile shows German category names (`Kasus`, `Präpositionen`, `Endungen`, …); JSON keeps the English category IDs.
