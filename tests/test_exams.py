from __future__ import annotations

import json
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from test_agent_contract import CliTestCase
from test_deutsch_loop import BASE_TIME, StoreTestCase, dna

import exam_catalog  # noqa: E402  (test_deutsch_loop puts scripts/ on the path)


# A made-up format: these tests check the engine's rules, not any provider's numbers.
PROBE = {
    "title": "Probe B1", "provider": "Test", "level": "B1", "part": "Schreiben", "minutes": 30,
    "tasks": [
        {"number": 1, "type": "E-Mail", "register": "informal", "words": 20, "words_kind": "about", "words_label": "circa 20 Wörter",
         "content_points": 3, "brief": "An email to a friend with three content points."},
        {"number": 2, "type": "Mitteilung", "register": "formal", "words": 10, "words_kind": "minimum", "words_label": "mindestens 10 Wörter",
         "content_points": 1, "brief": "A short formal note."},
    ],
    "criteria": [{"id": "inhalt", "label": "Inhalt", "meaning": "Are the content points covered?"},
                 {"id": "sprache", "label": "Sprache", "meaning": "Range and correctness."}],
    "bands": ["A", "B", "C", "D"],
    "scoring": {
        "points": {"1": {"inhalt": {"A": 10, "B": 7.5, "C": 5, "D": 0}, "sprache": {"A": 10, "B": 7.5, "C": 5, "D": 0}},
                   "2": {"inhalt": {"A": 5, "B": 3, "C": 1, "D": 0}, "sprache": {"A": 5, "B": 3, "C": 1, "D": 0}}},
        "rules": [{"when": {"inhalt": ["D"]}, "text": "Inhalt D: Die Aufgabe zählt 0 Punkte."}],
        "length_floor": {"criterion": "inhalt", "band": "D", "share": 0.5},
    },
    "max_points": 30,
    "pass": {"percent": 60, "label": "Bestehensgrenze", "note": None},
    "sources": ["https://example.invalid/probe"], "checked": "2026-11-10",
}
TASKS = ["Schreib deiner Freundin Mia: Wo warst du, was hast du gemacht, wann trefft ihr euch?",
         "Schreib deiner Kursleiterin, dass du am Montag nicht kommen kannst."]
EMAIL = ("Liebe Mia, am Wochenende war ich mit mein Bruder in Hamburg. Wir haben den Hafen besucht "
         "und viel gegessen. Hast du am Freitag Zeit? Viele Grüße")
NOTE = "Sehr geehrte Frau Weber, am Montag kann ich leider nicht kommen. Mit freundlichen Grüßen"
GOOD = {"inhalt": "A", "sprache": "B"}


class ExamTestCase(StoreTestCase):
    def setUp(self):
        super().setUp()
        self._catalog = mock.patch.dict(exam_catalog.EXAMS, {"probe-b1": PROBE}, clear=True)
        self._catalog.start()

    def tearDown(self):
        self._catalog.stop()
        super().tearDown()

    def start(self, *, day=0, tasks=None):
        at = BASE_TIME + timedelta(days=day)
        return self.store.exam_start("probe-b1", tasks=tasks or [f"{text} ({day})" for text in TASKS], at=at)["session_id"]

    def sit(self, *, day=0, texts=(EMAIL, NOTE), bands=(GOOD, GOOD), minutes=20, support="none"):
        """One whole exam: start, hand in, rate, finish."""
        sid = self.start(day=day)
        at = BASE_TIME + timedelta(days=day, minutes=minutes)
        for number, text in enumerate(texts, 1):
            if text:
                self.store.exam_submit(sid, task=number, text=text, support=support, at=at)
        self.store.exam_stop(sid, at=at + timedelta(seconds=30))
        for number, (text, rating) in enumerate(zip(texts, bands), 1):
            if text:
                self.store.exam_score(sid, task=number, bands=rating, note="Alle Punkte behandelt.", at=at + timedelta(minutes=2))
        self.store.exam_finish(sid, at=at + timedelta(minutes=3))
        return sid


