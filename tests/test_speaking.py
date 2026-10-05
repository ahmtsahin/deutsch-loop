from __future__ import annotations

import contextlib
import io
import json
from datetime import timedelta
from unittest import mock

from test_deutsch_loop import BASE_TIME, StoreTestCase, dna


class SpeakingTests(StoreTestCase):
    def scene(self, **kwargs):
        return self.store.roleplay_start("restaurant", at=BASE_TIME, **kwargs)["session"]["id"]

    def turn(self, identifier, text="Wir sind zwei Person.", seconds=30, speaker="learner", **kwargs):
        return self.store.roleplay_turn(identifier, speaker=speaker, text=text, at=BASE_TIME + timedelta(seconds=seconds), **kwargs)["utterance"]

    def plural(self, identifier, turn, **kwargs):
        params = dict(original=turn["text"], corrected=turn["text"].replace("Person.", "Personen."),
                      category="plural", pattern="Person plural is Personen", rule="Plural: Personen",
                      session_id=identifier, turn_id=turn["id"])
        params.update(kwargs)
        return self.store.record(**params)

    def finish(self, identifier):
        self.store.roleplay_finish(identifier, at=BASE_TIME + timedelta(minutes=10))
        return self.store.roleplay_show(identifier)["debrief"]

    def test_scene_stays_ungraded_until_stopped_and_wraps_up_at_next_turn(self):
        identifier = self.scene()
        self.turn(identifier, "Guten Abend. Haben Sie reserviert?", seconds=0, speaker="partner")
        wrong = self.turn(identifier)
        self.assertEqual(self.store.list(), [])
        with self.assertRaisesRegex(dna.DeutschLoopError, "Stop the scene"):
            self.plural(identifier, wrong)
        self.assertIsNone(self.store.roleplay_show(identifier, at=BASE_TIME + timedelta(seconds=299))["debrief"])
        self.assertFalse(self.store.roleplay_show(identifier, at=BASE_TIME + timedelta(seconds=299))["should_close"])
        result = self.store.roleplay_turn(identifier, speaker="learner", text="Danke!", at=BASE_TIME + timedelta(seconds=301))
        self.assertTrue(result["should_close"])
        self.assertEqual(result["learner_turns"], 2)
        self.assertNotIn("corrections", result)
        self.assertEqual(self.store.list(), [])

    def test_duration_is_frozen_before_analysis_and_only_learner_turns_count(self):
        identifier = self.scene()
        self.turn(identifier, "Guten Abend!", seconds=0, speaker="partner")
        self.turn(identifier, "Guten Abend!", seconds=10)
        self.turn(identifier, "Vielen Dank!", seconds=400, speaker="partner")
        stopped = self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(seconds=402))
        self.assertEqual((stopped["duration_seconds"], stopped["turns"]), (402, 1))
        result = self.finish(identifier)
        self.assertEqual((result["duration_seconds"], result["duration_source"]), (402, "elapsed"))
        self.assertEqual(result["learner_turns"], 1)
        again = self.store.roleplay_finish(identifier, turns=100, at=BASE_TIME + timedelta(days=1))
        self.assertEqual(again["duration_seconds"], 402)
        self.assertEqual(again["turns"], 1)
        shown = dna.render_roleplay_text(self.store.roleplay_show(identifier))
        self.assertIn("6m 42s", shown)
        self.assertNotIn("You spoke", shown)

    def test_recorded_scenes_cannot_override_real_duration_or_turn_count(self):
        identifier = self.scene()
        self.turn(identifier)
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(minutes=5))
        with self.assertRaises(dna.DeutschLoopError):
            self.store.roleplay_finish(identifier, turns=8)
        with self.assertRaises(dna.DeutschLoopError):
            self.store.roleplay_finish(identifier, duration_seconds=402)
        self.assertEqual(self.store.roleplay_show(identifier)["session"]["status"], "debriefing")

    def test_turn_retries_are_idempotent_and_distinct_identical_messages_count(self):
        identifier = self.scene()
        first = self.turn(identifier, event_id="msg-1")
        duplicate = self.store.roleplay_turn(identifier, speaker="learner", text=first["text"], event_id="msg-1", at=BASE_TIME + timedelta(seconds=31))
        self.assertEqual(duplicate["status"], "duplicate")
        with self.assertRaises(dna.DeutschLoopError):
            self.turn(identifier, "Andere Antwort.", seconds=32, event_id="msg-1")
        self.turn(identifier, seconds=33, event_id="msg-2")
        self.assertEqual(self.store.roleplay_show(identifier)["learner_turns"], 2)

    def test_turns_and_stop_reject_impossible_timestamps_and_closed_scenes(self):
        identifier = self.scene()
        with self.assertRaises(dna.DeutschLoopError):
            self.turn(identifier, seconds=-1)
        self.turn(identifier, seconds=60)
        with self.assertRaises(dna.DeutschLoopError):
            self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(seconds=59))
        with self.assertRaises(dna.DeutschLoopError):
            self.store.roleplay_finish(identifier, at=BASE_TIME + timedelta(seconds=59))
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(seconds=61))
        with self.assertRaises(dna.DeutschLoopError):
            self.turn(identifier, seconds=62)

    def test_feedback_must_reference_the_actual_learner_sentence(self):
        identifier = self.scene()
        partner = self.turn(identifier, speaker="partner")
        learner = self.turn(identifier, seconds=40)
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(minutes=5))
        for turn, original in ((partner, partner["text"]), (learner, "Invented sentence.")):
            with self.assertRaises(dna.DeutschLoopError):
                self.plural(identifier, turn, original=original)
        wrong, _, _ = self.plural(identifier, learner)
        self.assertEqual(wrong["last_seen"], learner["at"])
        self.assertEqual(wrong["examples"][-1]["session_id"], identifier)
        self.assertEqual(wrong["examples"][-1]["turn_id"], learner["id"])
        result = self.finish(identifier)
        self.assertEqual(result["corrections"][0]["example"]["original"], learner["text"])

    def test_session_recurrences_are_separate_from_prior_history_and_other_scenes(self):
        previous, _, _ = self.store.record(original="Zwei Person kommen.", corrected="Zwei Personen kommen.",
                                          category="plural", pattern="Person plural is Personen", rule="Plural: Personen",
                                          at=BASE_TIME - timedelta(days=1))
        identifier = self.scene()
        turns = [self.turn(identifier, f"Wir sind {number} Person.", seconds=(index + 1) * 30)
                 for index, number in enumerate(("zwei", "drei", "vier", "fünf"))]
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(minutes=5))
        for turn in turns:
            self.plural(identifier, turn)
        result = self.finish(identifier)
        self.assertEqual(result["confirmed_occurrences"], 4)
        self.assertEqual(result["recurring"][0]["session_occurrences"], 4)
        self.assertTrue(result["recurring"][0]["previously_tracked"])
        self.assertEqual(self.store.show(previous["id"])["occurrences"], 5)
        other = self.scene()
        self.turn(other, "Alles gut.")
        self.store.roleplay_stop(other, at=BASE_TIME + timedelta(minutes=1))
        self.assertEqual(self.finish(other)["confirmed_occurrences"], 0)

    def test_feedback_retry_cannot_double_count_even_after_history_trimming(self):
        identifier = self.scene()
        turns = [self.turn(identifier, f"Wir sind {index + 2} Person.", seconds=index * 15) for index in range(14)]
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(minutes=5))
        for turn in turns:
            pattern, _, _ = self.plural(identifier, turn)
        self.assertEqual(len(pattern["examples"]), 12)
        _, status, _ = self.plural(identifier, turns[0])
        self.assertEqual(status, "duplicate")
        result = self.finish(identifier)
        self.assertEqual(result["confirmed_occurrences"], 14)
        self.assertEqual(result["corrections"][0]["example"]["original"], turns[0]["text"])

    def test_retry_repairs_a_partially_saved_session_link(self):
        identifier = self.scene()
        turn = self.turn(identifier)
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(minutes=5))
        with mock.patch.object(self.store, "_session_feedback", side_effect=dna.DeutschLoopError("interrupted")):
            with self.assertRaises(dna.DeutschLoopError):
                self.plural(identifier, turn)
        pattern, status, _ = self.plural(identifier, turn)
        self.assertEqual(status, "duplicate")
        self.assertEqual(pattern["occurrences"], 1)
        self.assertEqual(self.finish(identifier)["confirmed_occurrences"], 1)

    def test_vocab_requires_real_surface_and_preserves_german_dictionary_form(self):
        identifier = self.scene()
        turn = self.turn(identifier, "Haben Sie reserviert? Auf welchen Namen?", speaker="partner")
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(minutes=5))
        result = self.store.roleplay_vocab(identifier, term="reservieren", surface="reserviert", meaning="rezervasyon yapmak", turn_id=turn["id"])
        self.assertEqual(result["vocabulary"][0]["example"], turn["text"])
        again = self.store.roleplay_vocab(identifier, term="reservieren", surface="reserviert", meaning="rezervasyon yapmak", turn_id=turn["id"])
        self.assertEqual(again["status"], "duplicate")
        for surface in ("Hotel", "serviert"):
            with self.assertRaises(dna.DeutschLoopError):
                self.store.roleplay_vocab(identifier, term="Hotel", surface=surface, meaning="otel", turn_id=turn["id"])
        self.assertEqual(len(self.finish(identifier)["vocabulary"]), 1)

    def test_debrief_limits_visible_corrections_to_three_without_inventing_severity(self):
        identifier = self.scene()
        turn = self.turn(identifier, "Satz 1. Satz 2. Satz 3. Satz 4.")
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(minutes=5))
        for index in range(1, 5):
            self.store.record(original=f"Satz {index}.", corrected=f"Korrigierter Satz {index}.",
                              category="other", pattern=f"test pattern {index}", rule="test", session_id=identifier, turn_id=turn["id"])
        result = self.finish(identifier)
        self.assertEqual(result["confirmed_patterns"], 4)
        self.assertEqual(len(result["corrections"]), 3)
        self.assertEqual(result["recurring"], [])

    def test_undo_forget_and_rename_keep_the_debrief_consistent(self):
        identifier = self.scene()
        turns = [self.turn(identifier, seconds=30), self.turn(identifier, "Wir sind drei Person.", seconds=60)]
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(minutes=5))
        first, _, _ = self.plural(identifier, turns[0])
        self.plural(identifier, turns[1])
        self.assertEqual(self.finish(identifier)["confirmed_occurrences"], 2)
        self.store.undo(first["id"])
        self.assertEqual(self.store.roleplay_show(identifier)["debrief"]["confirmed_occurrences"], 1)
        changed = self.store.rename(first["id"], pattern="Person has Personen plural", label="Plural: Personen")["mistake"]
        debrief = self.store.roleplay_show(identifier)["debrief"]
        self.assertEqual(debrief["corrections"][0]["mistake_id"], changed["id"])
        self.assertEqual(debrief["corrections"][0]["label"], "Plural: Personen")
        self.store.forget(changed["id"])
        self.assertEqual(self.store.roleplay_show(identifier)["debrief"]["confirmed_patterns"], 0)

    def test_merging_two_labels_for_one_turn_does_not_double_count_a_root_cause(self):
        identifier = self.scene()
        turn = self.turn(identifier)
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(minutes=5))
        first, _, _ = self.plural(identifier, turn)
        second, _, _ = self.plural(identifier, turn, pattern="plural of Person")
        self.finish(identifier)
        self.store.merge(second["id"], first["id"])
        debrief = self.store.roleplay_show(identifier)["debrief"]
        self.assertEqual(debrief["confirmed_occurrences"], 1)
        self.assertEqual(debrief["confirmed_patterns"], 1)

    def test_undoing_a_merge_restores_the_scene_references(self):
        identifier = self.scene()
        turn = self.turn(identifier)
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(minutes=5))
        first, _, _ = self.plural(identifier, turn)
        second, _, _ = self.plural(identifier, turn, pattern="plural of Person")
        self.finish(identifier)
        self.store.merge(second["id"], first["id"])
        self.store.undo(first["id"])
        debrief = self.store.roleplay_show(identifier)["debrief"]
        self.assertEqual({item["mistake_id"] for item in debrief["corrections"]}, {first["id"], second["id"]})
        session = json.loads((self.home / "sessions.json").read_text(encoding="utf-8"))["sessions"][0]
        self.assertEqual(session["mistake_ids"], [first["id"], second["id"]])

    def test_undo_restores_references_that_changed_after_the_merge(self):
        known = [
            self.record_example(category="plural", pattern="Person plural is Personen", rule="Personen",
                                original="Wir sind drei Person.", corrected="Wir sind drei Personen.",
                                at=BASE_TIME - timedelta(days=2))[0],
            self.record_example(category="plural", pattern="plural of Person", rule="Personen",
                                original="Zwei Person warten.", corrected="Zwei Personen warten.",
                                at=BASE_TIME - timedelta(days=2, hours=-1))[0],
            self.record_example(pattern="bei + dative", rule="bei takes dative", original="Ich wohne bei mein Onkel.",
                                corrected="Ich wohne bei meinem Onkel.", at=BASE_TIME - timedelta(days=1))[0],
            self.record_example(at=BASE_TIME - timedelta(hours=5))[0],
        ]
        target, source, other_source, other_target = (item["id"] for item in known)
        identifier = self.scene()
        turn = self.turn(identifier)
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(minutes=5))
        self.plural(identifier, turn, pattern="plural of Person")
        self.finish(identifier)
        # A second merge rewrites the same list before the first one is undone.
        self.store.merge(source, target)
        self.store.merge(other_source, other_target)
        self.store.undo(target)
        self.store.undo(other_target)
        session = json.loads((self.home / "sessions.json").read_text(encoding="utf-8"))["sessions"][0]
        self.assertEqual(set(session["known_pattern_ids"]), {target, source, other_source, other_target})
        self.assertEqual(session["mistake_ids"], [source])
        debrief = self.store.roleplay_show(identifier)["debrief"]
        self.assertEqual(debrief["corrections"][0]["mistake_id"], source)
        self.assertTrue(debrief["corrections"][0]["previously_tracked"])

    def test_undo_after_the_scene_was_finished_on_merged_ids(self):
        identifier = self.scene()
        turn = self.turn(identifier)
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(minutes=5))
        first, _, _ = self.plural(identifier, turn)
        second, _, _ = self.plural(identifier, turn, pattern="plural of Person")
        self.store.merge(second["id"], first["id"])
        self.finish(identifier)
        self.store.undo(first["id"])
        session = json.loads((self.home / "sessions.json").read_text(encoding="utf-8"))["sessions"][0]
        self.assertEqual(session["mistake_ids"], [first["id"], second["id"]])

    def test_transcript_cannot_establish_capitalization_or_punctuation_errors(self):
        identifier = self.scene(input_mode="transcript")
        turn = self.turn(identifier, "ich habe eine reservierung")
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(minutes=5))
        for category in ("spelling", "punctuation"):
            with self.assertRaisesRegex(dna.DeutschLoopError, "speech transcript"):
                self.plural(identifier, turn, category=category, pattern="German nouns are capitalized", corrected="Ich habe eine Reservierung.")
        self.assertEqual(self.store.list(), [])

    def test_speak_cli_and_text_debrief_roundtrip(self):
        def cli(*args, as_text=False):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = dna.main(["--home", str(self.home), *args])
            self.assertEqual(code, 0)
            return output.getvalue() if as_text else json.loads(output.getvalue())

        started = cli("speak", "restaurant", "--minutes", "5", "--at", "2026-09-10T12:00:00Z")
        identifier = started["session"]["id"]
        turn = cli("roleplay-turn", identifier, "--speaker", "learner", "--text", "Wir sind zwei Person.", "--at", "2026-09-10T12:01:00Z")["utterance"]
        cli("roleplay-stop", identifier, "--at", "2026-09-10T12:06:42Z")
        cli("record", "--session-id", identifier, "--turn-id", turn["id"], "--original", turn["text"],
            "--corrected", "Wir sind zwei Personen.", "--category", "plural", "--pattern", "Person plural is Personen", "--rule", "Plural: Personen")
        text = cli("roleplay-finish", identifier, "--format", "text", "--at", "2026-09-10T12:10:00Z", as_text=True)
        self.assertIn("AUSWERTUNG DER SZENE", text)
        self.assertIn("6m 42s", text)
        self.assertIn("Wir sind zwei Personen.", text)
        shown = cli("roleplay-show", identifier)
        self.assertEqual(shown["learner_turns"], 1)
        self.assertEqual(shown["debrief"]["confirmed_occurrences"], 1)
        self.assertEqual(cli("speak", "doctor")["session"]["scenario"], "arzt")

    def test_interrupted_scene_and_debrief_are_resumable(self):
        identifier = self.scene()
        turn = self.turn(identifier, "Ja, ich habe reserviert.")
        self.store = dna.StateStore(self.home)
        scene = self.store.recap(at=BASE_TIME + timedelta(minutes=1))["active_roleplay"]
        self.assertEqual((scene["session_id"], scene["status"]), (identifier, "active"))
        self.assertEqual(self.store.roleplay_show(identifier)["session"]["utterances"][0]["text"], turn["text"])
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(minutes=5))
        self.assertEqual(self.store.recap(at=BASE_TIME + timedelta(minutes=6))["active_roleplay"]["status"], "debriefing")
        with self.assertRaises(dna.DeutschLoopError):
            self.store.roleplay_finish(identifier, at=BASE_TIME + timedelta(minutes=4))
        self.finish(identifier)
        self.assertIsNone(self.store.recap(at=BASE_TIME + timedelta(minutes=11))["active_roleplay"])

    def test_vocabulary_is_bounded_and_completed_scenes_reject_new_feedback(self):
        identifier = self.scene()
        turn = self.turn(identifier, "Brot Wasser Suppe Kaffee Tee Milch", speaker="partner")
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(minutes=5))
        for term in ("Brot", "Wasser", "Suppe", "Kaffee", "Tee"):
            self.store.roleplay_vocab(identifier, term=term, meaning="test meaning", turn_id=turn["id"])
        with self.assertRaises(dna.DeutschLoopError):
            self.store.roleplay_vocab(identifier, term="Milch", meaning="süt", turn_id=turn["id"])
        self.finish(identifier)
        with self.assertRaises(dna.DeutschLoopError):
            self.store.roleplay_vocab(identifier, term="Milch", meaning="süt", turn_id=turn["id"])
        with self.assertRaises(dna.DeutschLoopError):
            self.plural(identifier, turn)

    def test_speaking_demo_counts_real_scripted_occurrences_and_elapsed_time(self):
        import demo

        with mock.patch.object(dna, "utc_now", return_value=BASE_TIME + timedelta(minutes=10)):
            identifier = demo.seed_speaking_scene(self.home)
        result = self.store.roleplay_show(identifier)
        self.assertEqual(result["debrief"]["duration_seconds"], 402)
        self.assertEqual(result["debrief"]["learner_turns"], 6)
        self.assertEqual(len(result["debrief"]["corrections"]), 3)
        self.assertEqual(result["debrief"]["recurring"][0]["label"], "Plural von Person: Personen")
        self.assertEqual(result["debrief"]["recurring"][0]["session_occurrences"], 4)
        self.assertEqual([item["term"] for item in result["debrief"]["vocabulary"]], ["reservieren", "die Reservierung", "auf den Namen"])
        self.assertEqual(result["session"]["utterances"][2]["text"], "Auf welchen Namen?")

    def test_legacy_session_without_linked_evidence_does_not_invent_corrections(self):
        mistake, _, _ = self.record_example()
        identifier = self.scene()
        self.store.roleplay_finish(identifier, turns=8, duration_seconds=100, mistake_ids=[mistake["id"]], at=BASE_TIME + timedelta(minutes=5))
        result = self.store.roleplay_show(identifier)
        self.assertEqual(result["debrief"]["corrections"], [])
        self.assertEqual(result["debrief"]["duration_source"], "provided")
        self.assertIn("Angegebene Dauer", dna.render_roleplay_text(result))

    def test_bitir_is_an_end_control_and_is_not_counted_as_an_answer(self):
        identifier = self.scene()
        turn = self.turn(identifier)
        result = self.store.roleplay_turn(identifier, speaker="learner", text="Bitir", at=BASE_TIME + timedelta(seconds=90))
        self.assertEqual(result["control"], "end_scene")
        self.assertEqual(result["next_action"], "prepare_debrief")
        self.assertIsNone(result["learner_message"])
        self.assertEqual(result["session"]["status"], "debriefing")
        self.assertEqual(result["learner_turns"], 1)
        self.assertEqual(result["session"]["duration_seconds"], 90)
        self.assertEqual(result["session"]["utterances"], [turn])
        repeated = self.store.roleplay_turn(identifier, speaker="learner", text="BİTİR!", at=BASE_TIME + timedelta(seconds=100))
        self.assertEqual(repeated["session"]["ended_at"], result["session"]["ended_at"])
        self.plural(identifier, turn)
        self.finish(identifier)
        replay = self.store.roleplay_turn(identifier, speaker="learner", text="bitirelim", at=BASE_TIME + timedelta(minutes=11))
        self.assertTrue(replay["response_required"])
        self.assertEqual(replay["next_action"], "present_debrief")
        self.assertIn("Wir sind zwei Personen.", replay["learner_message"])
        self.assertEqual(replay["learner_turns"], 1)

    def test_indirect_stop_words_and_partner_speech_do_not_end_a_scene(self):
        identifier = self.scene()
        for index, text in enumerate(("Was bedeutet bitir?", "Bitte nicht beenden.", "Bitirme.", "Ben bitir demedim."), 1):
            result = self.store.roleplay_turn(identifier, speaker="learner", text=text, at=BASE_TIME + timedelta(seconds=index))
            self.assertEqual(result["status"], "stored")
        self.turn(identifier, "Bitir", speaker="partner", seconds=30)
        self.assertEqual(self.store.roleplay_show(identifier)["session"]["status"], "active")

    def test_default_json_finish_contains_the_report_to_send_to_the_learner(self):
        identifier = self.scene()
        turn = self.turn(identifier)
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(minutes=4))
        self.plural(identifier, turn)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = dna.main(["--home", str(self.home), "roleplay-finish", identifier,
                             "--at", "2026-09-10T12:06:00Z"])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "finished")
        self.assertEqual(result["next_action"], "present_debrief")
        self.assertTrue(result["response_required"])
        self.assertEqual(result["learner_message"], dna.render_roleplay_text(result))
        self.assertIn(result["debrief"]["corrections"][0]["example"]["corrected"], result["learner_message"])
        self.assertIn("4m 00s", result["learner_message"])

    def test_missing_report_can_be_recovered_without_rewriting_or_recounting_state(self):
        identifier = self.scene()
        turn = self.turn(identifier)
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(minutes=4))
        pattern, _, _ = self.plural(identifier, turn)
        self.finish(identifier)
        snapshot = {name: (self.home / name).read_bytes() for name in ("sessions.json", "mistakes.json", "profile.json")}
        self.store = dna.StateStore(self.home)
        recap = self.store.recap(at=BASE_TIME + timedelta(minutes=12))
        self.assertIsNone(recap["active_roleplay"])
        self.assertEqual(recap["last_roleplay"]["session_id"], identifier)
        recovered = self.store.roleplay_show(recap["last_roleplay"]["session_id"])
        self.assertTrue(recovered["response_required"])
        self.assertIn("Wir sind zwei Personen.", recovered["learner_message"])
        self.assertEqual(self.store.show(pattern["id"])["occurrences"], 1)
        self.assertEqual(snapshot, {name: (self.home / name).read_bytes() for name in snapshot})

    def test_prepared_report_reflects_repair_and_exists_without_recorded_errors(self):
        identifier = self.scene()
        turn = self.turn(identifier)
        self.store.roleplay_stop(identifier, at=BASE_TIME + timedelta(minutes=1))
        pattern, _, _ = self.plural(identifier, turn)
        self.finish(identifier)
        self.store.forget(pattern["id"])
        repaired = self.store.roleplay_show(identifier)
        self.assertTrue(repaired["response_required"])
        self.assertTrue(repaired["learner_message"])
        self.assertEqual(repaired["debrief"]["corrections"], [])
        self.assertNotIn("Wir sind zwei Personen.", repaired["learner_message"])

    def test_latest_completed_report_is_separate_from_an_active_scene(self):
        old = self.scene()
        self.turn(old)
        self.store.roleplay_stop(old, at=BASE_TIME + timedelta(minutes=1))
        self.finish(old)
        current = self.store.roleplay_start("arbeit", at=BASE_TIME + timedelta(minutes=12))["session"]["id"]
        recap = self.store.recap(at=BASE_TIME + timedelta(minutes=13))
        self.assertEqual(recap["active_roleplay"]["session_id"], current)
        self.assertEqual(recap["last_roleplay"]["session_id"], old)
        self.assertIsNone(self.store.roleplay_show(current)["learner_message"])
