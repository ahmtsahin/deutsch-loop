# Continuing preparation for real-life goals

A mission remembers a concrete learner-stated goal, its date when known, and a small sequence of communication tasks across scenes and chats. Mission progress is separate from grammar reviews. The model judges the communication goal; the engine checks that the judgment has real scene evidence, tracks help, and advances the plan once.

## Route an actual goal to preparation

An explicit real-life preparation request such as “Cuma Almanca iş görüşmem var” starts a mission immediately, without onboarding or a questionnaire. Match the situation to a supported scenario; `scenarios` lists the frames, openings, and variations. Use `bewerbung` for a job interview and `praesentation` for a presentation. Every scenario has a three-step plan; the interview has its own introduction → difficult question → unexpected follow-up sequence.

Keep the learner's stated goal and personal details. Do not treat a fictional roleplay utterance, a grammar example, or a demo as a real event. Do not invent the employer, job title, career history, family, or an appointment date.

Read `mission-list` before creating a plan. Reuse a relevant active mission when the learner is continuing it; use `mission-update` for a changed deadline or goal. Exact creation retries return `existing`. Start a genuinely new goal with:

```text
python <skill-root>/scripts/deutsch_loop.py mission-create --goal 'Cuma Almanca iş görüşmem var.' --scenario bewerbung --deadline 'cuma'
```

The date can be `YYYY-MM-DD`, today/tomorrow, or a weekday in English, German, or Turkish. A bare weekday resolves to the next occurrence on the local calendar, including today. Prefer an explicit date when it is known from the conversation. Take the resolved date from `mission.deadline` and show it in a short planning sentence before the first question. If a relative expression is ambiguous, start without a deadline, ask briefly what date is meant, and save the answer with `mission-update --deadline`; keep useful preparation moving. An empty deadline clears it. A passed date is marked overdue, never silently completed.

## Start or continue the next scene

```text
python <skill-root>/scripts/deutsch_loop.py mission-start g_...
```

Use the returned `contract`: role, opening, personal goal, `mission_step.goal`, and `mission_step.criteria`. Adapt language to the learner's stated level; the criteria can be met over several small turns. Use their actual details when known. Do not recite the CLI, rubric, or hidden focus patterns to the learner. A simple opener might be “İş görüşmesi için önce kendini tanıtmayı çalışacağız. Düzeltmeleri sona bırakacağım.” Then deliver one German partner line and wait for their answer.

The contract's `adaptation` contains the previous assessment, actual evidence sentences, note, and recorded scene corrections. Its focus list prioritizes active mistakes from the previous scene, then due and recurring patterns; helpful coaching memory is included. Weave those patterns into meaningful questions rather than demanding the same construction every turn.

- `start`: begin with the first manageable communication goal.
- `repair`: keep the same goal, use a fresh situation, and break it into smaller questions. Keep the previously useful hint in reserve, then use it if necessary. A different opening is provided for a retry; avoid repeating the rest of the earlier exchange verbatim.
- `challenge`: move to the next communication task and add one natural complication, using the learner's last actual answer as context.

If the date is close, keep scenes short and focused; urgency never substitutes for evidence or advances the plan. Scenes can be practised on the same day. That says nothing about long-term retention.

`mission-start` is resumable. `next_action: resume_scene` means use the stored utterances and continue the current role, without a new opening. `present_debrief` means finish and show the existing scene's report. `assess_mission` means the scene is already complete but its mission outcome still needs recording. None of these actions creates another scene or repeats stored errors. A completed/cancelled mission cannot start a new scene. Resolve another unfinished roleplay before starting this mission.

At the beginning of a new chat, `recap.missions` identifies active preparation and pending scenes. A request such as “İş görüşmesi hazırlığına devam” resumes that mission. For multiple active goals, use the named one; ask a short choice only when the learner's intended goal is unclear. An explicit unrelated request takes priority.

## Preserve help and actual evidence

Follow the normal [roleplay flow](roleplay.md): log real turns, stay in character, defer ordinary corrections, and stop/freeze the scene before the debrief. If the partner supplies a hint or an answer, label that actual partner turn:

```text
python <skill-root>/scripts/deutsch_loop.py roleplay-turn s_... --speaker partner --text 'Frage dich: mit wem?' --support hint
```

Use `--support shown` for a supplied answer, and omit the flag for ordinary partner dialogue. Do not label the learner's turn as the help. A normal interview question is not a hint. At the debrief, retain confirmed errors and actual successful productions through the existing `record`, `coach`, and `observe` rules. Reuse their timestamps when appropriate. These commands alone govern grammar memory and reviews; mission assessments do not.

After `roleplay-stop`, record the ordinary feedback and vocabulary and finish with `roleplay-finish`. Then assess the current step using `mission_step.criteria`, the actual saved exchange, and the help used:

```text
python <skill-root>/scripts/deutsch_loop.py mission-assess g_... --session-id s_... --result achieved --support none --evidence-turn-id t_... --note 'The learner introduced a role, a relevant project, and motivation without help.'
```

The example is illustrative. Cite actual learner turn IDs from this scene and write a grounded note. Repeat `--evidence-turn-id` for multiple necessary productions. Never invent a response, award success for a greeting alone, or infer that every criterion was met from a single grammar-correct sentence.

- `achieved`: the learner demonstrated this step's communication criteria without help. It advances one step, even if there are separate grammar errors to practise. Do not use it when the communication goal remains unmet.
- `practice`: more practice is needed, including a goal reached after a hint or supplied answer. It keeps the step open. Describe what worked and the specific gap in the note.

`--support` must describe the help actually used. The engine also checks the partner-turn labels: a logged hint or supplied answer prevents an unaided achievement even when an assessment says `none`. It validates the scene, turn ownership, completion, and chronology. It cannot itself judge German or whether a quoted sentence satisfies a semantic criterion; that remains the tutor's responsibility.

The assessment is a separate idempotent transaction. If a chat ends after the scene report but before assessment, a later chat can assess the completed scene without re-recording its mistakes. Identical retries do not advance twice. A changed judgment requires `mission-undo` of the latest assessment first; it is blocked while a newer unassessed scene exists, so a scene cannot be reassigned to an older step.

## Show the result and leave the next session available

Present the actual roleplay debrief in the same reply when the learner says “bitir”, followed by one short mission-progress line derived from the assessment. For example, a hinted attempt may say “Bu adımı ipucuyla tamamladın; sonraki oturumda yeni bir durumla tekrar deneyeceğiz.” A passed step may identify the next task. Do not launch another exercise automatically after an end request.

Completing all three steps means the communication-practice plan is completed. It is not evidence of overall fluency, exam success, guaranteed interview readiness, or mastery of the recorded grammar patterns. Use actual sources and keep grammar outcomes distinct.

`mission-update g_... --cancel` stops preparation without deleting its learning evidence. End and finish a currently active/debriefing scene before cancelling. The next offline dashboard export includes active/completed goals, steps, previous evidence, and the expanded roleplay catalog.