class ExamClockTests(ExamTestCase):
    def test_the_engine_starts_the_clock_and_keeps_the_tutors_tasks(self):
        started = self.store.exam_start("Probe B1", tasks=TASKS, at=BASE_TIME)
        self.assertEqual(started["status"], "started")
        self.assertEqual(started["next_action"], "wait_for_texts")
        self.assertEqual(started["deadline_local"], "2026-09-10T12:30:00+00:00")
        self.assertEqual([task["prompt"] for task in started["session"]["tasks"]], TASKS)
        self.assertEqual(started["open_tasks"], [1, 2])
        self.assertIn("Zeit: 30 Minuten · Abgabe bis 12:30 Uhr", started["card"])
        self.assertIn("Aufgabe 1 · E-Mail · circa 20 Wörter", started["card"])
        self.assertEqual(started["rubric"]["length_floor"]["share"], 0.5)
        self.assertEqual(started["rubric"]["points"]["1"]["inhalt"]["B"], 7.5)

    def test_a_new_chat_finds_the_running_exam_and_keeps_it_apart_from_scenes(self):
        sid = self.start()
        recap = dna.StateStore(self.home).recap(at=BASE_TIME + timedelta(minutes=10))
        self.assertEqual(recap["active_exam"]["session_id"], sid)
        self.assertEqual(recap["active_exam"]["remaining_seconds"], 20 * 60)
        self.assertEqual(recap["active_exam"]["next_action"], "wait_for_texts")
        self.assertIsNone(recap["active_roleplay"])
        self.assertEqual(recap["roleplays"]["count"], 0)
        self.assertIsNotNone(recap["last_activity_at"])

    def test_every_task_of_the_format_needs_its_own_new_text(self):
        with self.assertRaisesRegex(dna.DeutschLoopError, r"2 writing task\(s\)"):
            self.store.exam_start("probe-b1", tasks=TASKS[:1], at=BASE_TIME)
        with self.assertRaisesRegex(dna.DeutschLoopError, "Unknown exam"):
            self.store.exam_start("toefl", tasks=TASKS, at=BASE_TIME)
        with self.assertRaisesRegex(dna.DeutschLoopError, "already used"):
            self.store.exam_start("probe-b1", tasks=[TASKS[0], TASKS[0].upper()], at=BASE_TIME)

    def test_a_task_from_an_earlier_exam_is_refused(self):
        self.sit()
        with self.assertRaisesRegex(dna.DeutschLoopError, "already used"):
            self.store.exam_start("probe-b1", tasks=[f"{TASKS[0]} (0)", "Eine ganz neue Aufgabe."], at=BASE_TIME + timedelta(days=1))

    def test_only_one_exam_or_scene_is_open_at_a_time(self):
        sid = self.start()
        with self.assertRaisesRegex(dna.DeutschLoopError, f"practice exam {sid}"):
            self.start(day=1)
        with self.assertRaisesRegex(dna.DeutschLoopError, f"practice exam {sid}"):
            mission = self.store.mission_create(goal="Vorstellungsgespräch", scenario="interview", at=BASE_TIME)["mission"]["id"]
            self.store.mission_start(mission, at=BASE_TIME + timedelta(minutes=1))
        self.store.exam_cancel(sid, at=BASE_TIME + timedelta(minutes=2))
        scene = self.store.roleplay_start("restaurant", at=BASE_TIME + timedelta(minutes=3))["session"]["id"]
        with self.assertRaisesRegex(dna.DeutschLoopError, f"scene {scene}"):
            self.start(day=1)

    def test_the_rubric_is_frozen_when_the_exam_starts(self):
        sid = self.start()
        self.store.exam_submit(sid, task=1, text=EMAIL, at=BASE_TIME + timedelta(minutes=5))
        self.store.exam_stop(sid, at=BASE_TIME + timedelta(minutes=6))
        changed = json.loads(json.dumps(PROBE))
        changed["scoring"]["points"]["1"]["inhalt"]["A"] = 99
        with mock.patch.dict(exam_catalog.EXAMS, {"probe-b1": changed}):
            scored = self.store.exam_score(sid, task=1, bands=GOOD, note="Alle Punkte behandelt.", at=BASE_TIME + timedelta(minutes=8))
        self.assertEqual(scored["score"]["points"], 17.5)


