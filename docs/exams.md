# Practise the writing part of your exam

[Back to the README](../README.md) · [Tutor protocol](../references/exams.md)

Tell the tutor which exam you are preparing for:

> Goethe B1 Schreiben üben.

> telc B1 sınavına hazırlanıyorum, bir yazma denemesi yapalım.

You get new tasks in the format of the real paper and its time limit. While you write there is no help and no correction, as in the exam room. When you hand in, the tutor rates your texts by the exam's own criteria, the engine turns the ratings into points with the exam's own table, and every mistake enters your FehlerDNA, where it comes back in reviews from the next day.

```text
PRÜFUNGSTRAINING · Goethe-Zertifikat B1 · Schreiben
Zeit: 60 Minuten · Abgabe bis 16:00 Uhr
Aufgabe 1 · Persönliche E-Mail · circa 80 Wörter
Aufgabe 2 · Forumsbeitrag mit eigener Meinung · circa 80 Wörter
Aufgabe 3 · Kurze höfliche E-Mail · circa 40 Wörter
Bis zur Abgabe gibt es keine Hilfe und keine Korrekturen. Mit „Abgeben“ endet die Prüfung.
```

Send each text with its task number, in any order. A corrected version replaces the earlier one until you write „Abgeben". Then the report comes:

```text
PRÜFUNGSTRAINING · AUSWERTUNG
Goethe-Zertifikat B1 · Schreiben · 10.11.2026
Zeit: 52:00 von 60:00 · ohne Hilfe

Aufgabe 1 · Persönliche E-Mail · 74 Wörter (circa 80 Wörter)
  Erfüllung A · Kohärenz B · Wortschatz B · Strukturen C  →  30 von 40 Punkten
  Alle drei Punkte behandelt; Genus und Kasus bei Balkon und Arbeit.
Aufgabe 2 · Forumsbeitrag mit eigener Meinung · 67 Wörter (circa 80 Wörter)
  Erfüllung B · Kohärenz B · Wortschatz B · Strukturen B  →  30 von 40 Punkten
  Meinung klar begründet; ein Wortstellungsfehler nach manchmal.
Aufgabe 3 · Kurze höfliche E-Mail · 34 Wörter (circa 40 Wörter)
  Erfüllung A · Kohärenz A · Wortschatz B · Strukturen A  →  18,5 von 20 Punkten
  Entschuldigung, Grund und Bitte um einen neuen Termin, höflich.

Übungsergebnis: 78,5 von 100 Punkten (79 %)
Bestehensgrenze im Modul Schreiben: 60 % · erreicht
Das ist eine Übungseinschätzung nach den veröffentlichten Kriterien, kein offizielles Ergebnis.

Fehler aus deinen Texten: 3 Muster
1. Balkon ist maskulin
   Die neue Wohnung ist hell und hat ein großes Balkon, aber die Küche ist leider klein.
   → Die neue Wohnung ist hell und hat einen großen Balkon, aber die Küche ist leider klein.
…
Diese Muster kommen in deiner Wiederholung in neuen Sätzen zurück.
```

This report is real engine output for a scripted learner; the ratings and notes in it were written for the example. For a whole exam rated by an actual Claude Code tutor, see the [recorded Goethe B1 exam](../demo/exam.md).

## The formats

| Exam | Part | Time | Tasks | Points | Threshold shown |
| --- | --- | --- | --- | --- | --- |
| Goethe-Zertifikat B1 (`goethe-b1`) | Schreiben | 60 min | e-mail to a friend (about 80 words), forum opinion (about 80), short polite e-mail (about 40) | 100 | pass mark of the module: 60 |
| Goethe-Zertifikat B2 (`goethe-b2`) | Schreiben | 75 min | forum post (about 150 words), workplace message (about 100) | 100 | pass mark of the module: 60 |
| telc Deutsch B1 (`telc-b1`) | Schriftlicher Ausdruck | 30 min | one e-mail with four content points | 45 | none for this part alone |
| telc Deutsch B2 (`telc-b2`) | Schriftlicher Ausdruck | 30 min | one semi-formal e-mail, at least 150 words, a choice of two situations | 45 | none for this part alone |
| Deutsch-Test für Zuwanderer (`dtz`) | Schreiben | 30 min | one short message or letter with four content points, a choice of two situations | 20 | level B1 from 15 points, A2 from 7 |

