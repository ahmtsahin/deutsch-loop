# Speaking scenes

The learner chooses a situation and talks to a character. Corrections wait until the scene ends. `speak restaurant`, “Restoranda konuşalım”, and “Rollenspiel Restaurant” select this mode. With the installed skill name, the invocation is `/deutsch-loop speak restaurant` in Claude Code or `$deutsch-loop speak restaurant` in Codex. Do not claim `/deutsch` is a registered shortcut; the skill is named `deutsch-loop`.

## “Bitir” means deliver the evaluation

An explicit end request exits character and starts the debrief. Stop asking in-character questions; finish the feedback flow and **show the report in the final assistant response in this same turn**. An acknowledgment such as “Alles klar” is optional, but cannot be the whole response. A report printed by a tool or prepared by background work is not yet a message the learner has received.

After `roleplay-finish`, use `learner_message` as the ready-to-display report. Translate its labels and explanation faithfully when needed. Preserve the actual corrections, vocabulary, counts, and timing basis. `response_required: true` with `next_action: present_debrief` is a handoff to the assistant's final response, not a claim that delivery already happened. If the tool fails, provide grounded feedback from the visible conversation and briefly explain what was not saved. Do not pad a missing report with invented counts.

In voice, make the switch from character to tutor explicit and relay the short evaluation through the active response. Do not end the host voice call unless the learner requested that separately. If they say the report never appeared, reopen this scene with `roleplay-show` and show its existing report; do not restart or record the same errors again. Use `recap.last_roleplay` to find the latest completed scene only when its report is requested and no session ID is in context. An explicit “no feedback” request overrides the default debrief.

## Start immediately

```text
python <skill-root>/scripts/deutsch_loop.py speak restaurant --minutes 5
```

`roleplay-start --scenario restaurant` remains supported. There are fifteen scenarios; `scenarios` returns their openings and example situations. English aliases such as `interview`, `presentation`, `train`, `shopping`, `phone`, and `customer-service` work with `speak`. The default target is five minutes. This is an approximate scene length: time is checked when a turn is logged, so do not promise to interrupt at exactly five minutes or wait on a timer.

The response contains the role, opening, learner goal, and optional `focus_pattern` with coaching memory. Its `personal_goal` is the learner's stated goal. Adapt the scene to relevant goals while respecting the requested situation. Keep the focus hidden; do not force the same grammar pattern into every question. Start without the onboarding questionnaire, a progress board, or the full help menu.

If useful, give one brief line in their explanation language: “Garsonu ben oynayacağım. Düzeltmeleri sona bırakacağım; istediğinde ‘bitir’ diyebilirsin.” Then begin:

```text
Kellner: Guten Abend. Haben Sie reserviert?
```

Use the actual learner's name only if they supplied it. Do not fabricate “Alex:” replies or print both sides as a finished dialogue. Wait for every answer. Speaker labels are optional, but should stay clear and consistent.

## Keep the conversation moving

Log actual utterances as they happen. Use the actual partner line you deliver and the learner's verbatim input:

```text
python <skill-root>/scripts/deutsch_loop.py roleplay-turn s_... --speaker partner --text 'Guten Abend. Haben Sie reserviert?' --event-id message-1
python <skill-root>/scripts/deutsch_loop.py roleplay-turn s_... --speaker learner --text 'Ja wir haben eine reservierung für zwei person.' --event-id message-2
```

Keep the returned turn IDs for the debrief. Use source message IDs when available, or one stable ID per actual message; reuse only for a retry. A repeated sentence in a different learner message is a different turn. The CLI logs text and time without grading it. Keep all local state operations out of the spoken dialogue.

When the partner gives a hint or supplies an answer, mark that actual partner turn with `--support hint` or `--support shown`; ordinary dialogue uses `none` by default. These labels preserve the distinction between help and an unaided mission result. A learner turn cannot carry help metadata. For a concrete real-life goal spanning scenes, use the [mission flow](missions.md) and its saved plan rather than creating unrelated roleplays each time.

- Stay in character and respond to the meaning. After the reservation answer, continue naturally with “Auf welchen Namen?”
- Ask one question at a time. Follow a learner-led change of subject within the scene; rephrase briefly when they seem confused.
- Do not run a visible grammar explanation, ordinary correction, review exercise, or success callback during the scene. Save confirmed mistakes and successes for the end. The general correction and first-practice-feedback rules do not interrupt this mode.
- A message beginning with „Hilfe-Knopf:" comes from the Hilfe button of the [Claude Code companion](../docs/companion.md#hilfe). It is an explicit help request, not a learner turn: do not log it. Answer in role with a small hint rather than a finished sentence, and log that partner turn with `--support hint`.
- Give help when explicitly requested or when meaning is blocked, then resume the role. In the doctor scenario, keep it fictional language practice and resolve potentially harmful misunderstandings.
- A `should_close` response signals that the target time has elapsed. At the next natural stopping point, close the exchange. Honour requests to continue or to stop early. If the learner explicitly stops, leave the role and deliver the debrief, rather than ending with just a character's acknowledgment.
- For an interrupted session, `recap.active_roleplay` and `roleplay-show <id>` provide its status and actual utterances. Resume if that is what the learner wants; a new explicit task takes priority.