class ExamTextTests(ExamTestCase):
    def test_a_text_is_counted_and_can_be_replaced_until_the_exam_is_handed_in(self):
        sid = self.start()
        first = self.store.exam_submit(sid, task=1, text="Liebe Mia, ich komme.", at=BASE_TIME + timedelta(minutes=5))
        self.assertEqual((first["status"], first["utterance"]["words"], first["open_tasks"]), ("stored", 4, [2]))
        again = self.store.exam_submit(sid, task=1, text="Liebe Mia, ich komme.", at=BASE_TIME + timedelta(minutes=6))
        self.assertEqual(again["status"], "duplicate")
        second = self.store.exam_submit(sid, task=1, text=EMAIL, at=BASE_TIME + timedelta(minutes=9))
        self.assertEqual((second["status"], second["utterance"]["id"]), ("replaced", first["utterance"]["id"]))
        self.assertEqual(second["utterance"]["words"], dna.count_words(EMAIL))
        self.assertEqual(len(second["session"]["texts"]), 1)
        self.store.exam_stop(sid, at=BASE_TIME + timedelta(minutes=10))
        with self.assertRaisesRegex(dna.DeutschLoopError, "texts are final"):
            self.store.exam_submit(sid, task=2, text=NOTE, at=BASE_TIME + timedelta(minutes=11))

    def test_words_are_counted_like_an_examiner_counts_them(self):
        self.assertEqual(dna.count_words("Ich komme um 18 Uhr, weil's E-Mail-Probleme gab – okay?"), 9)

    def test_a_text_after_the_deadline_is_late_and_the_report_says_so(self):
        sid = self.start()
        on_time = self.store.exam_submit(sid, task=1, text=EMAIL, at=BASE_TIME + timedelta(minutes=30, seconds=45))
        self.assertFalse(on_time["utterance"]["late"])  # The tutor needs a moment to pass a text on.
        late = self.store.exam_submit(sid, task=2, text=NOTE, at=BASE_TIME + timedelta(minutes=34))
        self.assertTrue(late["utterance"]["late"])
        self.assertTrue(late["time_is_up"])
        self.store.exam_stop(sid, at=BASE_TIME + timedelta(minutes=35))
        for number in (1, 2):
            self.store.exam_score(sid, task=number, bands=GOOD, note="Verständlich.", at=BASE_TIME + timedelta(minutes=36))
        self.store.exam_finish(sid, at=BASE_TIME + timedelta(minutes=37))
        shown = self.store.exam_show(sid)
        self.assertFalse(shown["report"]["within_time"])
        self.assertFalse(shown["report"]["exam_conditions"])
        self.assertIn("Zeit: 34:00 von 30:00", shown["learner_message"])
        self.assertIn("Nach der Zeit abgegeben: Aufgabe 2.", shown["learner_message"])

    def test_the_exam_ends_with_the_last_text_not_with_the_tutors_bookkeeping(self):
        sid = self.start()
        self.store.exam_submit(sid, task=1, text=EMAIL, at=BASE_TIME + timedelta(minutes=12))
        stopped = self.store.exam_stop(sid, at=BASE_TIME + timedelta(minutes=14))
        self.assertEqual((stopped["status"], stopped["duration_seconds"]), ("debriefing", 12 * 60))
        self.assertEqual(self.store.exam_stop(sid, at=BASE_TIME + timedelta(minutes=20))["duration_seconds"], 12 * 60)

    def test_help_during_the_exam_stays_on_the_result(self):
        sid = self.sit(support="hint")
        shown = self.store.exam_show(sid)
        self.assertFalse(shown["report"]["unaided"])
        self.assertFalse(shown["report"]["exam_conditions"])
        self.assertIn("· mit Hilfe", shown["learner_message"])
        self.assertIn("Mit Hilfe geschrieben", shown["learner_message"])


