from __future__ import annotations

import contextlib
import io
import json
from datetime import timedelta
from unittest import mock

from test_deutsch_loop import BASE_TIME, StoreTestCase, dna


PARTNER_LINE = "Haben Sie reserviert? Die Reservierung ist auf den Namen Sahin."
RESERVIEREN = ("reservieren", "reserviert", "rezervasyon yapmak")
RESERVIERUNG = ("die Reservierung", "Die Reservierung", "rezervasyon")


class VocabularyTests(StoreTestCase):
    def scene_with_words(self, words=(RESERVIEREN,), start=BASE_TIME):
        identifier = self.store.roleplay_start("restaurant", at=start)["session"]["id"]
        turn = self.store.roleplay_turn(identifier, speaker="partner", text=PARTNER_LINE,
                                        at=start + timedelta(seconds=10))["utterance"]
        self.store.roleplay_stop(identifier, at=start + timedelta(minutes=5))
        results = [self.store.roleplay_vocab(identifier, term=term, surface=surface, meaning=meaning, turn_id=turn["id"])
                   for term, surface, meaning in words]
        return identifier, results

    def review(self, word_id, index, *, result="pass", at):
        return self.store.vocab_grade(word_id, result=result, at=at, prompt=f"Neue Situation {index}: sag es mit rezervasyon yapmak.",
                                      answer=f"Ich reserviere für {index + 2} Personen.")

    def cli(self, *arguments: str) -> str:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = dna.main(["--home", str(self.home), *arguments])
        self.assertEqual(code, 0, buffer.getvalue())
        return buffer.getvalue()

    def test_scene_words_enter_the_deck_and_come_back_the_next_day(self):
        _, results = self.scene_with_words()
        word = results[0]["word"]
        self.assertEqual(results[0]["deck"], "added")
        self.assertEqual((word["source"]["scenario"], word["source"]["example"]), ("restaurant", PARTNER_LINE))
        self.assertEqual(self.store.vocab_due(at=BASE_TIME + timedelta(hours=23)), [])
        due = self.store.vocab_due(at=BASE_TIME + timedelta(days=1, minutes=1))
        self.assertEqual([item["id"] for item in due], [word["id"]])

    def test_a_word_met_again_keeps_its_schedule(self):
        _, results = self.scene_with_words()
        word_id = results[0]["word"]["id"]
        graded, _ = self.review(word_id, 0, at=BASE_TIME + timedelta(days=1, hours=1))
        _, again = self.scene_with_words(start=BASE_TIME + timedelta(days=2))
        self.assertEqual(again[0]["deck"], "known")
        deck = self.store.vocab_list()
        self.assertEqual(len(deck), 1)
        self.assertEqual((deck[0]["review_step"], len(deck[0]["sources"])), (1, 2))
        self.assertEqual(deck[0]["next_review"], graded["next_review"])

    def test_articles_and_spellings_share_a_card_but_nouns_and_verbs_do_not(self):
        self.assertEqual(dna.word_key("die Reservierung"), dna.word_key("Reservierung"))
        self.assertEqual(dna.word_key("die Straße"), dna.word_key("Strasse"))
        self.assertNotEqual(dna.word_key("schön"), dna.word_key("schon"))
        self.assertNotEqual(dna.word_key("der Morgen"), dna.word_key("morgen"))
        self.assertNotEqual(dna.word_key("das Essen"), dna.word_key("essen"))
        words: list = []
        source = {"session_id": "s_1", "turn_id": "t_1", "example": None}
        dna.learn_word(words, term="Straße", meaning="yol", source=source, moment=BASE_TIME)
        dna.learn_word(words, term="die Strasse", meaning="cadde", source=dict(source, turn_id="t_2"), moment=BASE_TIME)
        dna.learn_word(words, term="Reservierung", meaning="rezervasyon", source=source, moment=BASE_TIME)
        dna.learn_word(words, term="die Reservierung", meaning="rezervasyon", source=dict(source, turn_id="t_3"), moment=BASE_TIME)
        self.assertEqual([(word["term"], word["meaning"]) for word in words],
                         [("Straße", "yol"), ("die Reservierung", "rezervasyon")])

    def test_morgen_and_der_morgen_get_their_own_cards_and_meanings(self):
        identifier = self.store.roleplay_start("arbeit", at=BASE_TIME)["session"]["id"]
        turn = self.store.roleplay_turn(identifier, speaker="partner", text="Morgen früh, am Morgen um acht.",
                                        at=BASE_TIME + timedelta(seconds=10))["utterance"]
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(minutes=5))
        self.store.roleplay_vocab(identifier, term="morgen", meaning="yarın", turn_id=turn["id"])
        self.store.roleplay_vocab(identifier, term="der Morgen", surface="Morgen", meaning="sabah", turn_id=turn["id"])
        self.assertEqual(sorted((word["term"], word["meaning"]) for word in self.store.vocab_list()),
                         [("der Morgen", "sabah"), ("morgen", "yarın")])

    def test_reviews_need_a_due_word_a_new_task_and_a_new_sentence(self):
        _, results = self.scene_with_words()
        word_id = results[0]["word"]["id"]
        prompt = "Du rufst im Hotel an. Sag mit rezervasyon yapmak, dass du ein Zimmer willst."
        with self.assertRaisesRegex(dna.DeutschLoopError, "not due"):
            self.store.vocab_grade(word_id, result="pass", prompt=prompt, answer="Ich möchte ein Zimmer reservieren.",
                                   at=BASE_TIME + timedelta(hours=2))
        moment = BASE_TIME + timedelta(days=1, hours=1)
        with self.assertRaisesRegex(dna.DeutschLoopError, "already seen"):
            self.store.vocab_grade(word_id, result="pass", prompt=prompt, answer=PARTNER_LINE, at=moment)
        word, status = self.store.vocab_grade(word_id, result="pass", prompt=prompt,
                                              answer="Ich möchte ein Zimmer reservieren.", at=moment)
        self.assertEqual((status, word["review_step"], word["next_review"]), ("graded", 1, dna.iso(moment + timedelta(days=3))))
        _, retry = self.store.vocab_grade(word_id, result="pass", prompt=prompt,
                                          answer="Ich möchte ein Zimmer reservieren.", at=moment + timedelta(minutes=1))
        self.assertEqual(retry, "duplicate")
        later = moment + timedelta(days=3)
        with self.assertRaisesRegex(dna.DeutschLoopError, "prompt was already used"):
            self.store.vocab_grade(word_id, result="pass", prompt=prompt, answer="Wir haben schon reserviert.", at=later)
        hard, _ = self.store.vocab_grade(word_id, result="hard", prompt="Der Chef fragt nach dem Tisch fürs Teamessen.",
                                         answer="Ich habe den Tisch reserviert.", at=later)
        self.assertEqual((hard["review_step"], hard["next_review"]), (1, dna.iso(later + timedelta(days=1))))
        failed, _ = self.store.vocab_grade(word_id, result="fail", prompt="Deine Freundin fragt nach dem Kino.",
                                           answer="Ich habe die Karten gebucht.", correction="Ich habe die Karten reserviert.",
                                           at=later + timedelta(days=1))
        self.assertEqual((failed["review_step"], failed["wrong"], failed["right"]), (0, 1, 1))

    def test_six_passes_master_a_word(self):
        _, results = self.scene_with_words()
        word_id = results[0]["word"]["id"]
        moment = BASE_TIME + timedelta(days=1, hours=1)
        for index in range(6):
            word, _ = self.review(word_id, index, at=moment)
            if word["next_review"]:
                moment = dna.parse_moment(word["next_review"])
        self.assertEqual((word["status"], word["next_review"], word["right"]), ("mastered", None, 6))
        self.assertEqual(self.store.vocab_due(at=moment + timedelta(days=365)), [])

    def test_undo_and_forget_also_repair_the_scene_report(self):
        identifier, results = self.scene_with_words(words=(RESERVIEREN, RESERVIERUNG))
        removed = self.store.vocab_undo(results[1]["word"]["id"])
        self.assertEqual(removed["status"], "removed")
        vocabulary = self.store.roleplay_show(identifier)["session"]["vocabulary"]
        self.assertEqual([item["term"] for item in vocabulary], ["reservieren"])

        word_id = results[0]["word"]["id"]
        before = {key: value for key, value in self.store.vocab_list()[0].items() if key != "undo"}
        self.store.vocab_grade(word_id, result="fail", prompt="Frag nach einem Tisch.", answer="Ich buche einen Tisch.",
                               at=BASE_TIME + timedelta(days=1, hours=1))
        self.assertEqual(self.store.vocab_undo(word_id)["undone"], "grade")
        self.assertEqual({key: value for key, value in self.store.vocab_list()[0].items() if key != "undo"}, before)

        self.store.vocab_forget(word_id)
        self.assertEqual(self.store.vocab_list(), [])
        self.store.roleplay_finish(identifier, at=BASE_TIME + timedelta(minutes=10))
        self.assertEqual(self.store.roleplay_show(identifier)["debrief"]["vocabulary"], [])
        with self.assertRaises(dna.DeutschLoopError):
            self.store.vocab_undo(word_id)

    def test_undoing_a_known_word_restores_its_card_and_keeps_the_earlier_scene(self):
        first_scene, results = self.scene_with_words()
        word_id = results[0]["word"]["id"]
        self.review(word_id, 0, at=BASE_TIME + timedelta(days=1, hours=1))
        before = {key: value for key, value in self.store.vocab_list()[0].items() if key != "undo"}
        second_scene, again = self.scene_with_words(start=BASE_TIME + timedelta(days=2))
        self.assertEqual(again[0]["deck"], "known")
        self.assertEqual(self.store.vocab_undo(word_id)["status"], "undone")
        self.assertEqual({key: value for key, value in self.store.vocab_list()[0].items() if key != "undo"}, before)
        self.assertEqual(self.store.roleplay_show(second_scene)["session"]["vocabulary"], [])
        self.assertEqual([item["term"] for item in self.store.roleplay_show(first_scene)["session"]["vocabulary"]], ["reservieren"])

    def test_a_retry_finishes_a_word_whose_card_was_not_written(self):
        identifier = self.store.roleplay_start("restaurant", at=BASE_TIME)["session"]["id"]
        turn = self.store.roleplay_turn(identifier, speaker="partner", text=PARTNER_LINE,
                                        at=BASE_TIME + timedelta(seconds=10))["utterance"]
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(minutes=5))
        real_write = dna._atomic_write

        def deck_write_fails(path, value):
            if path.name == "vocabulary.json":
                raise dna.DeutschLoopError("disk full")
            real_write(path, value)

        with mock.patch.object(dna, "_atomic_write", side_effect=deck_write_fails):
            with self.assertRaises(dna.DeutschLoopError):
                self.store.roleplay_vocab(identifier, term="reservieren", surface="reserviert",
                                          meaning="rezervasyon yapmak", turn_id=turn["id"])
        self.assertEqual(self.store.vocab_list(), [])
        retried = self.store.roleplay_vocab(identifier, term="reservieren", surface="reserviert",
                                            meaning="rezervasyon yapmak", turn_id=turn["id"])
        self.assertEqual((retried["status"], retried["deck"]), ("duplicate", "added"))
        self.assertEqual([word["id"] for word in self.store.vocab_due(at=BASE_TIME + timedelta(days=2))], [retried["word"]["id"]])

    def test_a_forget_retry_finishes_after_a_failed_write(self):
        identifier, results = self.scene_with_words()
        word_id = results[0]["word"]["id"]
        real_write = dna._atomic_write

        def scene_write_fails(path, value):
            if path.name == "sessions.json":
                raise dna.DeutschLoopError("disk full")
            real_write(path, value)

        with mock.patch.object(dna, "_atomic_write", side_effect=scene_write_fails):
            with self.assertRaises(dna.DeutschLoopError):
                self.store.vocab_forget(word_id)
        self.store.vocab_forget(word_id)
        self.assertEqual(self.store.vocab_list(), [])
        self.assertEqual(self.store.roleplay_show(identifier)["session"]["vocabulary"], [])

    def test_the_debrief_only_promises_a_return_for_words_still_under_review(self):
        _, results = self.scene_with_words()
        word_id = results[0]["word"]["id"]
        moment = BASE_TIME + timedelta(days=1, hours=1)
        for index in range(6):
            word, _ = self.review(word_id, index, at=moment)
            moment = dna.parse_moment(word["next_review"]) if word["next_review"] else moment
        later = moment + timedelta(days=1)
        identifier, again = self.scene_with_words(words=(RESERVIEREN, RESERVIERUNG), start=later)
        self.assertEqual(again[0]["deck"], "known")
        self.store.roleplay_finish(identifier, at=later + timedelta(minutes=10))
        shown = self.store.roleplay_show(identifier)
        self.assertEqual([item["review"] for item in shown["debrief"]["vocabulary"]], ["mastered", "active"])
        self.assertIn("reservieren — rezervasyon yapmak · schon gemeistert", shown["learner_message"])
        self.assertIn("Die übrigen Wörter kommen in deiner Wiederholung", shown["learner_message"])

    def test_words_saved_before_the_deck_existed_are_imported(self):
        identifier, _ = self.scene_with_words(words=(RESERVIEREN, RESERVIERUNG))
        (self.home / "vocabulary.json").unlink()
        imported = dna.StateStore(self.home).vocab_list()
        self.assertEqual(sorted(word["term"] for word in imported), ["die Reservierung", "reservieren"])
        self.assertTrue(all(word["next_review"] == dna.iso(BASE_TIME + timedelta(days=1, minutes=5)) for word in imported))
        self.assertTrue(all(word["sources"][0]["session_id"] == identifier for word in imported))

    def test_cards_show_the_deck_and_word_reviews_count_as_practice(self):
        identifier, _ = self.scene_with_words()
        self.store.roleplay_finish(identifier, at=BASE_TIME + timedelta(minutes=10))
        self.assertIn("Diese Wörter kommen in deiner Wiederholung in neuen Sätzen zurück.",
                      self.store.roleplay_show(identifier)["learner_message"])
        later_today = self.store.recap(at=BASE_TIME + timedelta(hours=2))
        self.assertEqual((later_today["vocabulary"]["total"], later_today["vocabulary"]["due_now"]), (1, 0))
        self.assertTrue(later_today["card"].endswith("Wortschatz: 1 Wort · nächste Wiederholung morgen 12:00"))

        moment = BASE_TIME + timedelta(days=1, hours=1)
        due = self.store.recap(at=moment)
        self.assertTrue(due["card"].endswith("Wortschatz: 1 Wort · 1 fällig"))
        self.assertIn("1 Wort aus deinen Szenen zum Wiederholen fällig", dna.render_recap_text(due))
        self.review(self.store.vocab_due(at=moment)[0]["id"], 0, at=moment)
        summary = self.store.summary(at=moment + timedelta(minutes=5))
        self.assertEqual(summary["streak_days"], 2)
        self.assertIn("Wortschatz: 1 Wort · nächste Wiederholung", dna.render_summary_text(summary))
        recap = self.store.recap(at=moment + timedelta(minutes=5))
        self.assertEqual(recap["word_reviews"], {"total": 1, "pass": 1, "hard": 0, "fail": 0})
        self.assertIn("1 Wortwiederholung (1 bestanden)", dna.render_recap_text(recap))

    def test_the_recap_text_does_not_say_nothing_is_due_while_words_are(self):
        self.record_example(at=BASE_TIME + timedelta(days=1))
        self.scene_with_words()
        recap = self.store.recap(at=BASE_TIME + timedelta(days=1, hours=1))
        self.assertEqual((recap["due_now"], recap["vocabulary"]["due_now"]), (0, 1))
        text = dna.render_recap_text(recap)
        self.assertIn("Keine Fehler fällig. Gerade am schwächsten: mit + Dativ", text)
        self.assertNotIn("Nichts fällig", text)

    def test_cli_word_commands(self):
        self.scene_with_words()
        due = json.loads(self.cli("vocab-due", "--at", "2026-09-11T13:00:00Z"))
        word = due["words"][0]
        self.assertEqual((due["count"], word["meaning"], word["due"]), (1, "rezervasyon yapmak", True))
        self.assertNotIn("seen_answers", word)
        text = self.cli("vocab-due", "--format", "text", "--at", "2026-09-11T13:00:00Z")
        self.assertIn("1. reservieren — rezervasyon yapmak", text)
        self.assertIn("Aus der Szene (Restaurant): „Haben Sie reserviert?", text)
        graded = json.loads(self.cli("vocab-grade", word["id"], "--result", "pass", "--prompt", "Frag im Hotel nach einem Zimmer.",
                                     "--answer", "Kann ich ein Zimmer reservieren?", "--at", "2026-09-11T13:00:00Z"))
        self.assertEqual((graded["status"], graded["word"]["review_step"]), ("graded", 1))
        self.assertEqual(graded["word"]["recent_prompts"], ["Frag im Hotel nach einem Zimmer."])
        listing = self.cli("vocab-list", "--format", "text", "--at", "2026-09-11T13:05:00Z")
        self.assertTrue(listing.startswith("Wortschatz · 1 Wort · 0 fällig"))
        self.assertIn("reservieren  rezervasyon yapmak  ▰▱▱▱▱▱ 1/6   Mo 13:00", listing)
        row = json.loads(self.cli("vocab-list"))["words"][0]
        self.assertEqual(sorted(row), ["due", "id", "meaning", "next_review_local", "review_step", "status", "term"])
        self.assertIn("review_history", json.loads(self.cli("vocab-list", "--verbose"))["words"][0])
