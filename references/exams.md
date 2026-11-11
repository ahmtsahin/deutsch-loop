# Practice exams: the writing part

The learner writes the writing part of a German exam under its real conditions: its time limit, its task types, and its rating scheme. You write new tasks and rate the texts. The engine keeps the clock, counts the words, turns your ratings into points with the exam's own table, applies its knock-out rules, and keeps the history. The result is a practice estimate, never an official score or a prediction.

Requests such as „Goethe B1 Schreiben üben", “telc B1 yazma sınavı denemesi yapalım”, „Prüfungstraining", or “DTZ writing practice” select this mode. It skips onboarding, the board, and the opener exercise.

## Which exams

```text
python <skill-root>/scripts/deutsch_loop.py exam-formats
```

Read it once per conversation. It lists five formats: `goethe-b1`, `goethe-b2`, `telc-b1`, `telc-b2`, and `dtz` (Deutsch-Test für Zuwanderer). Each carries its minutes, its tasks with a `brief`, the criteria with a rating `guide`, the point table, its rules, and the published documents the numbers were read in.

- The learner did not name an exam: ask one short question, exam and level, and offer these five.
- Another exam (TestDaF, DSH, ÖSD, Goethe C1, telc Beruf) or another part (reading, listening, speaking): say that it is not available. Offer the closest format only as what it is; never present one exam's scheme as another's.
- A real exam date belongs in the learner's `goal` (`init --goal`), not in a mission: missions plan conversations.

## Write the tasks, then start the clock

1. Write one new task for every task of the format, in German, as the real paper words it: the situation, the content points as bullets where the `brief` asks for them, the requested length where the format states one, and its reminders such as salutation and closing. Number them „Aufgabe 1", „Aufgabe 2". Where the brief asks for a choice (`telc-b2`, `dtz`), put both alternatives, A and B, into the one task text.
2. Invent the situations yourself. Never reproduce a task from a published model test, and never reuse one from an earlier exam; the engine refuses a task it has seen. Use what you know about the learner's life without inventing personal facts.
3. Say in one or two lines, in the explanation language: how long they have, that there is no help and no correction until they hand in, that they send each text with its task number, and that „Abgeben" ends the exam.
4. Start the exam and show its card and tasks in the same response:

```text
python <skill-root>/scripts/deutsch_loop.py exam-start --exam goethe-b1 --task 'Aufgabe 1. ...' --task 'Aufgabe 2. ...' --task 'Aufgabe 3. ...'
```

The clock starts with this command, so run it only when the tasks are ready and nothing else needs asking. Show the returned `card` exactly as printed, in a code block, followed by the task texts exactly as you passed them. Task texts are your own words: keep quotation marks out of them, as for every text you write yourself.

## While the clock runs

- Give no hint, correction, word, translation, or comment on a text, and do not praise its content. The learner may ask; answer once that the exam gives no help. If they insist and you help anyway, pass `--support hint` on their next text, or `--support shown` when you supplied wording. The result then says „mit Hilfe".
- Store every text verbatim as it arrives:

```text
python <skill-root>/scripts/deutsch_loop.py exam-submit s_... --task 1 --text '...'
```

  For a long text or one with quotation marks, write it unchanged to a file in a writable folder and pass `--text-file <path>` instead of `--text`. Split a message that holds several tasks and store each one.
- Reply with one neutral line: which task arrived, the `words` the engine counted, the time left from `remaining_seconds`, and the tasks still open. Take every time from the output and never estimate one.
- A newer text for the same task replaces the earlier one until the exam is handed in.
- `time_is_up` means the deadline has passed. Say once that the paper would now be collected and ask for what they have. A text that arrives later is stored and marked late.
- The clock cannot pause. If the learner wants to abandon the exam, `exam-cancel s_...` takes it out of the history; its tasks stay used.
- „Abgeben", „fertig", “bitti”, or “done” hands the exam in: go on with the next section.

In a new chat, `recap.active_exam` names an exam that is still open. Read `exam-show <session-id>`: with `next_action: wait_for_texts`, show the time left and the saved tasks (`session.tasks[].prompt`) and continue; with `prepare_report`, the texts are handed in and the report is still owed.

## After the hand-in

Do these in order, then show the report in the same response. Run each command on its own and written out in full, with the IDs typed in: a command that sets shell variables or chains several calls does not match the host's permission rules and is refused.

1. **Close the exam.** `exam-stop s_...` freezes its time. Its length is measured to the last text, not to this command.
2. **Record the mistakes.** Every confirmed error goes to its root cause, linked to the text it came from:

```text
python <skill-root>/scripts/deutsch_loop.py record --session-id s_... --turn-id t_... --original '<the whole sentence, verbatim>' --corrected '...' --mistake-id m_...
```

   The turn ID of a task's text is `utterance.id` from `exam-submit`, or `session.texts[].turn_id` from `exam-show`. The [correction protocol](correction-protocol.md) applies unchanged: the smallest correction, one record per root cause in a sentence, a catalog key and a category from the [taxonomy](error-taxonomy.md) for a new pattern, and nothing recorded that you are not sure of. When one sentence holds two errors, record it once per pattern, and pass the same fully corrected sentence as `--corrected` both times: the report prints that correction, and it must not still contain the other mistake. Unlike a scene, record every confirmed error; the report shows up to six patterns and counts the rest.
3. **Log what went right.** When a text uses an active tracked pattern correctly, `observe m_... --context '<that sentence>'` once per pattern.
4. **Rate each submitted task** with the criteria and bands of `rubric` in the `exam-stop` output:

```text
python <skill-root>/scripts/deutsch_loop.py exam-score s_... --task 1 --band erfuellung=B --band kohaerenz=B --band wortschatz=C --band strukturen=C --note '...'
```

   Rate every criterion on its own evidence, with its `guide`. Between two bands, take the lower one, as a rater does. The `--note` is one or two sentences in the explanation language that name what the text does: which content points it handles and what holds a band down. It appears in the report. Apply `rubric.tutor_rules` yourself, such as telc's off-topic rule. The engine computes the points and applies the exam's knock-out rules; it also refuses a rating that contradicts what it measured, such as a Goethe text under half the requested length rated above E in Erfüllung. A task without a text needs no rating and scores 0.
5. **Finish and show the report.** `exam-finish s_...` returns `learner_message`. Put it in your final response, exactly as printed, in a code block. `response_required: true` with `next_action: present_report` means the report has been saved, not shown.
6. **Add at most four lines** in the explanation language: the one or two changes that would raise the score most, each tied to a criterion and to a sentence of theirs, and what happens next: the recorded patterns return in reviews from tomorrow. Leave commands, retries, and notes to yourself out of the reply.

Never say that the learner would pass or fail the real exam, and never turn the points into a CEFR level of your own. The report already sets the points beside the published threshold and says what it is. Two trained raters score a real paper; you are one model.

## Repairs and history

- A disputed correction: `undo <mistake-id>`; the report loses that entry.
- A disputed rating: `exam-score` again replaces a rating until `exam-finish`. A finished exam's ratings are final; say so and offer another exam on another day.
- If the learner did not see a report, read `exam-show <session-id>` and show its `learner_message` again; `recap.last_exam` names the latest finished exam. Nothing is recorded twice.
- “How did my exams go?”: `exam-list --format text`, shown as printed. An attempt written with help, after the time, or with a task missing is marked as such, and the next report names the previous attempt on its own.