class ExamRatingTests(ExamTestCase):
    def handed_in(self, texts=(EMAIL, NOTE)):
        sid = self.start()
        for number, text in enumerate(texts, 1):
            if text:
                self.store.exam_submit(sid, task=number, text=text, at=BASE_TIME + timedelta(minutes=15))
        self.store.exam_stop(sid, at=BASE_TIME + timedelta(minutes=16))
        return sid

    def score(self, sid, task=1, bands=GOOD, note="Alle drei Punkte behandelt; ein Kasusfehler.", minute=18):
        return self.store.exam_score(sid, task=task, bands=bands, note=note, at=BASE_TIME + timedelta(minutes=minute))

    def test_no_rating_and_no_correction_reaches_a_running_exam(self):
        sid = self.start()
        turn = self.store.exam_submit(sid, task=1, text=EMAIL, at=BASE_TIME + timedelta(minutes=5))["utterance"]
        with self.assertRaisesRegex(dna.DeutschLoopError, "Stop the exam before rating"):
            self.score(sid)
        with self.assertRaisesRegex(dna.DeutschLoopError, "Stop the exam before recording feedback"):
            self.record_example(original="am Wochenende war ich mit mein Bruder in Hamburg.",
                                corrected="am Wochenende war ich mit meinem Bruder in Hamburg.",
                                session_id=sid, turn_id=turn["id"])
        self.assertEqual(self.store.list(), [])

    def test_points_come_from_the_table_not_from_the_tutor(self):
        sid = self.handed_in()
        first = self.score(sid)
        self.assertEqual((first["status"], first["score"]["points"], first["score"]["max_points"]), ("scored", 17.5, 20))
        self.assertEqual((first["unscored_tasks"], first["next_action"]), ([2], "score_remaining_tasks"))
        self.assertEqual(self.score(sid)["status"], "duplicate")
        changed = self.score(sid, bands={"inhalt": "B", "sprache": "B"})
        self.assertEqual((changed["status"], changed["score"]["points"]), ("rescored", 15))
        last = self.score(sid, task=2, bands={"inhalt": "A", "sprache": "A"})
        self.assertEqual((last["score"]["points"], last["next_action"]), (10, "finish_exam"))

    def test_a_rating_covers_every_criterion_with_a_band_of_the_exam(self):
        sid = self.handed_in()
        with self.assertRaisesRegex(dna.DeutschLoopError, "exactly once: inhalt, sprache"):
            self.score(sid, bands={"inhalt": "A"})
        with self.assertRaisesRegex(dna.DeutschLoopError, "exactly once"):
            self.score(sid, bands={**GOOD, "stil": "A"})
        with self.assertRaisesRegex(dna.DeutschLoopError, "sprache takes one of A, B, C, D; got E"):
            self.score(sid, bands={"inhalt": "A", "sprache": "E"})
        with self.assertRaisesRegex(dna.DeutschLoopError, "grounded"):
            self.score(sid, note="  ")
        with self.assertRaisesRegex(dna.DeutschLoopError, "no writing task 3"):
            self.score(sid, task=3)

    def test_the_knock_out_rule_is_applied_by_the_engine(self):
        sid = self.handed_in()
        scored = self.score(sid, bands={"inhalt": "D", "sprache": "A"})
        self.assertEqual(scored["score"]["points"], 0)
        self.assertEqual(scored["score"]["rule"], "Inhalt D: Die Aufgabe zählt 0 Punkte.")

    def test_a_task_without_a_text_scores_zero_and_cannot_be_rated(self):
        sid = self.handed_in(texts=(EMAIL, None))
        with self.assertRaisesRegex(dna.DeutschLoopError, "No text was submitted for task 2"):
            self.score(sid, task=2)
        self.score(sid)
        self.store.exam_finish(sid, at=BASE_TIME + timedelta(minutes=20))
        report = self.store.exam_show(sid)["report"]
        self.assertEqual((report["points"], report["max_points"], report["percent"]), (17.5, 30, 58))
        self.assertFalse(report["complete"])
        self.assertFalse(report["reached_pass_mark"])
        self.assertIn("Aufgabe 2 · Mitteilung · nicht abgegeben  →  0 von 10 Punkten", self.store.exam_show(sid)["learner_message"])

    def test_every_submitted_text_needs_a_rating_before_the_report(self):
        sid = self.handed_in()
        self.score(sid)
        with self.assertRaisesRegex(dna.DeutschLoopError, "Rate task 2 with exam-score first"):
            self.store.exam_finish(sid, at=BASE_TIME + timedelta(minutes=20))
        self.score(sid, task=2)
        finished = self.store.exam_finish(sid, at=BASE_TIME + timedelta(minutes=20))
        self.assertEqual(finished["status"], "complete")
        self.assertEqual(self.store.exam_finish(sid, at=BASE_TIME + timedelta(minutes=30))["finished_at"], finished["finished_at"])
        with self.assertRaisesRegex(dna.DeutschLoopError, "ratings are final"):
            self.score(sid, bands={"inhalt": "A", "sprache": "A"})


