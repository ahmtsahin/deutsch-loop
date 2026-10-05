from __future__ import annotations

import contextlib
import io
import json
import os
from datetime import timedelta
from unittest import mock

from test_deutsch_loop import BASE_TIME, CASE_REVIEWS, StoreTestCase, dna


class LearningLoopTests(StoreTestCase):
    def assisted(self, identifier, *, at=None, **overrides):
        args = dict(outcome="assisted", prompt="Schau noch einmal auf mit mein Chef.",
                    answer="Ich spreche mit meinem Chef.", strategy="Kasusfrage",
                    hint="Frage dich: mit wem?", at=at or BASE_TIME + timedelta(minutes=5))
        args.update(overrides)
        return self.store.coach(identifier, **args)

    def test_six_early_passes_cannot_create_mastery(self):
        first, _, _ = self.record_example()
        for index, (prompt, answer) in enumerate(CASE_REVIEWS, 1):
            with self.subTest(minutes=index * 6), self.assertRaisesRegex(dna.DeutschLoopError, "not due"):
                self.store.grade(first["id"], result="pass", prompt=prompt, answer=answer,
                                 at=BASE_TIME + timedelta(minutes=index * 6))
        self.assertEqual(self.store.show(first["id"]), first)

    def test_review_retry_is_idempotent_but_new_early_answers_are_not_passes(self):
        first, _, _ = self.record_example()
        due = BASE_TIME + timedelta(days=1)
        passed, _ = self.grade_example(first["id"], result="pass", at=due)
        repeated, status = self.grade_example(first["id"], result="pass", at=due + timedelta(minutes=1))
        self.assertEqual((status, repeated["review_attempts"]), ("duplicate", 1))
        with self.assertRaisesRegex(dna.DeutschLoopError, "not due"):
            self.grade_example(first["id"], result="pass", answer=CASE_REVIEWS[1][1], at=due + timedelta(minutes=2))
        self.assertEqual(self.store.show(first["id"]), passed)

    def test_review_requires_new_prompt_answer_and_no_hint(self):
        first, _, _ = self.record_example()
        self.grade_example(first["id"], result="pass", at=BASE_TIME + timedelta(days=1))
        before = self.store.show(first["id"])
        at = BASE_TIME + timedelta(days=4)
        attempts = [
            {"prompt": "", "answer": CASE_REVIEWS[1][1]},
            {"prompt": CASE_REVIEWS[1][0], "answer": " "},
            {"prompt": CASE_REVIEWS[0][0].upper() + "!", "answer": CASE_REVIEWS[1][1]},
            {"prompt": CASE_REVIEWS[1][0], "answer": "ICH  FAHRE MIT DEM BUS!"},
            {"prompt": CASE_REVIEWS[1][0], "answer": CASE_REVIEWS[1][1], "hint": "mit wem?", "strategy": "Kasusfrage"},
            {"prompt": CASE_REVIEWS[1][0], "answer": first["examples"][0]["corrected"]},
        ]
        for args in attempts:
            with self.subTest(args=args), self.assertRaises(dna.DeutschLoopError):
                self.store.grade(first["id"], result="pass", at=at, **args)
        self.assertEqual(self.store.show(first["id"]), before)

    def test_novelty_index_outlives_detailed_review_history(self):
        first, _, _ = self.record_example()
        item, _ = self.grade_example(first["id"], result="pass", at=BASE_TIME + timedelta(days=1))
        for index in range(dna.HISTORY_LIMIT + 1):
            item, _ = self.store.grade(first["id"], result="hard", prompt=f"Neue Testsituation {index}",
                                       answer=f"Testantwort {index}", at=dna.parse_moment(item["next_review"]))
        self.assertFalse(any(event.get("prompt") == CASE_REVIEWS[0][0] for event in item["review_history"]))
        for prompt, answer in ((CASE_REVIEWS[0][0], CASE_REVIEWS[1][1]), (CASE_REVIEWS[1][0], CASE_REVIEWS[0][1])):
            with self.assertRaises(dna.DeutschLoopError):
                self.store.grade(first["id"], result="pass", prompt=prompt, answer=answer, at=dna.parse_moment(item["next_review"]))
        self.assertNotIn("seen_answers", dna.public(item))

    def test_first_error_survives_trimming_and_undo(self):
        first, _, _ = self.record_example()
        for day in range(1, 15):
            _, _, extra = self.record_example(original="Ich fahre mit mein Auto.", corrected="Ich fahre mit meinem Auto.",
                                              at=BASE_TIME + timedelta(days=day), event_id=f"recurrence-{day}")
        self.assertEqual(extra["previous"]["first_example"]["original"], first["examples"][0]["original"])
        self.assertTrue(extra["previous"]["first_example_is_original"])
        self.assertEqual(len(self.store.show(first["id"])["examples"]), dna.EXAMPLE_LIMIT)
        self.store.undo(first["id"])
        timeline = dna.render_show_text({"mistake": self.store.show(first["id"])})
        self.assertIn("Erster Fehler · 2026-09-10: Ich spreche mit mein Chef.", timeline)

    def test_guided_practice_is_persistent_but_does_not_change_scores_or_schedule(self):
        first, _, _ = self.record_example()
        coached = self.assisted(first["id"])
        self.store = dna.StateStore(self.home)
        after = self.store.show(first["id"])
        for field in ("occurrences", "correct_uses", "review_step", "review_attempts", "next_review"):
            self.assertEqual(after[field], first[field], field)
        self.assertTrue(self.store.list()[0]["new"])
        focus = self.store.recap(at=BASE_TIME + timedelta(minutes=10))["callback"]
        self.assertEqual(focus["coaching"]["helpful_hint"]["hint"], "Frage dich: mit wem?")
        self.assertEqual(coached["attempt"]["at_local"], "2026-09-10T12:05:00+00:00")
        self.assertIsNone(coached["learning_proof"])

    def test_first_session_win_then_next_day_spontaneous_transfer(self):
        first, _, _ = self.record_example()
        self.assisted(first["id"])
        immediate = self.store.coach(first["id"], outcome="independent", prompt=CASE_REVIEWS[0][0],
                                     answer=CASE_REVIEWS[0][1], at=BASE_TIME + timedelta(minutes=8))
        self.assertIsNone(immediate["learning_proof"])
        self.assertEqual(immediate["mistake"]["review_step"], 0)
        next_day = BASE_TIME + timedelta(days=1, minutes=10)
        observed = self.store.observe([first["id"]], context="Wir haben mit unseren Kunden gesprochen.", at=next_day)[0]
        proof = observed["learning_proof"]
        self.assertEqual(observed["status"], "observed_and_advanced")
        self.assertEqual(proof["with_help"]["strategy"], "Kasusfrage")
        self.assertEqual(proof["independent"]["source"], "spontaneous")
        self.assertEqual(proof["independent"]["at_local"], "2026-09-11T12:10:00+00:00")
        later = self.store.observe([first["id"]], context=CASE_REVIEWS[1][1], at=next_day + timedelta(minutes=10))[0]
        self.assertIsNone(later["learning_proof"], "The same achievement should not be announced on every turn")
        timeline = dna.render_show_text({"mistake": self.store.show(first["id"])})
        self.assertIn("Ohne Hilfe · 2026-09-11 (frei geschrieben)", timeline)

    def test_supported_review_remembers_hint_and_later_review_proves_transfer(self):
        first, _, _ = self.record_example()
        item, _ = self.grade_example(first["id"], result="hard", strategy="Kasusfrage", hint="Mit wem?",
                                      at=BASE_TIME + timedelta(days=1))
        self.assertEqual(item["helpful_hint"]["outcome"], "assisted")
        passed, _ = self.grade_example(first["id"], result="pass", at=BASE_TIME + timedelta(days=2))
        self.assertEqual(passed["learning_proof"]["independent"]["source"], "review")
        self.assertEqual(passed["review_step"], 1)

    def test_shown_answers_and_unsuccessful_hints_are_not_helpful_evidence(self):
        first, _, _ = self.record_example()
        for outcome in ("shown", "miss"):
            self.assisted(first["id"], outcome=outcome)
            self.assertIsNone(self.store.show(first["id"])["helpful_hint"])
        with self.assertRaises(dna.DeutschLoopError):
            self.assisted(first["id"], outcome="independent")
        with self.assertRaises(dna.DeutschLoopError):
            self.assisted(first["id"], hint=None)
        next_day = self.store.observe([first["id"]], context=CASE_REVIEWS[0][1], at=BASE_TIME + timedelta(days=1))[0]
        self.assertIsNone(next_day["learning_proof"])

    def test_a_copied_correction_is_not_independent_practice(self):
        first, _, _ = self.record_example()
        with self.assertRaises(dna.DeutschLoopError):
            self.store.coach(first["id"], outcome="independent", prompt="Noch einmal bitte.",
                             answer=first["examples"][0]["corrected"], at=BASE_TIME + timedelta(minutes=5))
        self.assertEqual(self.store.show(first["id"]), first)

    def test_an_answer_given_after_a_hint_counts_for_nothing_later(self):
        # Resuming an interrupted lesson must not turn the assisted repair into unaided evidence.
        first, _, _ = self.record_example()
        self.assisted(first["id"])
        later = BASE_TIME + timedelta(days=1)
        with self.assertRaises(dna.DeutschLoopError):
            self.store.coach(first["id"], outcome="independent", prompt="Weiter mit der Aufgabe von gestern.",
                             answer="Ich spreche mit meinem Chef.", at=later)
        result = self.store.observe([first["id"]], context="Ich spreche mit meinem Chef.", at=later)[0]
        self.assertEqual((result["status"], result["learning_proof"]), ("seen", None))
        after = self.store.show(first["id"])
        self.assertEqual((after["correct_uses"], after["review_step"]), (0, 0))

    def test_repeated_spontaneous_sentence_counts_once(self):
        first, _, _ = self.record_example()
        self.store.observe([first["id"]], context=CASE_REVIEWS[0][1], at=BASE_TIME + timedelta(days=1))
        repeated = self.store.observe([first["id"]], context=CASE_REVIEWS[0][1].upper(), at=BASE_TIME + timedelta(days=4))[0]
        self.assertEqual(repeated["status"], "seen")
        after = self.store.show(first["id"])
        self.assertEqual((after["correct_uses"], after["review_step"]), (1, 1))
        self.assertEqual(len(self.store.due(at=BASE_TIME + timedelta(days=4))), 1)

    def test_coach_retry_and_undo_restore_memory(self):
        first, _, _ = self.record_example()
        self.assisted(first["id"])
        self.assertEqual(self.assisted(first["id"])["status"], "duplicate")
        self.assertEqual(len(self.store.show(first["id"])["coaching_history"]), 1)
        self.store.undo(first["id"])
        after = self.store.show(first["id"])
        self.assertIsNone(after["helpful_hint"])
        self.assertEqual(after["coaching_history"], [])
        self.assertEqual(after["next_review"], first["next_review"])

    def test_undo_transfer_restores_schedule_and_removes_proof(self):
        first, _, _ = self.record_example()
        self.assisted(first["id"])
        before = self.store.show(first["id"])
        self.store.observe([first["id"]], context=CASE_REVIEWS[0][1], at=BASE_TIME + timedelta(days=1))
        self.store.undo(first["id"])
        restored = self.store.show(first["id"])
        self.assertIsNone(restored["learning_proof"])
        self.assertEqual(restored["next_review"], before["next_review"])
        self.assertEqual(restored["seen_answers"], before["seen_answers"])

    def test_recurring_error_after_help_prevents_a_false_transfer_claim(self):
        first, _, _ = self.record_example()
        self.assisted(first["id"])
        self.record_example(at=BASE_TIME + timedelta(hours=1), event_id="recurrence")
        observation = self.store.observe([first["id"]], context=CASE_REVIEWS[0][1], at=BASE_TIME + timedelta(days=1))[0]
        self.assertIsNone(observation["learning_proof"])

    def test_transfer_requires_a_later_local_day(self):
        first, _, _ = self.record_example()
        with mock.patch.dict(os.environ, {"DEUTSCHLOOP_UTC_OFFSET": "+02:00"}):
            self.assisted(first["id"], at=BASE_TIME + timedelta(hours=11))
            result = self.store.observe([first["id"]], context=CASE_REVIEWS[0][1], at=BASE_TIME + timedelta(hours=12, minutes=1))[0]
            self.assertIsNone(result["learning_proof"], "Crossing UTC midnight is not a new local day")

    def test_goal_and_due_pattern_personalize_roleplay_with_explicit_focus_override(self):
        first, _, _ = self.record_example()
        self.assisted(first["id"])
        self.store.init_profile(goal="Morgen möchte ich mit meinem Chef einen Termin klären.")
        session = self.store.roleplay_start("arbeit", at=BASE_TIME + timedelta(days=1))
        contract = session["contract"]
        self.assertEqual(contract["focus_pattern"]["id"], first["id"])
        self.assertEqual(contract["focus_pattern"]["coaching"]["helpful_hint"]["strategy"], "Kasusfrage")
        self.assertIn("Termin", contract["personal_goal"])
        override = self.store.roleplay_start("arbeit", focus="Höflich widersprechen")
        self.assertEqual(override["contract"]["focus"], "Höflich widersprechen")
        self.assertIsNone(override["contract"]["focus_pattern"])
        self.store.forget(first["id"])
        sessions = json.loads((self.home / "sessions.json").read_text(encoding="utf-8"))["sessions"]
        self.assertIsNone(sessions[0]["focus_id"])
        self.store.init_profile(goal="")
        self.assertFalse(self.store.roleplay_start("arbeit")["contract"]["personal_goal"])

    def test_merge_and_rename_preserve_support_proof_and_oldest_sentence(self):
        source, _, _ = self.record_example()
        self.assisted(source["id"])
        self.store.observe([source["id"]], context=CASE_REVIEWS[0][1], at=BASE_TIME + timedelta(days=1))
        target, _, _ = self.record_example(pattern="mit governs object case", original="Ich fahre mit mein Auto.",
                                         corrected="Ich fahre mit meinem Auto.", at=BASE_TIME + timedelta(days=2))
        merged = self.store.merge(source["id"], target["id"])
        self.assertEqual(merged["first_example"]["original"], source["examples"][0]["original"])
        self.assertIsNotNone(merged["learning_proof"])
        self.assertEqual(merged["helpful_hint"]["strategy"], "Kasusfrage")
        self.assertIn(dna.text_fingerprint(CASE_REVIEWS[0][1]), merged["seen_answers"])
        renamed = self.store.rename(target["id"], pattern="mit + dative")["mistake"]
        self.assertEqual(renamed["learning_proof"], merged["learning_proof"])

    def test_legacy_truncated_history_is_not_presented_as_the_original_sentence(self):
        first, _, _ = self.record_example()
        self.record_example(original="Ich fahre mit mein Auto.", corrected="Ich fahre mit meinem Auto.", at=BASE_TIME + timedelta(days=1))
        document = json.loads((self.home / "mistakes.json").read_text(encoding="utf-8"))
        document["schema_version"] = 2
        item = document["mistakes"][0]
        item["examples"] = item["examples"][1:]
        for field in ("first_example", "coaching_history", "helpful_hint", "learning_proof", "seen_prompts", "seen_answers", "undo"):
            item.pop(field, None)
        (self.home / "mistakes.json").write_text(json.dumps(document), encoding="utf-8")
        _, _, extra = self.record_example(at=BASE_TIME + timedelta(days=2), event_id="new")
        self.assertFalse(extra["previous"]["first_example_is_original"])
        self.assertEqual(extra["previous"]["first_example"]["original"], "Ich fahre mit mein Auto.")
        self.assertIn("Frühester erhaltener Fehler", dna.render_show_text({"mistake": self.store.show(first["id"])}))

    def test_cli_can_complete_a_coaching_to_review_journey(self):
        first, _, _ = self.record_example()

        def cli(*args):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = dna.main(["--home", str(self.home), *args])
            self.assertEqual(status, 0)
            return json.loads(output.getvalue())

        cli("init", "--goal", "Beim Kundengespräch sicherer werden")
        result = cli("coach", first["id"], "--outcome", "assisted", "--prompt", "Prüfe mit mein Chef.",
                     "--answer", "Ich spreche mit meinem Chef.", "--strategy", "Kasusfrage", "--hint", "Mit wem?",
                     "--at", "2026-09-10T12:05:00Z")
        self.assertEqual(result["status"], "coached")
        result = cli("grade", first["id"], "--result", "pass", "--prompt", CASE_REVIEWS[0][0],
                     "--answer", CASE_REVIEWS[0][1], "--at", "2026-09-11T12:05:00Z")
        self.assertEqual(result["learning_proof"]["independent"]["source"], "review")
        self.assertIsNone(cli("grade", first["id"], "--result", "pass", "--prompt", CASE_REVIEWS[0][0],
                             "--answer", CASE_REVIEWS[0][1], "--at", "2026-09-11T12:06:00Z")["learning_proof"])

    def test_support_and_transfer_survive_coaching_history_trimming(self):
        first, _, _ = self.record_example()
        self.assisted(first["id"])
        self.store.observe([first["id"]], context=CASE_REVIEWS[0][1], at=BASE_TIME + timedelta(days=1))
        proof = self.store.show(first["id"])["learning_proof"]
        for index in range(dna.HISTORY_LIMIT + 1):
            self.assisted(first["id"], outcome="shown", prompt=f"Weitere Erklärung {index}",
                          at=BASE_TIME + timedelta(days=2, minutes=index * 10))
        stored = self.store.show(first["id"])
        self.assertEqual(len(stored["coaching_history"]), dna.HISTORY_LIMIT)
        self.assertTrue(all(entry["outcome"] == "shown" for entry in stored["coaching_history"]))
        self.assertEqual(stored["learning_proof"], proof)
        self.assertEqual(stored["helpful_hint"]["id"], proof["with_help"]["id"])

    def test_legacy_undo_snapshot_is_migrated_with_the_pattern(self):
        first, _, _ = self.record_example()
        self.record_example(at=BASE_TIME + timedelta(days=1), event_id="recurrence")
        document = json.loads((self.home / "mistakes.json").read_text(encoding="utf-8"))
        document["schema_version"] = 2
        item = document["mistakes"][0]
        for state in (item, item["undo"]["state"]):
            for field in ("first_example", "coaching_history", "helpful_hint", "learning_proof", "seen_prompts", "seen_answers"):
                state.pop(field, None)
        (self.home / "mistakes.json").write_text(json.dumps(document), encoding="utf-8")
        self.store.undo(first["id"])
        restored = self.store.show(first["id"])
        self.assertEqual(restored["first_example"], first["first_example"])
        self.assertEqual(restored["next_review"], first["next_review"])
        self.assertIn(dna.text_fingerprint(first["examples"][0]["corrected"]), restored["seen_answers"])
        self.assertIsNone(restored["helpful_hint"])

    def test_learning_demo_has_two_practice_attempts_and_one_spontaneous_advance(self):
        import demo

        with mock.patch.object(dna, "utc_now", return_value=BASE_TIME + timedelta(days=1, minutes=1)):
            demo.seed_learning_loop(self.home)
        pattern = self.store.show(dna.mistake_id("case", "mit + dative"))
        self.assertEqual([entry["outcome"] for entry in pattern["coaching_history"]], ["assisted", "independent"])
        self.assertEqual(pattern["review_step"], 1)
        self.assertEqual(pattern["learning_proof"]["independent"]["source"], "spontaneous")
        self.assertEqual(pattern["learning_proof"]["independent"]["answer"], "Wir haben mit unseren Kunden gesprochen.")
