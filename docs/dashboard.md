# Your learning story

[Back to the README](../README.md) · [CLI guide](cli.md)

The dashboard turns your saved sentences into a story you can explore. It is one HTML file with its data, styles, and interactions included. Open it directly in a browser; it needs no server, packages, account, or internet connection.

## Your own progress

From the cloned skill folder:

```bash
python scripts/deutsch_loop.py dashboard --output my-progress.html
```

The JSON response gives the absolute path to open. In a tutor conversation, ask for a visual progress view and the agent can export it for you. The dashboard uses the same `--home` or `DEUTSCHLOOP_HOME` as the tutor.

Choose a pattern to see:

- Its first recorded mistake, or the earliest retained example when older history is unavailable.
- The successful answer after a hint, with the actual help preserved.
- A new unaided sentence on a later day, when the engine has recorded a learning milestone.
- Its next review, six-step review ladder, and retained event timeline.

Search a pattern or a sentence, choose a grammar family, or filter for due reviews, milestones, and mastered patterns. The interface supports keyboard navigation, small screens, reduced motion, and printing the selected story.

Saved real-life missions appear above the pattern map, with their date, current communication step, and previous assessment evidence. Expand the roleplay catalog for fifteen situations, opening lines, and variations. Practice and assessment still happen in the tutor chat; the HTML is an offline view of saved state.

This is a snapshot, so due dates are evaluated at export time. The displayed dates retain the engine's local offset even when the file is opened in a browser with another time zone. Export again for a fresh view. To replace an existing HTML file deliberately:

```bash
python scripts/deutsch_loop.py dashboard --output my-progress.html --force
```

The output must end in `.html` or `.htm`. The command does not grade, reschedule, mark a profile as shown, initialize a missing learner directory, or persist state migrations. An existing state directory is locked for a consistent snapshot. An empty history has an explicit starting message and no fabricated scores.

The file includes the exported learner sentences and hints. It makes no network requests and does not contain the undo snapshots, novelty fingerprints, or unrelated scene transcripts. Copying the HTML file also copies those exported sentences.

## What the evidence means

A milestone needs successful self-repair with a hint followed by a fresh unaided answer on a later local day, without an intervening recorded mistake. The screen distinguishes a new practice task, a due review, and unprompted use in the learner's own writing. Same-day practice and a supplied answer do not become a later-day milestone.

Milestones are historical evidence about a specific pattern. They are not a CEFR assessment or a claim that an explanation caused improvement. A later mistake keeps the historical milestone visible, explicitly marks the pattern as back in practice, and shows the engine's current review ladder. Undo and forget are reflected in the next export.

Detailed histories have rolling limits. The dashboard pins the available first example, helpful hint, and learning proof in its timeline even when detailed events have expired; it does not invent missing history.

## Explore the example history

Download and open [demo/index.html](../demo/index.html), or open it from a clone. GitHub's file viewer displays source rather than executing the page. The four selectable chapters follow one of Alex's patterns through its first hint, next-day use, a new context, and a return 103 days later. Alex already has an older mastered pattern in this story.

Learner messages are scripted. Every chapter is a separate snapshot captured from an isolated instance of the real engine before subsequent events are added. This demo does not call a model or touch real learner memory.

Rebuild it from the repository root:

```bash
python scripts/render_dashboard_demo.py --force
```

The renderer writes `demo/index.html` by default; `--output PATH` chooses another file. It uses only the standard library. The interface comes from `scripts/dashboard.html`, which is also used for personal exports.

The companion [mission demo](../demo/missions.html) follows interview preparation across scenes. Rebuild it with `python scripts/demo_missions.py --force`; the demo navigation links work when both files are in the same folder.