class ExamReportTests(ExamTestCase):
    def test_the_report_shows_bands_points_the_pass_mark_and_its_own_limits(self):
        sid = self.sit()
        shown = self.store.exam_show(sid)
        self.assertEqual((shown["next_action"], shown["response_required"]), ("present_report", True))
        report = shown["report"]
        self.assertEqual((report["points"], report["percent"], report["reached_pass_mark"]), (25.5, 85, True))
        self.assertTrue(report["exam_conditions"])
        message = shown["learner_message"]
        self.assertIn("Probe B1 · Schreiben · 10.09.2026", message)
        self.assertIn("Zeit: 20:00 von 30:00 · ohne Hilfe", message)
        self.assertIn(f"Aufgabe 1 · E-Mail · {dna.count_words(EMAIL)} Wörter (circa 20 Wörter)", message)
        self.assertIn("Inhalt A · Sprache B  →  17,5 von 20 Punkten", message)
        self.assertEqual(dna.exam_result({**self.store._session_document()["sessions"][0],
                                          "scores": {"1": {"bands": GOOD, "points": 17.5}, "2": {"bands": GOOD, "points": 6.2}}})["percent"], 79)
        self.assertIn("Übungsergebnis: 25,5 von 30 Punkten (85 %)", message)
        self.assertIn("Bestehensgrenze: 60 % · erreicht", message)
        self.assertIn("kein offizielles Ergebnis", message)
        self.assertIn("Keine bestätigten Fehler für diese Prüfung gespeichert.", message)

    def test_mistakes_from_the_texts_enter_the_fehlerdna_with_their_exam_sentence(self):
        known, _, _ = self.record_example(at=BASE_TIME - timedelta(days=3))
        sid = self.start()
        turn = self.store.exam_submit(sid, task=1, text=EMAIL, at=BASE_TIME + timedelta(minutes=15))["utterance"]
        self.store.exam_stop(sid, at=BASE_TIME + timedelta(minutes=16))
        sentence = "am Wochenende war ich mit mein Bruder in Hamburg."
        with self.assertRaisesRegex(dna.DeutschLoopError, "actual sentence"):
            self.record_example(original="Ich war mit mein Bruder dort.", corrected="Ich war mit meinem Bruder dort.",
                                session_id=sid, turn_id=turn["id"])
        mistake, status, _ = self.record_example(original=sentence, corrected=sentence.replace("mein Bruder", "meinem Bruder"),
                                                 session_id=sid, turn_id=turn["id"])
        self.assertEqual((status, mistake["id"], mistake["occurrences"]), ("updated", known["id"], 2))
        self.assertEqual(mistake["examples"][-1]["seen_at"], turn["at"])
        self.store.exam_score(sid, task=1, bands=GOOD, note="Ein Kasusfehler.", at=BASE_TIME + timedelta(minutes=18))
        self.store.exam_finish(sid, at=BASE_TIME + timedelta(minutes=19))
        shown = self.store.exam_show(sid)
        self.assertEqual(shown["report"]["confirmed_patterns"], 1)
        self.assertIn("Fehler aus deinen Texten: 1 Muster", shown["learner_message"])
        self.assertIn("1. mit + Dativ · schon bekannt", shown["learner_message"])
        self.assertIn(f"   → {sentence.replace('mein Bruder', 'meinem Bruder')}", shown["learner_message"])
        # A withdrawn correction leaves the report as well.
        self.store.undo(known["id"])
        self.assertEqual(self.store.exam_show(sid)["report"]["confirmed_patterns"], 0)

    def test_the_next_report_names_the_previous_attempt(self):
        self.sit(bands=({"inhalt": "C", "sprache": "C"}, {"inhalt": "C", "sprache": "C"}), support="hint")
        second = self.sit(day=7)
        message = self.store.exam_show(second)["learner_message"]
        self.assertIn("Letzter Versuch (10.09.2026): 12 von 30 Punkten (mit Hilfe) · heute: 25,5", message)
        rows = self.store.exam_list(exam="Probe B1")
        self.assertEqual([(row["points"], row["exam_conditions"]) for row in rows], [(12, False), (25.5, True)])
        recap = self.store.recap(at=BASE_TIME + timedelta(days=7, hours=1))
        self.assertEqual((recap["last_exam"]["session_id"], recap["last_exam"]["percent"]), (second, 85))
        self.assertEqual(recap["exams"], {"count": 1, "total": 2})
        self.assertIsNone(recap["active_exam"])
        self.assertIsNone(recap["last_roleplay"])

    def test_a_short_text_is_flagged_by_its_measured_length(self):
        short = "Liebe Mia, ich komme am Freitag um acht Uhr zu dir. Bis dann"  # 13 of about 20 words
        brief = "Frau Weber, ich komme am Montag leider nicht."  # 8 of at least 10 words
        sid = self.sit(texts=(short, brief))
        self.assertIn("Kürzer als verlangt: Aufgabe 1 (13 von circa 20 Wörter), Aufgabe 2 (8 von mindestens 10 Wörter).",
                      self.store.exam_show(sid)["learner_message"])

    def test_a_text_under_half_the_length_gets_the_lowest_content_band_by_the_exams_rule(self):
        sid = self.start()
        self.store.exam_submit(sid, task=1, text="Liebe Mia, ich komme am Freitag.", at=BASE_TIME + timedelta(minutes=5))
        self.store.exam_stop(sid, at=BASE_TIME + timedelta(minutes=6))
        with self.assertRaisesRegex(dna.DeutschLoopError, "6 words, under 50 % of the 20 requested; by the exam's rule inhalt is D"):
            self.store.exam_score(sid, task=1, bands=GOOD, note="Kurz, aber klar.", at=BASE_TIME + timedelta(minutes=7))
        scored = self.store.exam_score(sid, task=1, bands={"inhalt": "D", "sprache": "B"}, note="Zu kurz.",
                                       at=BASE_TIME + timedelta(minutes=7))
        self.assertEqual((scored["score"]["points"], scored["score"]["rule"]), (0, "Inhalt D: Die Aufgabe zählt 0 Punkte."))

    def test_a_cancelled_exam_leaves_the_history_but_its_tasks_stay_used(self):
        sid = self.start()
        self.store.exam_submit(sid, task=1, text=EMAIL, at=BASE_TIME + timedelta(minutes=5))
        cancelled = self.store.exam_cancel(sid, at=BASE_TIME + timedelta(minutes=6))
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(self.store.exam_list(), [])
        self.assertIsNone(self.store.recap(at=BASE_TIME + timedelta(minutes=7))["active_exam"])
        with self.assertRaisesRegex(dna.DeutschLoopError, "no result"):
            self.store.exam_finish(sid, at=BASE_TIME + timedelta(minutes=8))
        with self.assertRaisesRegex(dna.DeutschLoopError, "already used"):
            self.start()
        finished = self.sit(day=1)
        with self.assertRaisesRegex(dna.DeutschLoopError, "stays in the history"):
            self.store.exam_cancel(finished)

    def test_scene_commands_and_exam_commands_do_not_mix(self):
        sid = self.start()
        for call in (lambda: self.store.roleplay_turn(sid, speaker="learner", text="Hallo", at=BASE_TIME + timedelta(minutes=1)),
                     lambda: self.store.roleplay_stop(sid), lambda: self.store.roleplay_show(sid),
                     lambda: self.store.roleplay_finish(sid),
                     lambda: self.store.roleplay_vocab(sid, term="Hafen", meaning="liman", turn_id="t_1")):
            with self.assertRaisesRegex(dna.DeutschLoopError, "is a practice exam"):
                call()
        self.store.exam_cancel(sid)
        scene = self.store.roleplay_start("restaurant", at=BASE_TIME + timedelta(hours=1))["session"]["id"]
        with self.assertRaisesRegex(dna.DeutschLoopError, "not a practice exam"):
            self.store.exam_submit(scene, task=1, text=EMAIL)


