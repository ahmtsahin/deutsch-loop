"""Writing-part formats of German exams, for timed practice with each exam's own rating scheme.

Every number here (minutes, text lengths, rating bands, points, thresholds) was read in the
provider's published material: `sources` names the documents and `checked` the day they were
read. The tutor writes new tasks in these formats and rates the texts; this module turns the
ratings into points. A result is a practice estimate, never an official score.

Tasks from the published practice tests are not reproduced. `brief` tells the tutor how to
write a new task of the same shape.
"""

from __future__ import annotations

import copy
import re
from typing import Any


def _number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else round(float(value), 2)


def _bands(names: tuple[str, ...], *values: float) -> dict[str, float]:
    return dict(zip(names, values))


def _table(criteria: tuple[str, ...], points: dict[str, float]) -> dict[str, dict[str, float]]:
    return {criterion: dict(points) for criterion in criteria}


A_TO_E = ("A", "B", "C", "D", "E")
A_TO_D = ("A", "B", "C", "D")
STEPS = ("5", "4", "3", "2", "1", "0")

GOETHE = ("erfuellung", "kohaerenz", "wortschatz", "strukturen")
GOETHE_LANGUAGE = (
    {"id": "kohaerenz", "label": "Kohärenz",
     "meaning": "Text structure (opening, close) and how sentences and clauses are linked.",
     "guide": "A structured throughout and effectively, linking appropriate; B mostly; C in places; D hardly; "
              "E inadequate throughout."},
    {"id": "wortschatz", "label": "Wortschatz",
     "meaning": "Range and control of vocabulary.",
     "guide": "A differentiated, isolated slips that do not affect understanding; B mostly appropriate, several slips, "
              "understanding intact; C partly appropriate or limited, slips partly affect understanding; D hardly any range, "
              "slips affect understanding considerably; E inadequate throughout."},
    {"id": "strukturen", "label": "Strukturen",
     "meaning": "Range and control of grammar: morphology, syntax, spelling.",
     "guide": "Rated like Wortschatz, for structures."},
)
GOETHE_RULES = [{"when": {"erfuellung": ["E"]}, "text": "Erfüllung E: Die Aufgabe zählt insgesamt 0 Punkte."}]
# Erfüllung is E when the text has under half of the requested words; the engine counts them.
GOETHE_FLOOR = {"criterion": "erfuellung", "band": "E", "share": 0.5}
GOETHE_PASS = {"percent": 60, "label": "Bestehensgrenze im Modul Schreiben", "note": None}

TELC = ("aufgabe", "gestaltung", "richtigkeit")
# The rating sheet gives 5/3/1/0 per criterion, and telc multiplies the sum by three.
TELC_POINTS = _bands(A_TO_D, 15, 9, 3, 0)
TELC_PASS = {"percent": None, "label": None,
             "note": "telc hat für diesen Teil keine eigene Bestehensgrenze: Die schriftliche Prüfung ist mit 60 % "
                     "(135 von 225 Punkten) bestanden, und der Schriftliche Ausdruck zählt davon 45 Punkte."}
TELC_OFF_TOPIC = ("A text with little or no connection to the task is off-topic: rate D in every criterion. If only the "
                  "situation is missed, criterion I is D while II and III are still rated.")


