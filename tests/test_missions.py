from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from unittest import mock

from test_agent_contract import CliTestCase
from test_deutsch_loop import BASE_TIME, ROOT, StoreTestCase, dna


class MissionTests(StoreTestCase):
    def mission(self, **overrides):
        arguments = dict(goal="Cuma Almanca iş görüşmem var.", scenario="interview", deadline="cuma", at=BASE_TIME)
        arguments.update(overrides)
        return self.store.mission_create(**arguments)["mission"]["id"]

    def attempt(self, identifier, *, day=0, text="Ich bin Entwickler und habe mit meinem Team ein Kundenportal gebaut.", support="none"):
        start = BASE_TIME + timedelta(days=day, minutes=1)
        scene = self.store.mission_start(identifier, at=start)
        sid = scene["session"]["id"]
        self.store.roleplay_turn(sid, speaker="partner", text=scene["contract"]["opening"], at=start)
        if support != "none":
            self.store.roleplay_turn(sid, speaker="partner", text="Denk an eine konkrete Situation mit deinem Team.",
                                     support=support, at=start + timedelta(seconds=10))
        turn = self.store.roleplay_turn(sid, speaker="learner", text=text, at=start + timedelta(seconds=30))["utterance"]
        self.store.roleplay_stop(sid, at=start + timedelta(minutes=2))
        return scene, turn

    def assess(self, identifier, scene, turn, *, day=0, result="achieved", support="none", note="The learner gave a relevant concrete example."):
        self.store.roleplay_finish(scene["session"]["id"], at=BASE_TIME + timedelta(days=day, minutes=4))
        return self.store.mission_assess(identifier, session_id=scene["session"]["id"], result=result, support=support,
                                         evidence_turn_ids=[turn["id"]], note=note, at=BASE_TIME + timedelta(days=day, minutes=5))

    def test_goal_date_and_plan_survive_a_new_chat_without_creating_learning_scores(self):
        identifier = self.mission()
        self.store = dna.StateStore(self.home)
        view = self.store.mission_show(identifier, at=BASE_TIME)
        self.assertEqual(view["scenario"], "bewerbung")
        self.assertEqual(view["deadline"], "2026-09-11")
        self.assertEqual(view["completed_steps"], 0)
        self.assertEqual([step["id"] for step in view["steps"]], ["introduction", "difficult_questions", "followup"])
        self.assertEqual(self.store.list(), [])
        recap = self.store.recap(at=BASE_TIME)
        self.assertEqual(recap["missions"][0]["id"], identifier)
        self.assertIsNone(recap["last_activity_at"])

    def test_creation_retry_reuses_the_active_goal(self):
        identifier = self.mission()
        retry = self.store.mission_create(goal="Cuma Almanca iş görüşmem var.", scenario="bewerbung", deadline="2026-09-11", at=BASE_TIME)
        self.assertEqual(retry["status"], "existing")
        self.assertEqual(retry["mission"]["id"], identifier)
        self.assertEqual(len(self.store.mission_list()), 1)

    def test_relative_dates_follow_the_local_calendar_and_weekday_language(self):
        with mock.patch.dict(os.environ, {"DEUTSCHLOOP_UTC_OFFSET": "+02:00"}):
            near_midnight = dna.parse_moment("2026-10-01T23:30:00Z")
            for word in ("cuma", "Freitag", "friday", "today", "bugün", "heute"):
                self.assertEqual(dna.parse_deadline(word, near_midnight), "2026-10-02")
            self.assertEqual(dna.parse_deadline("yarın", near_midnight), "2026-10-03")
            self.assertEqual(dna.parse_deadline("pazartesi", near_midnight), "2026-10-05")
        for invalid in ("2026-02-30", "20261002", "next friday", "soon"):
            with self.assertRaises(dna.DeutschLoopError):
                dna.parse_deadline(invalid, BASE_TIME)

    def test_invalid_goal_or_scenario_does_not_save_a_mission(self):
        for overrides in ({"goal": " "}, {"scenario": "missing"}, {"deadline": "2026-02-30"}):
            with self.assertRaises(dna.DeutschLoopError):
                self.mission(**overrides)
        self.assertFalse(self.store.missions_path.exists())

    def test_three_unaided_steps_complete_the_communication_plan_without_grading_patterns(self):
        mistake, _, _ = self.record_example(at=BASE_TIME - timedelta(days=1))
        identifier = self.mission()
        before = self.store.mistakes_path.read_bytes()
        for day in range(3):
            scene, turn = self.attempt(identifier, day=day)
            result = self.assess(identifier, scene, turn, day=day)
            self.assertEqual(result["mission"]["completed_steps"], day + 1)
        view = self.store.mission_show(identifier, at=BASE_TIME + timedelta(days=3))
        self.assertEqual(view["status"], "completed")
        self.assertIsNone(view["current_step"])
        self.assertEqual(view["next_action"], "mission_complete")
        self.assertIn("not a proficiency", view["completion_basis"])
        self.assertEqual(self.store.mistakes_path.read_bytes(), before)
        self.assertEqual(self.store.show(mistake["id"])["review_step"], 0)
        with self.assertRaisesRegex(dna.DeutschLoopError, "not active"):
            self.store.mission_start(identifier, at=BASE_TIME + timedelta(days=3))

    def test_hint_is_detected_from_partner_turns_even_if_assessment_claims_no_help(self):
        identifier = self.mission()
        scene, turn = self.attempt(identifier, support="hint")
        with self.assertRaisesRegex(dna.DeutschLoopError, "supported scene"):
            self.assess(identifier, scene, turn)
        result = self.assess(identifier, scene, turn, result="practice")
        self.assertEqual(result["mission"]["completed_steps"], 0)
        self.assertEqual(result["mission"]["last_attempt"]["support"], "hint")
        next_scene = self.store.mission_start(identifier, at=BASE_TIME + timedelta(days=1))
        self.assertEqual(next_scene["contract"]["adaptation"]["mode"], "repair")
        self.assertEqual(next_scene["contract"]["adaptation"]["previous_evidence"][0]["text"], turn["text"])
        self.assertNotEqual(next_scene["contract"]["opening"], scene["contract"]["opening"])
        self.assertEqual(next_scene["contract"]["mission_step"]["id"], "introduction")

    def test_shown_answer_cannot_become_unaided_through_a_claimed_hint(self):
        identifier = self.mission()
        scene, turn = self.attempt(identifier, support="shown")
        result = self.assess(identifier, scene, turn, result="practice", support="hint")
        self.assertEqual(result["mission"]["last_attempt"]["support"], "shown")

    def test_next_step_receives_previous_errors_before_other_due_patterns(self):
        other, _, _ = self.record_example(at=BASE_TIME - timedelta(days=10))
        identifier = self.mission()
        scene, turn = self.attempt(identifier, text="Ich warte für meinen Kollegen und bespreche dann das Projekt.")
        error, _, _ = self.store.record(original=turn["text"], corrected="Ich warte auf meinen Kollegen und bespreche dann das Projekt.",
                                       category="preposition", pattern="warten auf + accusative", rule="warten takes auf + accusative",
                                       session_id=scene["session"]["id"], turn_id=turn["id"])
        self.assess(identifier, scene, turn)
        self.store = dna.StateStore(self.home)
        next_scene = self.store.mission_start(identifier, at=BASE_TIME + timedelta(minutes=10))
        contract = next_scene["contract"]
        self.assertEqual(contract["mission_step"]["id"], "difficult_questions")
        self.assertEqual(contract["adaptation"]["mode"], "challenge")
        self.assertEqual(contract["focus_patterns"][0]["id"], error["id"])
        self.assertIn(other["id"], [row["id"] for row in contract["focus_patterns"]])
        self.assertEqual(contract["personal_goal"], "Cuma Almanca iş görüşmem var.")

    def test_an_unfinished_scene_resumes_and_a_finished_one_requires_assessment(self):
        identifier = self.mission()
        scene = self.store.mission_start(identifier, at=BASE_TIME)
        self.assertEqual(self.store.recap(at=BASE_TIME)["active_roleplay"]["mission_id"], identifier)
        duplicate = self.store.mission_start(identifier, at=BASE_TIME + timedelta(minutes=1))
        self.assertEqual(duplicate["session"]["id"], scene["session"]["id"])
        self.assertEqual(duplicate["next_action"], "resume_scene")
        self.store.roleplay_stop(scene["session"]["id"], at=BASE_TIME + timedelta(minutes=2))
        self.assertEqual(self.store.mission_start(identifier, at=BASE_TIME + timedelta(minutes=3))["next_action"], "present_debrief")
        self.store.roleplay_finish(scene["session"]["id"], at=BASE_TIME + timedelta(minutes=4))
        resumed = self.store.mission_start(identifier, at=BASE_TIME + timedelta(minutes=5))
        self.assertEqual(resumed["next_action"], "assess_mission")
        self.assertEqual(len(self.store._session_document()["sessions"]), 1)

    def test_assessment_needs_a_completed_scene_and_real_learner_evidence(self):
        identifier = self.mission()
        scene, turn = self.attempt(identifier)
        args = dict(session_id=scene["session"]["id"], result="achieved", support="none", evidence_turn_ids=[turn["id"]], note="Concrete answer.", at=BASE_TIME + timedelta(minutes=5))
        with self.assertRaisesRegex(dna.DeutschLoopError, "completed scene"):
            self.store.mission_assess(identifier, **args)
        self.store.roleplay_finish(scene["session"]["id"], at=BASE_TIME + timedelta(minutes=4))
        partner = self.store.roleplay_show(scene["session"]["id"])["session"]["utterances"][0]["id"]
        for ids in ([], ["invented"], [partner]):
            with self.assertRaises(dna.DeutschLoopError):
                self.store.mission_assess(identifier, **{**args, "evidence_turn_ids": ids})
        another = self.mission(goal="Prepare for a presentation.", scenario="presentation")
        with self.assertRaisesRegex(dna.DeutschLoopError, "belonging"):
            self.store.mission_assess(another, **args)
        self.assertEqual(self.store.mission_show(identifier)["completed_steps"], 0)

    def test_assessment_retry_does_not_advance_twice_and_a_changed_judgment_needs_undo(self):
        identifier = self.mission()
        scene, turn = self.attempt(identifier)
        self.assess(identifier, scene, turn)
        retry = self.assess(identifier, scene, turn)
        self.assertEqual(retry["status"], "duplicate")
        self.assertEqual(retry["mission"]["completed_steps"], 1)
        with self.assertRaisesRegex(dna.DeutschLoopError, "already assessed differently"):
            self.assess(identifier, scene, turn, result="practice")
        undone = self.store.mission_undo(identifier, at=BASE_TIME + timedelta(minutes=6))
        self.assertEqual(undone["mission"]["completed_steps"], 0)
        self.assertEqual(undone["mission"]["next_action"], "assess_mission")

    def test_undo_after_a_new_scene_started_cannot_reassign_that_scene_to_an_old_step(self):
        identifier = self.mission()
        scene, turn = self.attempt(identifier)
        self.assess(identifier, scene, turn)
        self.store.mission_start(identifier, at=BASE_TIME + timedelta(days=1))
        with self.assertRaisesRegex(dna.DeutschLoopError, "newer pending"):
            self.store.mission_undo(identifier, at=BASE_TIME + timedelta(days=1, minutes=1))

    def test_new_goal_and_deadline_can_be_saved_and_expiry_does_not_fake_completion(self):
        identifier = self.mission()
        updated = self.store.mission_update(identifier, goal="Interview for a backend role.", deadline="2026-09-12", at=BASE_TIME)
        self.assertEqual(updated["mission"]["deadline"], "2026-09-12")
        expired = self.store.mission_show(identifier, at=BASE_TIME + timedelta(days=3))
        self.assertTrue(expired["overdue"])
        self.assertEqual(expired["status"], "active")
        self.assertEqual(expired["completed_steps"], 0)
        self.store.mission_update(identifier, deadline="", at=BASE_TIME + timedelta(days=3))
        self.assertIsNone(self.store.mission_show(identifier)["deadline"])
        self.store.mission_update(identifier, cancel=True, at=BASE_TIME + timedelta(days=3))
        self.assertEqual(self.store.mission_list(), [])
        self.assertEqual(self.store.mission_list(status="all")[0]["status"], "cancelled")

    def test_backdated_start_or_assessment_is_rejected(self):
        identifier = self.mission()
        with self.assertRaisesRegex(dna.DeutschLoopError, "precede"):
            self.store.mission_start(identifier, at=BASE_TIME - timedelta(days=1))
        scene, turn = self.attempt(identifier)
        self.store.roleplay_finish(scene["session"]["id"], at=BASE_TIME + timedelta(minutes=4))
        with self.assertRaisesRegex(dna.DeutschLoopError, "precede"):
            self.store.mission_assess(identifier, session_id=scene["session"]["id"], result="achieved", support="none",
                                     evidence_turn_ids=[turn["id"]], note="An actual answer.", at=BASE_TIME)

    def test_dashboard_includes_goals_and_catalog_without_changing_learner_data(self):
        identifier = self.mission()
        scene, turn = self.attempt(identifier)
        self.assess(identifier, scene, turn)
        before = {p.name: p.read_bytes() for p in self.home.glob("*.json")}
        snapshot = dna.dashboard_snapshot(self.store, at=BASE_TIME + timedelta(minutes=6))
        self.assertEqual(snapshot["missions"][0]["completed_steps"], 1)
        self.assertEqual(snapshot["missions"][0]["last_attempt"]["evidence"][0]["text"], turn["text"])
        self.assertEqual(len(snapshot["scenarios"]), 15)
        self.assertEqual({p.name: p.read_bytes() for p in self.home.glob("*.json")}, before)