class ExamCliTests(ExamTestCase, CliTestCase):
    def test_a_whole_exam_through_the_command_line(self):
        at = lambda minutes: (BASE_TIME + timedelta(minutes=minutes)).isoformat()
        started = json.loads(self.cli("exam-start", "--exam", "probe-b1", "--task", TASKS[0], "--task", TASKS[1], "--at", at(0)))
        sid = started["session_id"]
        with tempfile.TemporaryDirectory() as folder:
            draft = Path(folder) / "aufgabe-1.txt"
            draft.write_text(EMAIL, encoding="utf-8-sig")  # Windows PowerShell writes a byte-order mark.
            stored = json.loads(self.cli("exam-submit", sid, "--task", "1", "--text-file", str(draft), "--at", at(10)))
        self.assertEqual(stored["utterance"]["text"], EMAIL)
        self.cli("exam-submit", sid, "--task", "2", "--text", NOTE, "--at", at(12))
        self.assertIn("noch 18:00 Minuten", self.cli("exam-show", sid, "--format", "text", "--at", at(12)))
        self.assertEqual(json.loads(self.cli("exam-stop", sid, "--at", at(13)))["next_action"], "prepare_report")
        self.assertIn("Pass each rating once", self.cli_error("exam-score", sid, "--task", "1", "--band", "inhalt:A", "--note", "x"))
        self.cli("exam-score", sid, "--task", "1", "--band", "Inhalt=a", "--band", "sprache=B", "--note", "Alle Punkte.", "--at", at(15))
        self.cli("exam-score", sid, "--task", "2", "--band", "inhalt=A", "--band", "sprache=A", "--note", "Klar.", "--at", at(15))
        finished = json.loads(self.cli("exam-finish", sid, "--at", at(16)))
        self.assertEqual((finished["status"], finished["next_action"], finished["report"]["points"]), ("finished", "present_report", 27.5))
        self.assertIn("Übungsergebnis: 27,5 von 30 Punkten (92 %)", self.cli("exam-show", sid, "--format", "text"))
        self.assertIn("Prüfungstraining · 1 Versuch", self.cli("exam-list", "--format", "text"))
        self.assertIn("Could not read the text file", self.cli_error("exam-submit", sid, "--task", "1", "--text-file", "missing.txt"))

    def test_the_formats_are_listed_without_creating_learner_memory(self):
        self._temporary.cleanup()
        listed = json.loads(self.cli("exam-formats"))
        self.assertEqual((listed["count"], listed["exams"][0]["id"]), (1, "probe-b1"))
        self.assertIn("brief", listed["exams"][0]["tasks"][0])
        self.assertFalse(self.home.exists())
        self.home.mkdir()


