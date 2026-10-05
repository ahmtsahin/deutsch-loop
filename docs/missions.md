# Prepare for a real conversation

[Back to the README](../README.md) · [Roleplay examples](practice.md#more-roleplay-situations)

Tell the tutor about a real goal, for example:

> Cuma Almanca iş görüşmem var. Birkaç oturumda hazırlanalım.

It saves the goal and date, starts a small task, and remembers the result for the next chat. A job interview has three communication steps:

1. Introduce your background, experience, and motivation.
2. Answer a difficult question with a concrete situation, your action, and its result.
3. Handle an unexpected follow-up, an alternative, or a request for clarification.

You can finish a scene with “bitir” and continue another time with “İş görüşmesi hazırlığına devam”. The tutor resumes an interrupted scene or unfinished assessment before starting another one. Each new scene gets the previous actual answers, assessment note, and recorded mistakes; the date stays with the plan.

If you needed a hint or a supplied answer, the same step stays open for a fresh attempt with smaller questions. If you demonstrated its communication goal without help, the next step introduces another challenge. Grammar patterns remain separate: a communicated answer can meet a task while still containing a mistake worth practising, and completing preparation does not count as grammar mastery or overall fluency.

Say that the date changed to update it, or ask to cancel preparation. Finishing the three practice steps does not guarantee an interview result or certify readiness. The assessment is the tutor's judgment of the saved conversation; the engine checks its sources and help labels, not the semantics of German.

Every roleplay frame supports a three-step goal plan. The interview has its specific sequence; the others practise explaining the request, pursuing the main goal, and reacting to a change.

## Use the engine directly

These commands are usually run by the agent. From a clone, they are also available directly:

```bash
python scripts/deutsch_loop.py mission-create --goal "Cuma Almanca iş görüşmem var." --scenario interview --deadline cuma
python scripts/deutsch_loop.py mission-list
python scripts/deutsch_loop.py mission-start g_...
python scripts/deutsch_loop.py mission-show g_...
```

Use the returned mission ID. `--deadline` accepts an ISO date, today/tomorrow, or a weekday in English, German, or Turkish. A bare weekday includes today when it matches the local calendar; use an explicit date for a later week's event. An overdue plan remains active until the learner completes or cancels it.

The scene uses the ordinary `roleplay-turn`, `roleplay-stop`, feedback, vocabulary, and `roleplay-finish` flow. Mark a real partner hint with `--support hint`, and a supplied answer with `--support shown`. Then cite actual learner turn IDs in the completed scene:

```bash
python scripts/deutsch_loop.py mission-assess g_... --session-id s_... --result achieved --support none --evidence-turn-id t_... --note "Introduced experience and motivation without help."
```

Use `practice` when the communication goal is unmet or needed support. Repeating an identical assessment is safe; changing it requires `mission-undo`. Undo is blocked while a newer scene is awaiting assessment, so its evidence cannot be applied to an older step. Mission operations do not advance the grammar review ladder.

```bash
python scripts/deutsch_loop.py mission-update g_... --deadline 2026-10-09
python scripts/deutsch_loop.py mission-update g_... --cancel
python scripts/deutsch_loop.py dashboard --output my-progress.html
```

Plans live locally in `missions.json` beside the existing learner files. The dashboard shows active/completed goals, their steps and previous evidence, and the roleplay catalog. It remains a snapshot; practising happens in the tutor chat.

## Explore a complete example

Download and open [demo/missions.html](../demo/missions.html), or use it from a clone. The example includes a hinted attempt, a fresh unaided introduction, a difficult-question scene with a recorded error, and a follow-up shaped by that history.

The learner and assessment judgments are scripted. State, sources, dates, progress, and focus selection come from the real engine. Each chapter is captured before future events exist. No model, account, or real learner memory is used.

Rebuild with the standard library:

```bash
python scripts/demo_missions.py --force
```