Only the writing part exists. Reading, listening, and speaking parts, and other exams such as telc Deutsch Beruf, TestDaF, or ÖSD, are not included.

Every number comes from the provider's own published material, read on 10 November 2026:

- Goethe-Zertifikat B1: [Übungssatz Erwachsene](https://www.goethe.de/pro/relaunch/prf/materialien/B1/B1_Uebungssatz_Erwachsene.pdf) with its rating form, the [Modellsatz](https://www.goethe.de/pro/relaunch/prf/materialien/B1/b1_modellsatz_erwachsene.pdf), and the [Durchführungsbestimmungen](https://www.goethe.de/resources/files/pdf325/durchfuehrungsbestimmungen_b1-1.pdf).
- Goethe-Zertifikat B2: [Modellsatz Erwachsene](https://www.goethe.de/pro/relaunch/prf/materialien/B2/b2_modellsatz_erwachsene.pdf), 2nd edition of August 2025, and the [Durchführungsbestimmungen](https://www.goethe.de/resources/files/pdf325/durchfuehrungsbestimmungen_b2.pdf).
- telc Deutsch B1: [Übungstest 1](https://shop.telc.net/media/catalog/product/file/telc_deutsch_b1_zd_uebungstest_1.pdf), 13th edition of 2020.
- telc Deutsch B2: the [Handbuch](https://www.telc.net/fileadmin/user_upload/pdfs/Handbuch_und_Tipps_fuer_Pruefungsvorbereitung/Deutsch_B2_Handbuch.pdf) of 2019 for the format and the 45 points, and [Übungstest 1](https://shop.telc.net/media/catalog/product/file/201904225023B00010201BiB.pdf) of 2019 for the task and the criteria. The points per rating (5, 3, 1, and 0, times three) were read in the practice test of 2011, because the 2019 excerpt does not print them. That older test also scored a whole text 0 for a D in its first or third criterion; the 2019 criteria do not say so, and the rule is not applied.
- Deutsch-Test für Zuwanderer: the [handbook](https://www.bamf.de/SharedDocs/Anlagen/DE/Integration/Integrationskurse/Kurstraeger/Modellsaetze/dtz-handbuch_pdf.pdf?__blob=publicationFile&v=8) published by the BAMF, 1st edition of 2009, sections 6.3.3 and 7.1.2.3.

Exams change. If a format here differs from your provider's current paper, [open an issue](https://github.com/ahmtsahin/deutsch-loop/issues) with a link to the document. The tasks are written new for every exam; the published practice tasks are not reproduced.

## What the engine decides, and what the tutor decides

The tutor reads your text and chooses a rating band for each criterion, with a short reason. Everything else is the engine's:

```text
A rating while you are still writing
→ Stop the exam before rating it; no feedback reaches the learner while the clock runs

A task the tutor has used before
→ This exam task was already used; write a new task

A rating that skips a criterion
→ Rate every criterion of task 1 exactly once: erfuellung, kohaerenz, wortschatz, strukturen

A generous rating for a text that is far too short (Goethe: under half the requested words)
→ The text has 31 words, under 50 % of the 80 requested; by the exam's rule erfuellung is E

A report before every text is rated
→ Rate task 2 with exam-score first; every submitted text needs a rating
```

- **Time** is measured from the start to your last text. A text that arrives more than a minute after the deadline is marked late, and the report says so.
- **Length** is the engine's word count, shown beside the requested length.
- **Points** come from the exam's table. Where the exam scores a task 0 for the lowest content rating, the engine applies that.
- **Help** is kept: if the tutor helped while you wrote, the result reads „mit Hilfe".
- **History** is kept: the next report names your previous attempt, and “How did my exams go?” lists them all.

## What the result is not

It is one model's rating against published criteria. A real paper is scored by two trained raters, and their judgment can differ from the tutor's by a band in either direction. Use the number to see which criterion costs you points and whether you finish in time, not to decide whether you are ready. The engine cannot check the tutor's reading of your German; it checks time, length, completeness, and arithmetic.

## Use the engine directly

These commands are usually run by the agent. From a clone:

```bash
python scripts/deutsch_loop.py exam-formats
```

```bash
python scripts/deutsch_loop.py exam-list --format text
```

```bash
python scripts/deutsch_loop.py exam-show s_... --format text
```

`exam-start`, `exam-submit`, `exam-stop`, `exam-score`, `exam-finish`, and `exam-cancel` are described in the [command contract](../references/cli-contract.md#practice-exams).