EXAMS: dict[str, dict[str, Any]] = {
    "goethe-b1": {
        "title": "Goethe-Zertifikat B1", "provider": "Goethe-Institut", "level": "B1", "part": "Schreiben", "minutes": 60,
        "tasks": [
            {"number": 1, "type": "Persönliche E-Mail", "register": "informal", "words": 80, "words_kind": "about",
             "words_label": "circa 80 Wörter", "content_points": 3,
             "brief": "An e-mail to a friend about a personal occasion. Give three content points as bullets, each a "
                      "different language function (for example describe, give a reason, make a suggestion), and ask for "
                      "all three plus a salutation, an opening, and a close. Suggested time: 20 minutes."},
            {"number": 2, "type": "Forumsbeitrag mit eigener Meinung", "register": "neutral", "words": 80, "words_kind": "about",
             "words_label": "circa 80 Wörter", "content_points": 0,
             "brief": "Name a discussion topic and quote one short opinion from an online guestbook or forum; the learner "
                      "writes their own opinion on the topic. No bullets. Suggested time: 25 minutes."},
            {"number": 3, "type": "Kurze höfliche E-Mail", "register": "polite", "words": 40, "words_kind": "about",
             "words_label": "circa 40 Wörter", "content_points": 0,
             "brief": "A short polite e-mail to someone like a course leader: the learner cannot keep an appointment and "
                      "excuses themselves with a reason. Remind them of the salutation and the closing. "
                      "Suggested time: 15 minutes."},
        ],
        "criteria": [
            {"id": "erfuellung", "label": "Erfüllung",
             "meaning": "Content, length, and language functions of the task; the text type; a register that fits the reader.",
             "guide": "Task 1: A all three content points appropriate in content and length; B two appropriate, or one "
                      "appropriate and two partly; C one appropriate and one partly, or all partly; D one appropriate or "
                      "partly; E off-topic or under half the requested words. Tasks 2 and 3: A the opinion or message is "
                      "appropriate in content and length; B mostly; C partly; D hardly; E as in task 1."},
            *GOETHE_LANGUAGE,
        ],
        "bands": list(A_TO_E),
        "scoring": {
            "points": {
                "1": _table(GOETHE, _bands(A_TO_E, 10, 7.5, 5, 2.5, 0)),
                "2": _table(GOETHE, _bands(A_TO_E, 10, 7.5, 5, 2.5, 0)),
                "3": {**_table(GOETHE[:2], _bands(A_TO_E, 4, 3, 2, 1, 0)), **_table(GOETHE[2:], _bands(A_TO_E, 6, 4.5, 3, 1.5, 0))},
            },
            "rules": GOETHE_RULES, "length_floor": GOETHE_FLOOR,
        },
        "max_points": 100, "pass": GOETHE_PASS,
        "sources": ["https://www.goethe.de/pro/relaunch/prf/materialien/B1/B1_Uebungssatz_Erwachsene.pdf",
                    "https://www.goethe.de/pro/relaunch/prf/materialien/B1/b1_modellsatz_erwachsene.pdf",
                    "https://www.goethe.de/resources/files/pdf325/durchfuehrungsbestimmungen_b1-1.pdf"],
        "source_note": "Übungssatz Erwachsene (2016, print of October 2017): tasks, criteria, and the rating form with its points.",
        "checked": "2026-11-10",
    },
    "goethe-b2": {
        "title": "Goethe-Zertifikat B2", "provider": "Goethe-Institut", "level": "B2", "part": "Schreiben", "minutes": 75,
        "tasks": [
            {"number": 1, "type": "Forumsbeitrag", "register": "neutral", "words": 150, "words_kind": "about",
             "words_label": "circa 150 Wörter", "content_points": 4,
             "brief": "A forum post on a topic of public interest. Give four content points as bullets (for example an "
                      "opinion, reasons, alternatives, their advantages) and ask for an introduction and a conclusion. "
                      "Suggested time: 50 minutes."},
            {"number": 2, "type": "Nachricht im beruflichen Umfeld", "register": "polite, workplace", "words": 100,
             "words_kind": "about", "words_label": "circa 100 Wörter", "content_points": 4,
             "brief": "A message to a superior or a similar contact in a workplace or training situation. Give four content "
                      "points as bullets (language functions such as asking for understanding, describing, proposing) and "
                      "ask for a fitting order, a salutation, and a closing. Suggested time: 25 minutes."},
        ],
        "criteria": [
            {"id": "erfuellung", "label": "Aufgabenerfüllung",
             "meaning": "Content and length, how the language functions are realised, register, and sociocultural fit.",
             "guide": "A all four language functions appropriate in content and length, fitting the situation and the reader; "
                      "lower bands as fewer are appropriate; E off-topic, under half the requested words, or not fitting "
                      "the situation and reader at all."},
            *GOETHE_LANGUAGE,
        ],
        "bands": list(A_TO_E),
        "scoring": {
            "points": {
                "1": {**_table(GOETHE[:2], _bands(A_TO_E, 14, 10.5, 7, 3.5, 0)), **_table(GOETHE[2:], _bands(A_TO_E, 16, 12, 8, 4, 0))},
                "2": _table(GOETHE, _bands(A_TO_E, 10, 7.5, 5, 2.5, 0)),
            },
            "rules": [{"when": {"erfuellung": ["E"]}, "text": "Aufgabenerfüllung E: Die Aufgabe zählt insgesamt 0 Punkte."}],
            "length_floor": GOETHE_FLOOR,
        },
        "max_points": 100, "pass": GOETHE_PASS,
        "sources": ["https://www.goethe.de/pro/relaunch/prf/materialien/B2/b2_modellsatz_erwachsene.pdf",
                    "https://www.goethe.de/resources/files/pdf325/durchfuehrungsbestimmungen_b2.pdf"],
        "source_note": "Modellsatz Erwachsene, 2. Auflage August 2025: tasks, criteria, and the rating form with its points.",
        "checked": "2026-11-10",
    },
    "telc-b1": {
        "title": "telc Deutsch B1", "provider": "telc", "level": "B1", "part": "Schriftlicher Ausdruck", "minutes": 30,
        "tasks": [
            {"number": 1, "type": "E-Mail (informell oder halbformell)", "register": "informal or semi-formal", "words": None,
             "words_kind": None, "words_label": None, "content_points": 4,
             "brief": "Write the short e-mail the learner has received (from a friend or a contact) and ask for a reply "
                      "that says something about four content points given as bullets, in a fitting order, with a subject "
                      "line, a salutation, an opening, and a close. The practice test states no word count."},
        ],
        "criteria": [
            {"id": "aufgabe", "label": "Aufgabenbewältigung",
             "meaning": "How many of the four content points are handled appropriately.",
             "guide": "A all four; B three; C two; D one or none, or the situation is missed."},
            {"id": "gestaltung", "label": "Kommunikative Gestaltung",
             "meaning": "Range of language functions, structure, cohesion, register, and vocabulary.",
             "guide": "A level B1 well met; B B1 met; C A2; D A1 or below. No A when text-type features are missing, the "
                      "register is wrong or unstable, the points are only listed, or most sentences begin with Ich or Wir."},
            {"id": "richtigkeit", "label": "Formale Richtigkeit",
             "meaning": "Grammar, spelling, and punctuation; comprehensibility comes first.",
             "guide": "A level B1 well met; B B1 met; C A2; D A1 or below."},
        ],
        "bands": list(A_TO_D),
        "scoring": {"points": {"1": _table(TELC, TELC_POINTS)}, "rules": []},
        "tutor_rules": [TELC_OFF_TOPIC],
        "max_points": 45, "pass": TELC_PASS,
        "sources": ["https://shop.telc.net/media/catalog/product/file/telc_deutsch_b1_zd_uebungstest_1.pdf"],
        "source_note": "Übungstest 1, 13. Auflage 2020: task, criteria, and the calculation of the subtest result.",
        "checked": "2026-11-10",
    },
    "telc-b2": {
        "title": "telc Deutsch B2", "provider": "telc", "level": "B2", "part": "Schriftlicher Ausdruck", "minutes": 30,
        "tasks": [
            {"number": 1, "type": "Halbformelle E-Mail", "register": "semi-formal", "words": 150, "words_kind": "minimum",
             "words_label": "mindestens 150 Wörter", "content_points": 4,
             "brief": "Offer two alternative situations, A and B, each a reply to something like an advertisement (a request "
                      "for information, a complaint); the learner chooses one. Give four content points as bullets: the "
                      "learner covers three of them, or two of them and one further aspect of their own, in a fitting "
                      "order with a subject line, a salutation, an opening, and a close."},
        ],
        "criteria": [
            {"id": "aufgabe", "label": "Aufgabenbewältigung",
             "meaning": "How fully the content points are covered at the target level.",
             "guide": "A three content points, or two and a further aspect; B two, or one and a further aspect; C one; D none."},
            {"id": "gestaltung", "label": "Kommunikative Gestaltung",
             "meaning": "Formal and less formal style as the situation needs, range, and connectors.",
             "guide": "A level B2 well met; B B2 met; C B1; D A2 or below."},
            {"id": "richtigkeit", "label": "Formale Richtigkeit",
             "meaning": "Grammar, spelling, and punctuation.",
             "guide": "A level B2 well met; B B2 met; C B1; D A2 or below."},
        ],
        "bands": list(A_TO_D),
        "scoring": {"points": {"1": _table(TELC, TELC_POINTS)}, "rules": []},
        "tutor_rules": [TELC_OFF_TOPIC],
        "max_points": 45, "pass": TELC_PASS,
        "sources": ["https://www.telc.net/fileadmin/user_upload/pdfs/Handbuch_und_Tipps_fuer_Pruefungsvorbereitung/Deutsch_B2_Handbuch.pdf",
                    "https://shop.telc.net/media/catalog/product/file/201904225023B00010201BiB.pdf",
                    "https://www.sprachzertifikate-duesseldorf.de/_downloads/certificates/telc/pdf/telc-deutsch-b2-uebungstest.pdf"],
        "source_note": "Handbuch, 8. Auflage 2019: format and the 45 points. Übungstest 1 of 2019: task and criteria. "
                       "The points per rating (5/3/1/0, times three) were read in the Übungstest of 2011; its rule that a D "
                       "in criterion I or III scores the whole text 0 is not in the 2019 criteria and is not applied.",
        "checked": "2026-11-10",
    },
    "dtz": {
        "title": "Deutsch-Test für Zuwanderer", "provider": "BAMF", "level": "A2–B1", "part": "Schreiben", "minutes": 30,
        "tasks": [
            {"number": 1, "type": "Kurzmitteilung oder kurzer Brief", "register": "semi-formal or formal", "words": None,
             "words_kind": None, "words_label": None, "content_points": 4,
             "brief": "Offer two alternative situations, A and B; the learner chooses one. Each has a short introduction "
                      "that explains the occasion (for example an excuse to a course leader, a note to a landlord) and four "
                      "content points as keywords. All four are to be handled, with a salutation and a closing. "
                      "The handbook states no word count."},
        ],
        "criteria": [
            {"id": "aufgabe", "label": "Aufgabenbewältigung",
             "meaning": "How many of the four content points are handled, and how precisely.",
             "guide": "5 all four handled precisely; 4 all four, but the reader has to cooperate, or three appropriately; "
                      "3 three with the reader's cooperation, or two appropriately; 2 two with the reader's cooperation, or "
                      "one appropriately; 1 one with the reader's cooperation; 0 none, or the topic or situation is missed."},
            {"id": "gestaltung", "label": "Kommunikative Gestaltung",
             "meaning": "Realising language functions with the usual phrases, such as politeness formulas, and linking "
                        "short elements into a connected text.",
             "guide": "Rate the level shown: 5 or 4 for B1, 3 or 2 for A2, 1 for A1, 0 below that."},
            {"id": "korrektheit", "label": "Korrektheit",
             "meaning": "Grammar, spelling, and punctuation. At B1, errors occur but what is meant stays clear.",
             "guide": "Rate the level shown: 5 or 4 for B1, 3 or 2 for A2, 1 for A1, 0 below that."},
            {"id": "wortschatz", "label": "Wortschatz",
             "meaning": "Enough vocabulary to write about everyday matters, and how well the basic vocabulary is controlled.",
             "guide": "Rate the level shown: 5 or 4 for B1, 3 or 2 for A2, 1 for A1, 0 below that."},
        ],
        "bands": list(STEPS),
        "band_labels": {"5": "B1 gut erfüllt", "4": "B1 erfüllt", "3": "A2 gut erfüllt", "2": "A2 erfüllt", "1": "A1 erfüllt",
                        "0": "0 Punkte"},
        "scoring": {"points": {"1": _table(("aufgabe", "gestaltung", "korrektheit", "wortschatz"), _bands(STEPS, 5, 4, 3, 2, 1, 0))},
                    "rules": []},
        "max_points": 20,
        "pass": {"percent": 75, "label": "Niveau B1 in diesem Teil (ab 15 von 20 Punkten)", "note": "Niveau A2 ab 7 Punkten."},
        "sources": ["https://www.bamf.de/SharedDocs/Anlagen/DE/Integration/Integrationskurse/Kurstraeger/Modellsaetze/dtz-handbuch_pdf.pdf?__blob=publicationFile&v=8"],
        "source_note": "Prüfungsziele, Testbeschreibung (handbook), 1. Auflage 2009, sections 6.3.3 and 7.1.2.3.",
        "checked": "2026-11-10",
    },
}

