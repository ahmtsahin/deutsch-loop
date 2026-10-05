# Reciprocal learning

The learner practises German; the coach remembers the support used and the observed outcome. A successful hint is one piece of evidence, not proof of a learning style or of causation. Keep all evidence in the local CLI. Never invent an answer to finish a workflow.

## A first win

1. Respond to the content of the learner's message. Choose one confirmed, manageable root cause. Keep its corrected form out of the conversation until the learner has tried repairing it, and do not run `record` yet: hosts show every command, and its `--corrected` text would give the answer away. Skip the guessing step when they ask for direct correction; then record right away.
2. Invite self-repair with a small cue, such as “Schau noch einmal auf mit mein Chef.” Wait for the learner. If needed, offer one more specific cue; use the prior `coaching.helpful_hint` when it fits. If `last_attempt` shows that this approach just failed, change the explanation instead of repeating it indefinitely.
3. Once they answer, record the original error once, then what actually happened in the attempt. Run `record` before `coach`: an error saved after the assisted attempt looks like a recurrence after the help and blocks the next day's evidence.

   ```text
   python <skill-root>/scripts/deutsch_loop.py record --original 'Ich spreche mit mein Chef.' --corrected 'Ich spreche mit meinem Chef.' --category case --pattern 'mit + dative' --rule 'mit verlangt den Dativ'
   python <skill-root>/scripts/deutsch_loop.py coach <mistake-id> --outcome assisted --prompt 'Schau noch einmal auf mit mein Chef.' --answer 'Ich spreche mit meinem Chef.' --strategy 'Kasusfrage' --hint 'Frage dich: mit wem?'
   ```

4. Give one different situation that requires the same structure, without the rule or answer. Wait for their production, then use `coach --outcome independent --prompt '...' --answer '...'` if correct without help. This same-session win keeps the review schedule and accuracy unchanged. It is not evidence of long-term retention.
5. Return to the conversation with one content-specific question. Avoid turning every message into an exercise. If they are done, stop.

`--prompt` is the actual task, `--answer` is the learner's actual production, `--strategy` names the approach used, and `--hint` preserves the actual help (include every cue used in this attempt). Use German technique names and keep umlauts intact.

## Choose the command from the evidence

| Situation | Command | Learning evidence |
| --- | --- | --- |
| New unaided answer to an exercise before the due time | `coach --outcome independent` | Prompted practice, no ladder advance |
| Correct answer after a small cue | `coach --outcome assisted --strategy ... --hint ...` | Hint helped in this attempt; retained for future coaching |
| Learner repeats an answer the coach supplied | `coach --outcome shown --strategy ... --hint ...` | Exposure only; not a helpful-hint success or independent use |
| Exercise remains wrong | `coach --outcome miss`, with actual support if given | The method did not resolve this attempt |
| Due review | `grade --prompt ... --answer ... --result pass/hard/fail` | Due, fresh, unaided pass advances the ladder |
| Unprompted use in ordinary writing/conversation | `observe --context ...` | Spontaneous evidence; a new production can replace a due review |

`coach` never files a new error, changes accuracy, or changes the review ladder. For an actual new wrong production, record that occurrence once; never re-record the original error during the same self-repair attempt. `grade fail` already records its error. If the learner gives no answer, there is no attempt to log. A hint offered without a learner response is not a successful hint.

In a due review, record a small hint with `grade hard --strategy ... --hint ...`; this remembers the support in the same transaction. If the learner hesitated without a hint, omit both fields. When the full answer was supplied, use `coach shown` after the learner responds and leave the review due for a fresh task. A failed review followed by self-repair is `grade fail`, then `coach` for the repair; each is a distinct event.

## The next encounter

Read the target's `coaching` memory in `recap.callback`, `due`, `show`, or `list --verbose`. Start a new task without exposing the previous hint. If support is needed, the stored method is a candidate, not a requirement. Use the learner's stated goal for relevant contexts; a work meeting should lead to work practice when that is what they want.

The engine returns a new `learning_proof` only after a fresh unaided production on a later local day, following an assisted success with no intervening recorded recurrence. `with_help` contains the real earlier answer and hint; `independent` contains the new answer, local timestamp, and source (`spontaneous`, `review`, or `practice`). Use those fields to say, for example:

```text
Gestern mit einem Hinweis: „Ich spreche mit meinem Chef.“
Heute ohne Hilfe, in einer neuen Aufgabe: „Ich fahre mit dem Bus.“ ✓
```

This example is illustrative. Derive every date and quotation from actual output. Say “frei geschrieben” only for `source: spontaneous`; a prompted exercise is not spontaneous use. Do not turn a single success into “you mastered German” or claim that the hint caused the improvement. The same milestone is returned as new only once. Its stored copy remains available in `show` even when detailed histories are trimmed.

## Personal goals and repair

When the learner states a real-life goal, store it with `init --goal "..."`. Do not infer personal facts from grammar mistakes. `init --goal ""` clears the goal; ordinary profile updates preserve it. Roleplay receives it as `contract.personal_goal` and uses it only if relevant to the requested scene.

`undo` reverts the latest `coach`, `grade`, `record`, `observe`, or `merge`, including teaching memory, novelty checks, and scheduling. It remains one level deep: after two separate actions, it undoes only the most recent one. `merge` and `rename` preserve coaching evidence; `forget` removes the entire pattern and its evidence.
