# Tests and demo assets

[Back to the README](../README.md)

Run the commands below from the repository root. DeutschLoop's runtime uses only Python 3.10+ and the standard library. Pillow is a contributor dependency for rendering the README assets.

## Unit tests

```bash
python -m unittest discover -s tests -v
```

The tests cover the engine. The first-session check exercises the skill in a real agent: a small Claude model plays a learner, and the script checks the transcript and saved records.

```bash
python evals/first_session.py --host claude
python evals/first_session.py --host codex --model gpt-6-astra
```

It uses a copy of the skill called `deutsch-loop-smoke` and isolated state, and fails if `~/.deutschloop` changes. These runs make real model calls through the installed hosts and take a few minutes. `--setup none` checks the experience before permission setup; `--runs 3` repeats the session.

The interrupted-lesson check ends a chat right after the tutor's hint, before the learner answers, and continues in a fresh chat on the same state. There the learner sends the repaired sentence as if resuming, then makes the same mistake in a new sentence and repairs it. The run fails if the unanswered hint saved anything, if the resumed answer counted for anything, if the new mistake was not saved exactly once, or if a sentence given after a hint was saved as unaided. The learner's messages are scripted, so no second model is involved:

```bash
python evals/interrupted_lesson.py --host claude
python evals/interrupted_lesson.py --host codex --model gpt-6-astra
```

## Render the README stories

The interactive HTML demo uses only the standard library and snapshots isolated learner state:

```bash
python scripts/render_dashboard_demo.py --force
```

It writes `demo/index.html` using the same `scripts/dashboard.html` template as personal `dashboard` exports. Dashboard unit tests check snapshot isolation, historical milestones after recurrence, source labels, local dates, export immutability, and safe embedding of learner text. [Dashboard guide](dashboard.md).

The continuing interview-preparation story also uses isolated state and no model calls:

```bash
python scripts/demo_missions.py --force
```

It writes `demo/missions.html`. `tests/test_missions.py` covers persistence across chats, local deadlines, help/evidence gates, resumable scenes, adaptive focus, assessment idempotency, undo order, cancellation, and the isolated eval install's runtime assets. The example learner and communication judgments are scripted; the engine supplies their saved sources and progression.

The README screenshot, `demo/missions.png`, is captured from that HTML at a 960 px browser width and 2× pixel scale, with “The next session” selected and the previous-session evidence expanded. It includes the selected Real-life goals navigation tab, page heading, chapter controls, and mission panel. Refresh this screenshot when the demo's content or layout changes; the Python renderer regenerates the HTML only.

```bash
python -m pip install pillow
python scripts/render_demo_gif.py --story learning-loop
python scripts/render_demo_gif.py --story history
python scripts/render_demo_gif.py --story conversation
python scripts/render_demo_gif.py --story board
python scripts/render_demo_gif.py --story session
python scripts/render_demo_gif.py --story social
```

Each story command writes a GIF and a static PNG under `demo/`. Three stories write a single PNG: `board` is a 1600 × 900 image of the four-month learner's session board, `session` is the README's opening image, drawn from the [recorded session](../demo/session.json), and `social` is the board at 1280 × 640 for the repository's social preview (Settings → General → Social preview). Review ladders and comeback markers are drawn, so any monospaced font renders them. Pass `--frames-dir demo-home/frames` to inspect every complete scene at its full size and at the 309 px width used in the mobile review. Text that exceeds the layout raises an error instead of being silently clipped or shrunk.

The learning-loop story opens on the result and lasts 11 seconds. The history story opens on the returning mistake and lasts 9 seconds. Both use scripted learner inputs and actual engine state, with dates anchored to the render day. The conversation replay lasts 16 seconds and reveals each learner message before its tutor reply.

The first full scene is saved as the static alternative. Source images are 720 × 800; the main sentence type is 42 px, which displays at about 18 px when the image is 309 px wide. Auxiliary labels are smaller. Plain text descriptions and the conversation transcript remain available outside the images.

The terminal version of the four-month story can also be rendered with [VHS](https://github.com/charmbracelet/vhs):

```bash
vhs demo/history.tape
```

It writes `demo/history-terminal.gif`, leaving the README's compact story intact.

## Record a real conversation

The checked-in [capture](../demo/conversation.json) contains actual Claude Code tutor replies and selected saved learning evidence. The learner inputs are scripted. A fresh second chat reads the state written by the first; both happen on the same day. No date is advanced. The GIF is a transcript replay with shortened timing, not a screen capture or a claim of next-day learning evidence.

To capture another run with your existing Claude Code login:

```bash
python evals/record_conversation.py --output demo-home/new-conversation.json
```

This makes three real host calls. It creates a project-local skill copy and an isolated progress folder under the ignored `demo-home/` directory. Global settings and the real learner memory are not edited; the script checks that `~/.deutschloop` stays unchanged. Raw host logs stay local, while the export contains the tutor's complete words and selected evidence. Existing output files are never overwritten.

If interrupted, reuse the printed recording folder:

```bash
python evals/record_conversation.py --resume-run demo-home/conversation-XXXXXXXX --output demo-home/new-conversation.json
```

Completed turns are read from their logs rather than requested again. Review the new recording before publishing it. The renderer verifies every displayed excerpt against its source text; a different tutor response may require selecting new excerpts in `collect_conversation_screens` before rendering:

```bash
python scripts/render_demo_gif.py --story conversation --transcript demo-home/new-conversation.json --output demo-home/new-conversation.gif
```

## Record a returning learner's session

The README's opening image shows how a chat starts after four months. The history is seeded through the engine by `scripts/demo.py`; the tutor's replies are actual Claude Code replies. It takes two steps, because the learner's answer depends on the task the tutor sets:

```bash
python evals/record_session.py
```

Read the task in the printed reply, write a fitting answer, and continue the same chat:

```bash
python evals/record_session.py --resume-run demo-home/session-XXXXXXXX --answer "..." --output demo-home/new-session.json
```

The script makes two real host calls and uses the same isolation as the conversation capture. It fails if the opening does not show the engine's board and the stored sentence, or if the answer was not saved as a review of the quoted pattern. Render the image from the new recording:

```bash
python scripts/render_demo_gif.py --story session --transcript demo-home/new-session.json --output demo-home/new-session.png
```

## Plugin manifests

`.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` make the repository installable as a Claude Code plugin. Codex reads the same marketplace file and takes `.codex-plugin/plugin.json` as the plugin's manifest. The version in both manifests must match `metadata.version` in `SKILL.md`; unit tests check this. Claude Code keeps users on a version until it changes, so raise all three with every release. Check the Claude Code manifests with:

```bash
claude plugin validate .
```

Claude Code loads the root `SKILL.md` as the plugin's only skill. Codex loads a plugin's skills only from a subfolder, so `.codex-plugin/skills/deutsch-loop/SKILL.md` is a short entry file that sends the agent to the root `SKILL.md`. Its name and description must match the root file. It stays in a hidden folder: Codex skips hidden folders when it scans a skills folder, so a cloned skill folder still shows one skill.

Codex has no validate command. To see what it loads, set `CODEX_HOME` to an empty folder, so that your own Codex setup stays untouched, and run these from the repository. No model is called:

```bash
codex plugin marketplace add .
codex plugin add deutsch-loop@deutsch-loop
codex debug prompt-input hi
```

The printed skills list must name `deutsch-loop:deutsch-loop` once, with a file path that ends in `.codex-plugin/skills/deutsch-loop/SKILL.md`.