EXAM_ALIASES: dict[str, str] = {
    "goethe-zertifikat-b1": "goethe-b1", "goethe-zertifikat-b2": "goethe-b2",
    "telc-deutsch-b1": "telc-b1", "zertifikat-deutsch": "telc-b1", "zd": "telc-b1", "telc-deutsch-b2": "telc-b2",
    "deutsch-test-für-zuwanderer": "dtz", "deutsch-test-fuer-zuwanderer": "dtz", "deutschtest-für-zuwanderer": "dtz",
}

# What a session keeps of its format, so that a later change here never rescores an old exam.
SNAPSHOT_FIELDS = ("title", "provider", "level", "part", "minutes", "criteria", "bands", "band_labels", "scoring",
                   "tutor_rules", "max_points", "pass", "checked")
TASK_FIELDS = ("number", "type", "register", "words", "words_kind", "words_label", "content_points")


def resolve_exam(name: str) -> str | None:
    key = re.sub(r"[\s_]+", "-", name.strip().lower())
    key = EXAM_ALIASES.get(key, key)
    return key if key in EXAMS else None


def exam_snapshot(key: str) -> dict[str, Any]:
    form = EXAMS[key]
    snapshot = {field: copy.deepcopy(form[field]) for field in SNAPSHOT_FIELDS if field in form}
    snapshot["tasks"] = [{field: task.get(field) for field in TASK_FIELDS} for task in form["tasks"]]
    return snapshot