Text is supported directly. If the host supplies dictated or transcribed speech, start with `--input-mode transcript`. The skill itself adds no microphone, audio streaming, automatic silence detection, or pronunciation scoring. Do not assess spelling, capitalization, or punctuation from a speech transcript. Ask about ambiguous recognition before treating it as a learner error.

## Freeze the scene, then prepare feedback

At the end of the exchange, before spending time on grammar analysis:

```text
python <skill-root>/scripts/deutsch_loop.py roleplay-stop s_...
```

This changes the session to `debriefing` and freezes its elapsed duration and learner turn count. It includes time spent listening, typing, reading, and waiting; call it **scene duration**, never “you spoke for”. Do not invent a duration or supply an override for a scene with recorded turns.

Review the real utterances. Record confirmed root causes in turn order, once per root cause per actual learner sentence. Use the full original sentence and complete minimal correction as usual. Link every occurrence to its source so repetition counts are session-specific:

```text
python <skill-root>/scripts/deutsch_loop.py record --session-id s_... --turn-id t_... --original 'Wir sind zwei Person.' --corrected 'Wir sind zwei Personen.' --category plural --pattern 'Person plural is Personen' --rule 'Plural: Personen'
```

Use `--mistake-id` for a known pattern. Linked records use the turn timestamp automatically. Ordinary `record` calls without a session link do not contribute to the scene's report. Retries of a linked record do not double-count; a new wrong sentence in another turn does count. Do not record the same occurrence through both `grade fail` and `record`.

If one learner sentence contains several confirmed patterns, pass the same whole original/corrected pair for each. “eine Reservierung” already has a correct article; lowercasing alone does not establish an article error. Never alter or invent the learner's surname. Prefer errors that repeat or affect communication; record only what can be established from the actual language.

For a known pattern used correctly without prompting, `observe --context "..."` can record the success at its turn's timestamp. Targeted and hinted attempts use the [learning loop](learning-loop.md). Keep any resulting comparison for the debrief. A copied supplied answer is not spontaneous use.

## Vocabulary from the scene

Select at most five useful words or phrases actually encountered. Keep articles with nouns and use the learner's explanation language for meanings:

```text
python <skill-root>/scripts/deutsch_loop.py roleplay-vocab s_... --term 'reservieren' --surface 'reserviert' --meaning 'rezervasyon yapmak' --turn-id t_...
```

`--surface` is the actual inflected form in that learner or partner turn. Omit it when the dictionary form appears verbatim. The engine checks the cited form against the stored utterance; the agent judges whether the dictionary form and meaning are appropriate. Do not invent words to fill a list. The report calls these **scene vocabulary**, since it cannot know which words were new to the learner.

A new word also enters the learner's word deck and comes back in spaced reviews from the next day (see **Words from scenes** in the skill). A word already in the deck keeps its schedule, even when it is mastered, and gains this scene as a source (`deck: known`); the report marks mastered words and promises a return only for words still under review. If a word saved in this debrief is wrong, `vocab-undo <word-id>` takes it out of this report and returns its card to the state before this scene: a new card disappears, a known card keeps its earlier meaning and schedule.

## Debrief and finish

```text
python <skill-root>/scripts/deutsch_loop.py roleplay-finish s_... --format text
```

Put that text in the final assistant message. With default JSON output, `learner_message` contains the same report and `next_action` becomes `present_debrief`. Both formats still require the assistant to show the content. Do not treat a successful command or a “worked for …” UI indicator as visible feedback.

The engine counts recorded learner turns, uses the frozen duration, and reports at most three correction patterns. Recurrences show an explicit **in this scene** count and distinguish a pattern known before this scene. Rolling example limits do not erase the linked session evidence. `undo`, `rename`, `merge`, and `forget` update the references so a disputed correction does not stay in the report. Reopen a completed report with `roleplay-show s_... --format text`.

The report is in German by default. For a beginner or a requested support language, read the JSON and present the same facts in that language. Keep it compact: duration, at most three important corrections, useful vocabulary, and a recurring pattern if one was actually observed. Avoid claiming every correction is a “major error” or calling an unchecked scene error-free. Add one short specific success only if supported by the learner's words, and one next challenge if they want to continue. Do not restart a full lesson automatically after “bitir”.

## Scenario intent

- `alltag`: directions, neighbors, appointments, small talk.
- `arbeit`: colleagues, customers, deadlines, polite disagreement.
- `arzt`: describing symptoms and answering questions in fictional language practice.
- `wohnung`: viewing, repairs, landlord questions, moving.
- `restaurant`: reservation, ordering, requests, problems, paying.
- `bewerbung`: introduce yourself, explain an experience, handle a difficult question and follow-up.
- `praesentation`: present a project, explain a term, answer a skeptical question.
- `behoerde`: a fictional municipal-office appointment, missing information, clarification.
- `bahnhof`: a delayed train, an alternative route, a platform or ticket question.
- `einkaufen`: compare options, exchange an item, explain a purchase problem.
- `apotheke`: a fictional request and unfamiliar vocabulary; no treatment, medication, or dose advice.
- `telefon`: make, move, or confirm an appointment over the phone.
- `schule`: a fictional school concern, homework question, agreed next step.
- `hotel`: check in, clarify a booking, explain a room problem.
- `kundenservice`: a fictional delivery or billing problem and a requested resolution.

The catalog supplies a frame, an opening, and two optional variations, not both sides of a finished learner dialogue. [Practice examples](../docs/practice.md) show natural requests for all fifteen frames.