class ExamCatalogTests(StoreTestCase):
    """The shipped formats: every table is complete, and every number names where it was read."""

    def test_every_format_is_complete_and_names_its_sources(self):
        self.assertTrue(exam_catalog.EXAMS)
        for key, form in exam_catalog.EXAMS.items():
            with self.subTest(exam=key):
                self.assertEqual(exam_catalog.resolve_exam(form["title"]), key)
                self.assertGreater(form["minutes"], 0)
                self.assertTrue(form["sources"] and all(url.startswith("https://") for url in form["sources"]))
                self.assertRegex(form["checked"], r"^\d{4}-\d{2}-\d{2}$")
                criteria = {item["id"] for item in form["criteria"]}
                self.assertEqual([task["number"] for task in form["tasks"]], list(range(1, len(form["tasks"]) + 1)))
                self.assertEqual(set(form["scoring"]["points"]), {str(task["number"]) for task in form["tasks"]})
                for task in form["tasks"]:
                    self.assertTrue(task["type"] and task["brief"])
                    table = form["scoring"]["points"][str(task["number"])]
                    self.assertTrue(set(table) <= criteria)
                    for points in table.values():
                        self.assertEqual(list(points), form["bands"])
                        self.assertEqual(sorted(points.values(), reverse=True), list(points.values()))
                for rule in form["scoring"].get("rules", []):
                    self.assertTrue(rule["text"])
                    for criterion, bands in rule["when"].items():
                        self.assertIn(criterion, criteria)
                        self.assertTrue(set(bands) <= set(form["bands"]))
                total = sum(exam_catalog.max_task_points(form, task["number"]) for task in form["tasks"])
                self.assertEqual(total, form["max_points"])
                percent = form["pass"]["percent"]
                self.assertTrue(percent is None or 0 < percent <= 100)
                self.assertTrue(form["pass"]["label"] if percent is not None else form["pass"]["note"])

    def test_aliases_lead_to_formats(self):
        for alias, key in exam_catalog.EXAM_ALIASES.items():
            self.assertIn(key, exam_catalog.EXAMS, alias)
            self.assertEqual(exam_catalog.resolve_exam(alias.replace("-", " ").upper()), key)

    def test_a_real_format_starts_and_scores_with_its_best_bands(self):
        for key, form in exam_catalog.EXAMS.items():
            with self.subTest(exam=key):
                home = self.home / key
                store = dna.StateStore(home)
                tasks = [f"Neue Aufgabe {task['number']} für {key}." for task in form["tasks"]]
                sid = store.exam_start(key, tasks=tasks, at=BASE_TIME)["session_id"]
                for task in form["tasks"]:
                    store.exam_submit(sid, task=task["number"], text=" ".join([EMAIL] * 8), at=BASE_TIME + timedelta(minutes=5))
                store.exam_stop(sid, at=BASE_TIME + timedelta(minutes=6))
                for task in form["tasks"]:
                    table = form["scoring"]["points"][str(task["number"])]
                    store.exam_score(sid, task=task["number"], bands={criterion: form["bands"][0] for criterion in table},
                                     note="Probe.", at=BASE_TIME + timedelta(minutes=7))
                store.exam_finish(sid, at=BASE_TIME + timedelta(minutes=8))
                report = store.exam_show(sid)["report"]
                self.assertEqual((report["points"], report["percent"]), (form["max_points"], 100))