class MissionCliTests(CliTestCase):
    def test_catalog_is_available_without_initializing_learner_state(self):
        arguments = dna.build_parser().parse_args(["--home", str(self.home / "missing"), "scenarios"])
        result = dna.run(arguments)
        self.assertEqual(result["count"], 15)
        self.assertFalse((self.home / "missing").exists())
        codes = {entry["id"] for entry in result["scenarios"]}
        self.assertTrue({"bewerbung", "bahnhof", "apotheke", "telefon", "behoerde", "hotel"}.issubset(codes))

    def test_cli_plan_start_turn_finish_and_assess_roundtrip(self):
        created = json.loads(self.cli("mission-create", "--goal", "Cuma iş görüşmem var.", "--scenario", "interview", "--deadline", "cuma", "--at", dna.iso(BASE_TIME)))
        identifier = created["mission"]["id"]
        scene = json.loads(self.cli("mission-start", identifier, "--at", dna.iso(BASE_TIME)))
        sid = scene["session"]["id"]
        turn = json.loads(self.cli("roleplay-turn", sid, "--speaker", "learner", "--text", "Ich habe drei Jahre Erfahrung und möchte Ihr Team unterstützen.", "--at", dna.iso(BASE_TIME + timedelta(minutes=1))))
        self.cli("roleplay-stop", sid, "--at", dna.iso(BASE_TIME + timedelta(minutes=2)))
        self.cli("roleplay-finish", sid, "--at", dna.iso(BASE_TIME + timedelta(minutes=3)))
        result = json.loads(self.cli("mission-assess", identifier, "--session-id", sid, "--result", "achieved", "--support", "none", "--evidence-turn-id", turn["utterance"]["id"], "--note", "Introduced experience and motivation.", "--at", dna.iso(BASE_TIME + timedelta(minutes=4))))
        self.assertEqual(result["mission"]["current_step"]["id"], "difficult_questions")
        self.assertEqual(json.loads(self.cli("mission-list"))["count"], 1)

    def test_every_new_scenario_and_english_alias_can_start_a_roleplay(self):
        for alias, canonical in dna.SCENARIO_ALIASES.items():
            with self.subTest(alias=alias):
                result = json.loads(self.cli("speak", alias, "--at", dna.iso(BASE_TIME)))
                self.assertEqual(result["session"]["scenario"], canonical)
                self.assertTrue(result["contract"]["opening"])

    def test_isolated_eval_install_carries_the_catalog_and_dashboard_runtime(self):
        sys.path.insert(0, str(ROOT / "evals"))
        from first_session import install_skill
        target = self.home / "installed"
        install_skill(ROOT, target)
        result = subprocess.run([sys.executable, str(target / "scripts" / "deutsch_loop.py"), "--home", str(self.home / "memory"), "scenarios"], capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["count"], 15)
        exported = subprocess.run([sys.executable, str(target / "scripts" / "deutsch_loop.py"), "--home", str(self.home / "memory"), "dashboard", "--output", str(self.home / "copied.html")], capture_output=True, encoding="utf-8")
        self.assertEqual(exported.returncode, 0, exported.stderr)
        self.assertTrue((target / "docs" / "dashboard.md").is_file())


