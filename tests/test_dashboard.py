from __future__ import annotations

import json
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

from test_agent_contract import CliTestCase
from test_deutsch_loop import BASE_TIME, CASE_REVIEWS, StoreTestCase, dna
from render_dashboard_demo import demo_payload


class EmbeddedData(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.inside_data = False
        self.data = ""
        self.scripts = 0

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.scripts += 1
            self.inside_data = dict(attrs).get("id") == "dna-data"

    def handle_data(self, value):
        if self.inside_data:
            self.data += value

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside_data = False


def embedded_data(html):
    parser = EmbeddedData()
    parser.feed(html)
    return json.loads(parser.data), parser.scripts


class DashboardTests(CliTestCase):
    def saved_files(self):
        return {path.name: path.read_bytes() for path in self.home.glob("*.json")}

    def payload(self, output):
        return embedded_data(output.read_text(encoding="utf-8"))[0]

    def test_export_preserves_every_saved_record_and_profile_display_marker(self):
        first, _, _ = self.record_example()
        self.store.coach(first["id"], outcome="assisted", prompt="Schau noch einmal auf mit mein Chef.",
                         answer="Ich spreche mit meinem Chef.", strategy="Kasusfrage", hint="Mit wem?",
                         at=BASE_TIME + timedelta(minutes=2))
        self.grade_example(first["id"], result="pass", at=BASE_TIME + timedelta(days=1))
        before = self.saved_files()
        output = self.home / "progress.html"
        result = json.loads(self.cli("dashboard", "--output", str(output), "--at", dna.iso(BASE_TIME + timedelta(days=1))))
        self.assertEqual(result["status"], "exported")
        self.assertEqual(self.saved_files(), before)
        payload = self.payload(output)
        self.assertFalse(payload["demo"])
        self.assertEqual(payload["frames"][0]["counts"], {"patterns": 1, "due": 0, "mastered": 0, "milestones": 1})
        row = payload["frames"][0]["patterns"][0]
        self.assertEqual(row["first_example"]["original"], "Ich spreche mit mein Chef.")
        self.assertEqual(row["coaching"]["learning_proof"]["independent"]["source"], "review")
        self.assertNotIn("undo", row)
        self.assertNotIn("seen_answers", row)
        self.assertNotIn("seen_prompts", row)

    def test_an_empty_export_does_not_initialize_learner_memory(self):
        missing = self.home / "not-created"
        output = self.home / "empty.html"
        arguments = dna.build_parser().parse_args(["--home", str(missing), "dashboard", "--output", str(output)])
        dna.run(arguments)
        self.assertFalse(missing.exists())
        self.assertEqual(self.payload(output)["frames"][0]["patterns"], [])
        self.assertEqual(self.payload(output)["frames"][0]["counts"]["milestones"], 0)

    def test_legacy_examples_are_projected_without_creating_other_state_files(self):
        first, _, _ = self.record_example()
        document = json.loads(self.store.mistakes_path.read_text(encoding="utf-8"))
        document["schema_version"] = 1
        document["mistakes"][0].pop("first_example")
        document["mistakes"][0]["first_seen"] = dna.iso(BASE_TIME - timedelta(days=10))
        self.store.mistakes_path.write_text(json.dumps(document), encoding="utf-8")
        self.store.sessions_path.unlink()
        self.store.vocabulary_path.unlink()
        before = self.saved_files()
        snapshot = dna.dashboard_snapshot(self.store, at=BASE_TIME)
        self.assertEqual(self.saved_files(), before)
        row = snapshot["patterns"][0]
        self.assertEqual(row["first_example"]["original"], first["examples"][0]["original"])
        self.assertFalse(row["first_example_is_original"])

    def test_a_later_mistake_keeps_historical_proof_but_marks_the_return(self):
        first, _, _ = self.record_example()
        self.store.coach(first["id"], outcome="assisted", prompt="Prüfe mit mein Chef.",
                         answer="Ich spreche mit meinem Chef.", strategy="Kasusfrage", hint="Mit wem?",
                         at=BASE_TIME + timedelta(minutes=2))
        self.grade_example(first["id"], result="pass", at=BASE_TIME + timedelta(days=1))
        self.record_example(at=BASE_TIME + timedelta(days=9), original="Ich fahre mit mein Auto.",
                            corrected="Ich fahre mit meinem Auto.")
        row = dna.dashboard_snapshot(self.store, at=BASE_TIME + timedelta(days=10))["patterns"][0]
        self.assertTrue(row["proof_has_later_error"])
        self.assertIsNotNone(row["coaching"]["learning_proof"])
        self.assertEqual(row["review_step"], 0)
        self.assertTrue(row["due"])

    def test_hint_same_day_practice_and_spontaneous_use_keep_their_distinct_sources(self):
        first, _, _ = self.record_example()
        self.store.coach(first["id"], outcome="assisted", prompt="Prüfe mit mein Chef.",
                         answer="Ich spreche mit meinem Chef.", strategy="Kasusfrage", hint="Mit wem?",
                         at=BASE_TIME + timedelta(minutes=2))
        self.store.coach(first["id"], outcome="independent", prompt=CASE_REVIEWS[0][0], answer=CASE_REVIEWS[0][1],
                         at=BASE_TIME + timedelta(minutes=5))
        first_view = dna.dashboard_snapshot(self.store, at=BASE_TIME + timedelta(minutes=10))
        self.assertEqual(first_view["counts"]["milestones"], 0)
        self.store.observe([first["id"]], context="Ich telefoniere mit meiner Mutter.", at=BASE_TIME + timedelta(days=1))
        row = dna.dashboard_snapshot(self.store, at=BASE_TIME + timedelta(days=1))["patterns"][0]
        self.assertEqual(row["coaching"]["learning_proof"]["independent"]["source"], "spontaneous")
        kinds = [event["kind"] for event in row["events"]]
        self.assertEqual(kinds.count("spontaneous"), 1)
        self.assertEqual(kinds.count("practice"), 1)
        self.assertEqual(kinds.count("assisted"), 1)
        self.assertEqual(kinds.count("review"), 0, "Observations must not appear twice as passed reviews")

    def test_local_dates_keep_the_engine_offset(self):
        self.record_example()
        with mock.patch.dict("os.environ", {"DEUTSCHLOOP_UTC_OFFSET": "+03:00"}):
            view = dna.dashboard_snapshot(self.store, at=BASE_TIME)
        self.assertEqual(view["as_of_local"], "2026-09-10T15:00:00+03:00")
        self.assertEqual(view["patterns"][0]["events"][0]["at_local"], "2026-09-10T15:00:00+03:00")

    def test_exported_text_cannot_close_the_embedded_data_script(self):
        hostile = '</script><script>alert("learner text")</script><img src=x onerror=alert(1)> & ä\u2028'
        self.record_example(original=hostile, corrected="Ein gültiger Satz.")
        self.store.init_profile(name=hostile)
        snapshot = dna.dashboard_snapshot(self.store, at=BASE_TIME)
        original_payload = {"version": 1, "demo": False, "frames": [snapshot]}
        html = dna.render_dashboard(original_payload)
        actual, scripts = embedded_data(html)
        self.assertEqual(actual, original_payload)
        self.assertEqual(scripts, 2)
        self.assertNotIn(hostile, html)

    def test_output_needs_an_html_path_and_explicit_overwrite(self):
        output = self.home / "keep.html"
        output.write_text("existing content", encoding="utf-8")
        self.assertIn("already exists", self.cli_error("dashboard", "--output", str(output)))
        self.assertEqual(output.read_text(encoding="utf-8"), "existing content")
        self.cli("dashboard", "--output", str(output), "--force")
        self.assertEqual(self.payload(output)["version"], 1)
        self.assertIn(".html", self.cli_error("dashboard", "--output", str(self.store.profile_path), "--force"))
        template = Path(dna.__file__).with_name("dashboard.html")
        self.assertIn("source template", self.cli_error("dashboard", "--output", str(template), "--force"))


class DemoDashboardTests(StoreTestCase):
    def test_chapters_are_real_snapshots_without_future_evidence(self):
        payload = demo_payload(self.home)
        frames = payload["frames"]
        self.assertTrue(payload["demo"])
        self.assertEqual(len(frames), 4)
        self.assertEqual([frame["counts"]["milestones"] for frame in frames], [0, 2, 3, 3])
        self.assertEqual([frame["counts"]["mastered"] for frame in frames], [1, 1, 1, 1])
        mit_id = dna.mistake_id("case", "mit + dative")
        patterns = [next(row for row in frame["patterns"] if row["id"] == mit_id) for frame in frames]
        self.assertEqual([row["review_step"] for row in patterns], [0, 1, 2, 0])
        self.assertIsNone(patterns[0]["coaching"]["learning_proof"])
        self.assertTrue(patterns[-1]["proof_has_later_error"])
        for frame in frames:
            for row in frame["patterns"]:
                for event in row["events"]:
                    self.assertLessEqual(dna.parse_moment(event["at"]), dna.parse_moment(frame["as_of"]))

    def test_the_demo_refuses_to_seed_an_existing_learner_directory(self):
        self.record_example()
        before = self.store.mistakes_path.read_bytes()
        with self.assertRaisesRegex(dna.DeutschLoopError, "empty, isolated"):
            demo_payload(self.home)
        self.assertEqual(self.store.mistakes_path.read_bytes(), before)
