# The Claude Code companion

[Back to the README](../README.md)

**Nochmal** is an optional plugin for Claude Code that keeps DeutschLoop in view while you work on something else. It reads the same memory as the tutor and saves reviews through the same engine, so nothing it shows or saves can bend the tutor's rules.

| Feature | Where it shows | How to get it |
| --- | --- | --- |
| [What is due](#the-status-line) | The status line under the prompt | Always on |
| [A card while Claude works](#a-card-while-claude-works) | Above the prompt | After a turn runs 12 seconds, or `/nochmal` |
| [The back of the card](#the-back-of-the-card) | Under the card, after your answer | Answer a card |
| [Your FehlerDNA](#the-fehlerdna-pane) | A pane | `/fehlerdna` |
| [The running scene](#the-scene-pane) | A pane | Opens with a roleplay, or `/szene` |

## Install

```bash
claude plugin marketplace add ahmtsahin/deutsch-loop
claude plugin install nochmal@deutsch-loop
```

From a clone of this repository, load it for one session instead:

```bash
claude --plugin-dir mods/nochmal
```

It needs:

- **Claude Code with mods**, the plugin function hooks API. That API is early access and may change between releases; the companion is tested with Claude Code 2.1.286, in the terminal and in the desktop app's Code tab. Codex has no equivalent, so this part is Claude Code only.
- **The DeutschLoop engine.** The companion finds it in the repository it sits in, in a cloned `~/.claude/skills/deutsch-loop`, in the installed `deutsch-loop` plugin, or in the marketplace's own copy, and runs it with `python`, `python3`, or `py -3`.
- **A learner folder.** Until you have practised with the tutor once, the companion stays silent. It never creates `~/.deutschloop` itself.

## The status line

```text
nochmal  FehlerDNA · fällig: 3 Muster, 5 Wörter · 17 Tage in Folge
```

Due patterns, due words from your scenes, and your streak, from the engine's `recap`. With nothing due it reads `FehlerDNA · nichts fällig`. It refreshes when a session starts, after reviews and corrections, and at most once a minute after other turns.

## A card while Claude works

When a turn of yours runs longer than 12 seconds and something is due, a card opens above the prompt:

```text
╭──────────────────────────────────────────────────────────────╮
│ Nochmal · warten auf + Akkusativ                              │
│ Your train is late. Text your friend that you are waiting     │
│ for her at the station.                                       │
│ Deine Antwort auf Deutsch                            prüfen    │
│ [ Später ]   ctrl+x tab: antworten · /nochmal <Satz>          │
╰──────────────────────────────────────────────────────────────╯
```

- Due patterns come before due words. A word card names the word and its meaning, as in `reservieren (rezervasyon yapmak): …`.
- The situation is written for this card and in your explanation language. When the pattern is about one word, a noun's gender or a verb's preposition, the situation needs that word.
- Answer in the card (in the terminal, `ctrl+x tab` moves into it; in the desktop app, click), or with `/nochmal <Satz>` at the prompt. The command runs at once, also while Claude is still working.
- **Später** puts the card away; it comes back with the next long turn. `/nochmal` opens the next due card at any time.
- No card appears while a roleplay scene runs, or during a turn that is itself a DeutschLoop lesson.

### What happens to your answer

Sonnet checks whether the answer uses the pattern and gets it right, then the engine saves the review:

| The answer | What is saved | What you see |
| --- | --- | --- |
| Uses the pattern correctly | `grade --result pass` | ✓, the step on the ladder, and when it comes back |
| Uses the pattern, but wrongly | `grade --result fail` with the minimal correction | ✗, the correction, and when it comes back |
| Does not use the pattern | Nothing | A note naming the pattern; the card stays open |

Other mistakes in the sentence are named in the note and never turn a pass into a fail.

## The back of the card

After the answer, the card turns over and puts your first mistake for this pattern beside today's sentence:

```text
✓ Richtig. „auf dich“: warten takes auf with the accusative. Stufe 1/6 · wieder Do 21:44
Am 07.06.: „Ich warte dich.“ · Heute: „Ich warte am Bahnhof auf dich.“ ✓
```

The back appears only after you have answered, so it is no hint and changes no record. Word cards come from scenes rather than mistakes and have no back.

## The FehlerDNA pane

`/fehlerdna` opens every pattern on its review ladder. Each ▰ is a passed review on the way through 1, 3, 7, 14, 30, and 60 days; due patterns come first and mastered ones last:

```text
FehlerDNA · 14 Muster · 2 gemeistert
Stufen ▰: 1 · 3 · 7 · 14 · 30 · 60 Tage. Eine Zeile öffnet ihre Geschichte.
Adjektiv nach ein/kein/mein    ▱▱▱▱▱▱   5× ✗  jetzt fällig
anrufen + Akkusativ            ▰▰▱▱▱▱   2× ✗  jetzt fällig
Angst haben vor + Dativ        ▰▱▱▱▱▱   1× ✗  jetzt fällig
warten auf + Akkusativ         ▱▱▱▱▱▱   4× ✗  morgen 11:05
weil: Verb ans Ende            ▱▱▱▱▱▱   2× ✗  morgen 11:08
sich freuen auf + Akkusativ    ▰▰▱▱▱▱   3× ✗  Do 11:05
den/einen im Akkusativ         ▰▰▰▰▱▱   1× ✗  15.10.
obwohl: Verb ans Ende          ▰▰▰▰▰▱   1× ✗  09.11.
-ung-Wörter sind feminin       ▰▰▰▰▰▰   1× ✗  ★ gemeistert
mit + Dativ                    ▰▰▰▰▰▰   1× ✗  ★ gemeistert
```

Choose a row to read the pattern's story, exactly as `show --format text` tells it; **← Zurück** returns to the list:

```text
warten auf + Akkusativ · Präpositionen · wird geübt

Erster Fehler · 2026-06-07: Ich warte dich.

2026-06-07  ✗ Fehler         Ich warte dich. → Ich warte auf dich.
2026-06-08  ✓ Wiederholung   Ich warte auf meinen Bruder.
2026-06-11  ✗ Wiederholung   Ich warte den Zug. → Ich warte auf den Zug.
2026-06-15  ~ Wiederholung   Ich warte auf deine Antwort. (nach einem Hinweis)
2026-06-16  ✓ Wiederholung   Sie wartet auf ihren Termin.
…
Hilfreicher Hinweis (Verb mit Präposition): Das Verb heißt warten auf.
Mit Hilfe · 2026-06-15: Ich warte auf deine Antwort.
Ohne Hilfe · 2026-06-16 (neue Aufgabe): Sie wartet auf ihren Termin.
```

Both examples are real engine output for the scripted four-month learner of `scripts/demo.py`. The pane refreshes after every review, correction, and repair while it is open.

## The scene pane

When the tutor starts a roleplay (`speak`, `roleplay-start`, or a mission's `mission-start`), its pane opens beside the chat:

```text
Restaurant
Partner: a waiter in a busy restaurant
Ziel: Handle the reservation, order, one special request, and payment.
Deine Züge: 3 von etwa 8
Zeit: 2:14 / 5:00  ████░░░░░░
Hilfe: noch keine
[ Hilfe ]
Hilfe wird ehrlich gespeichert: der Hinweis zählt als Unterstützung.
```

- The clock runs on its own; turns and help come from the engine after every logged turn.
- The scene's focus pattern stays hidden, as the skill asks.
- When the target time is up, the pane says so: `Die Zeit ist um: noch ein Satz, dann kommt das Feedback.`
- After the scene ends it reads `Szene beendet. Das Feedback kommt im Chat.` and closes 20 seconds later.
- A terminal narrower than 144 columns does not place a pane nobody asked for; the companion then says so, and `/szene` opens it.

### Hilfe

**Hilfe** asks the partner for a small hint:

```text
Hilfe-Knopf: Ich komme in der Szene nicht weiter. Gib mir als Partner einen kleinen Hinweis,
keinen fertigen Satz, und bleib in der Rolle. Diese Bitte ist kein eigener Zug der Szene.
```

The tutor answers in role, for example:

```text
Kellner: Kein Problem, lassen Sie sich Zeit. Ein kleiner Tipp: Beim Bestellen beginnen
         viele Gäste mit „Ich hätte gern …“ und nennen dann ein Gericht von der Karte.
```

The companion watches the tutor's next `roleplay-turn` for the partner and adds `--support hint` when the tutor left the flag out; a turn the tutor marked `--support shown` keeps its mark. Help therefore always counts as help: a mission step answered after it cannot be recorded as achieved without help.

## Models and privacy

- **Model calls:** writing a card and checking an answer each take one Sonnet call through your own Claude Code login. The status line and the panes make no model calls.
- **Your data:** the memory stays in `~/.deutschloop` (or an older `~/.deutschdna`). The companion reads it through the CLI and changes it only with `grade` and `vocab-grade`, never by editing the files.
- **What leaves the machine:** your German answer and the card's situation go to the model, as everything in a Claude Code session does.

## Troubleshooting

| What you see | Why |
| --- | --- |
| No status line | No learner folder yet, or no Python or engine was found; `/nochmal` says which |
| No card during a long turn | Nothing is due, a scene is running, or the turn was a DeutschLoop lesson |
| `Nicht gespeichert: This pattern is not due …` | The engine refused the review; the card is dropped |
| No scene pane | The terminal is narrow: use `/szene` |

## Development

```bash
claude plugin validate mods/nochmal
claude plugin test mods/nochmal
```

The tests stand in for the engine, the CLI, and the models, so they run without Python or a model call. They draw the card, the back, and both panes on the terminal and desktop surfaces; check every grade the companion saves; and check that Hilfe marks only the partner turn that answers it. `claude --plugin-dir mods/nochmal` loads your working copy, and an interactive session reloads it when a file changes.