class MissionDemoTests(StoreTestCase):
    def test_demo_captures_a_hinted_retry_then_progress_without_future_evidence(self):
        from demo_missions import mission_demo_payload
        payload = mission_demo_payload(self.home)
        self.assertEqual(payload["experience"], "missions")
        views = [frame["missions"][0] for frame in payload["frames"]]
        self.assertEqual([view["completed_steps"] for view in views], [0, 0, 2, 3])
        self.assertEqual([frame["counts"]["milestones"] for frame in payload["frames"]], [0, 0, 1, 1])
        proof = next(row for row in payload["frames"][2]["patterns"] if row["category"] == "case")["coaching"]["learning_proof"]
        self.assertEqual(proof["independent"]["source"], "spontaneous")
        self.assertIn("Mit meinen Kolleginnen", proof["independent"]["answer"])
        self.assertIsNone(views[0]["last_attempt"])
        self.assertEqual(views[1]["last_attempt"]["support"], "hint")
        self.assertEqual(views[2]["current_step"]["id"], "followup")
        self.assertEqual(views[-1]["status"], "completed")
        for frame in payload["frames"]:
            for pattern in frame["patterns"]:
                for event in pattern["events"]:
                    self.assertLessEqual(dna.parse_moment(event["at"]), dna.parse_moment(frame["as_of"]))
            attempt = frame["missions"][0]["last_attempt"]
            if attempt:
                self.assertLessEqual(dna.parse_moment(attempt["at"]), dna.parse_moment(frame["as_of"]))

    def test_focus_references_follow_rename_and_forget_in_mission_scenes(self):
        first, _, _ = self.record_example(at=BASE_TIME - timedelta(days=1))
        goal = self.store.mission_create(goal="Prepare for an interview.", scenario="interview", at=BASE_TIME)["mission"]["id"]
        scene = self.store.mission_start(goal, at=BASE_TIME)["session"]
        renamed = self.store.rename(first["id"], pattern="bei + dative", label="bei + Dativ")
        row = self.store.roleplay_show(scene["id"])["session"]
        self.assertEqual(row["mission_focus_ids"], [renamed["mistake"]["id"]])
        self.store.forget(renamed["mistake"]["id"])
        self.assertEqual(self.store.roleplay_show(scene["id"])["session"]["mission_focus_ids"], [])