def exam_formats() -> list[dict[str, Any]]:
    """Everything the tutor needs to write new tasks in a format and to rate a text by its criteria."""
    return [{"id": key, "aliases": sorted(alias for alias, target in EXAM_ALIASES.items() if target == key),
             **copy.deepcopy(form)} for key, form in EXAMS.items()]


def task_table(form: dict[str, Any], number: int) -> dict[str, dict[str, float]]:
    table = form["scoring"]["points"].get(str(number))
    if table is None:
        raise ValueError(f"{form['title']} has no writing task {number}")
    return table


def max_task_points(form: dict[str, Any], number: int) -> int | float:
    return _number(sum(max(points.values()) for points in task_table(form, number).values()))


def score_task(form: dict[str, Any], number: int, bands: dict[str, str], *, words: int | None = None) -> dict[str, Any]:
    """Points for one task from the tutor's ratings, with the format's own length and knock-out rules applied."""
    table = task_table(form, number)
    criteria = [item["id"] for item in form["criteria"] if item["id"] in table]
    if set(bands) != set(criteria):
        raise ValueError(f"Rate every criterion of task {number} exactly once: {', '.join(criteria)}")
    for criterion in criteria:
        if bands[criterion] not in table[criterion]:
            raise ValueError(f"{criterion} takes one of {', '.join(table[criterion])}; got {bands[criterion]}")
    floor = form["scoring"].get("length_floor")
    task = next(item for item in form["tasks"] if item["number"] == number)
    if floor and words is not None and task.get("words") and words < floor["share"] * task["words"]:
        if bands[floor["criterion"]] != floor["band"]:
            raise ValueError(
                f"The text has {words} words, under {round(floor['share'] * 100)} % of the {task['words']} requested; "
                f"by the exam's rule {floor['criterion']} is {floor['band']}")
    points = sum(table[criterion][bands[criterion]] for criterion in criteria)
    rule = None
    for candidate in form["scoring"].get("rules", []):
        if any(bands.get(criterion) in lowest for criterion, lowest in candidate["when"].items()):
            points, rule = 0, candidate["text"]
            break
    return {"bands": {criterion: bands[criterion] for criterion in criteria}, "points": _number(points), "rule": rule}
