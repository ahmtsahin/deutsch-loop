from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from test_deutsch_loop import BASE_TIME, CASE_REVIEWS, SCRIPT, StoreTestCase, dna


class CliTestCase(StoreTestCase):
    def cli(self, *arguments: str) -> str:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = dna.main(["--home", str(self.home), *arguments])
        self.assertEqual(code, 0, buffer.getvalue())
        return buffer.getvalue()

    def cli_error(self, *arguments: str) -> str:
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            code = dna.main(["--home", str(self.home), *arguments])
        self.assertEqual(code, 2)
        return buffer.getvalue()


class ConcurrencyTests(StoreTestCase):
    def test_parallel_records_keep_every_pattern(self):
        # Agents often record the patterns of one learner sentence as parallel tool calls.
        def record(index: int) -> subprocess.CompletedProcess:
            return subprocess.run(
                [sys.executable, str(SCRIPT), "--home", str(self.home), "record",
                 "--original", f"Ich wohne bei mein Freund {index}.", "--corrected", f"Ich wohne bei meinem Freund {index}.",
                 "--category", "case", "--pattern", f"präposition{index} + dative", "--rule", "Dativ nach der Präposition"],
                capture_output=True,
                check=False,
            )

        with ThreadPoolExecutor(6) as pool:
            results = list(pool.map(record, range(6)))
        self.assertEqual([result.returncode for result in results], [0] * 6, [result.stderr for result in results])
        self.assertEqual(len(self.store.list(status="all")), 6)

    def test_a_held_lock_times_out_with_a_clear_error(self):
        with dna.state_lock(self.home):
            with self.assertRaisesRegex(dna.DeutschLoopError, "busy"):
                with dna.state_lock(self.home, timeout=0.1):
                    pass
        with dna.state_lock(self.home, timeout=0.1):
            pass


class MergeUndoTests(StoreTestCase):
    def mistakes_on_disk(self) -> list[dict]:
        return json.loads((self.home / "mistakes.json").read_text(encoding="utf-8"))["mistakes"]

    def test_a_merge_can_be_undone_exactly(self):
        target, _, _ = self.record_example()
        source, _, _ = self.record_example(
            pattern="bei + dative", rule="bei takes dative", original="Ich wohne bei mein Onkel.",
            corrected="Ich wohne bei meinem Onkel.", at=BASE_TIME + timedelta(hours=1),
        )
        without_undo = lambda items: [{key: value for key, value in item.items() if key != "undo"} for item in items]
        before = without_undo(self.mistakes_on_disk())
        merged = self.store.merge(source["id"], target["id"], at=BASE_TIME + timedelta(hours=2))
        self.assertEqual(merged["occurrences"], 2)
        self.assertEqual(len(self.mistakes_on_disk()), 1)

        outcome = self.store.undo(target["id"])
        self.assertEqual((outcome["status"], outcome["undone"]), ("undone", "merge"))
        self.assertEqual(outcome["restored"]["id"], source["id"])
        self.assertEqual(without_undo(self.mistakes_on_disk()), before)
        again, status, extra = self.record_example(
            pattern="bei + dative", rule="bei takes dative", original="Ich esse bei mein Tante.",
            corrected="Ich esse bei meiner Tante.", at=BASE_TIME + timedelta(days=2),
        )
        self.assertEqual((again["id"], status, extra["resolved_by"]), (source["id"], "updated", "id"))
        with self.assertRaises(dna.DeutschLoopError):
            self.store.undo(target["id"])


class AgentOutputTests(CliTestCase):
    def test_agent_json_is_compact_and_full_records_need_verbose(self):
        mistake, _, _ = self.record_example()
        self.record_example(original="Ich fahre mit mein Auto.", corrected="Ich fahre mit meinem Auto.", at=BASE_TIME + timedelta(days=1))
        printed = self.cli("record", "--mistake-id", mistake["id"], "--original", "Ich tanze mit mein Schwester.",
                           "--corrected", "Ich tanze mit meiner Schwester.", "--at", "2026-09-12T12:00:00Z")
        self.assertEqual(printed.count("\n"), 1, "piped JSON is printed on one line")
        result = json.loads(printed)
        self.assertEqual(result["status"], "updated")
        for field in ("id", "label", "rule", "first_example", "last_example", "coaching", "next_review_local"):
            self.assertIn(field, result["mistake"])
        for field in ("examples", "review_history", "verification_history", "seen_answers"):
            self.assertNotIn(field, result["mistake"])
        self.assertEqual(result["previous"]["first_example"]["original"], "Ich spreche mit mein Chef.")

        rows = json.loads(self.cli("list"))["mistakes"]
        self.assertEqual((rows[0]["label"], rows[0]["label_source"]), ("mit + Dativ", "rule"))
        self.assertNotIn("coaching", rows[0])
        self.assertIn("coaching", json.loads(self.cli("list", "--verbose"))["mistakes"][0])
        due = json.loads(self.cli("due", "--at", "2026-09-20T12:00:00Z"))["mistakes"][0]
        self.assertIn("coaching", due)
        self.assertNotIn("examples", due)
        self.assertIn("examples", json.loads(self.cli("due", "--verbose", "--at", "2026-09-20T12:00:00Z"))["mistakes"][0])

    def test_pretty_json_in_a_terminal(self):
        class Terminal(io.StringIO):
            def isatty(self) -> bool:
                return True

        terminal = Terminal()
        dna._print_json({"b": 1, "a": "ä"}, stream=terminal)
        self.assertEqual(terminal.getvalue(), '{\n  "a": "ä",\n  "b": 1\n}\n')

    def test_recap_names_the_callback_and_patterns_that_need_a_label(self):
        first, _, _ = self.record_example()
        coined, _, _ = self.record_example(
            category="vocabulary", pattern="Termin ausmachen for appointments", rule="einen Termin ausmachen",
            original="Ich mache einen Termin.", corrected="Ich mache einen Termin aus.", at=BASE_TIME + timedelta(hours=2),
        )
        recap = self.store.recap(at=BASE_TIME + timedelta(hours=3))
        self.assertEqual((recap["callback"]["id"], recap["callback"]["reason"]), (coined["id"], "recent"))
        self.assertEqual([row["id"] for row in recap["needs_label"]], [coined["id"]])

        moment = BASE_TIME + timedelta(days=1, minutes=30)
        due = self.store.recap(at=moment)
        self.assertEqual((due["callback"]["id"], due["callback"]["reason"]), (first["id"], "due"))
        self.assertEqual(due["callback"]["last_example"]["original"], "Ich spreche mit mein Chef.")
        self.assertIn("coaching", due["callback"])
        self.assertNotIn("coaching", due["board"][0])
        verbose = self.store.recap(at=moment, verbose=True)
        self.assertIn("coaching", verbose["board"][0])
        self.assertEqual(due["card"], verbose["card"])
        self.assertLess(len(json.dumps(due)), len(json.dumps(verbose)))


class MinimalityTests(CliTestCase):
    RECORD = ("record", "--original", "Ich spreche mit mein Chef.", "--corrected", "Ich spreche mit meinem Chef.",
              "--category", "case", "--pattern", "mit + dative", "--rule", "mit + Dativ")

    def test_record_reports_whether_the_correction_is_minimal(self):
        minimal = json.loads(self.cli(*self.RECORD))
        self.assertEqual(minimal["minimality"]["status"], "minimal")
        self.assertEqual(minimal["minimality"]["changes"][0]["corrected_tokens"], ["meinem"])
        self.assertNotIn("verification", minimal)
        rewrite = json.loads(self.cli(
            "record", "--original", "Ich bin müde.", "--corrected", "Erschöpft sank ich sofort ins Bett.",
            "--category", "vocabulary", "--pattern", "müde sein", "--rule", "müde", "--label", "müde sein",
        ))
        self.assertEqual(rewrite["minimality"]["status"], "possible_rewrite")

    def test_old_validator_fields_are_dropped_from_output_and_then_from_disk(self):
        mistake = json.loads(self.cli(*self.RECORD))["mistake"]
        scene = json.loads(self.cli("speak", "restaurant"))["session"]["id"]
        mistakes_path, sessions_path = self.home / "mistakes.json", self.home / "sessions.json"
        mistakes = json.loads(mistakes_path.read_text(encoding="utf-8"))
        mistakes["mistakes"][0]["verification_history"] = [{"status": "verified", "checked_at": "2026-09-01T10:00:00Z"}]
        mistakes["mistakes"][0]["examples"][0]["verification_status"] = "verified"
        mistakes_path.write_text(json.dumps(mistakes), encoding="utf-8")
        sessions = json.loads(sessions_path.read_text(encoding="utf-8"))
        sessions["sessions"][0]["feedback"] = [{"verification_status": "verified", "mistake_id": mistake["id"],
                                                "event_id": "e_1", "turn_id": "t_1", "original": "x"}]
        sessions_path.write_text(json.dumps(sessions), encoding="utf-8")
        self.assertNotIn("verification", self.cli("show", mistake["id"]))
        self.assertNotIn("verification", self.cli("roleplay-show", scene))
        self.cli("record", "--mistake-id", mistake["id"], "--original", "Ich gehe mit mein Hund.",
                 "--corrected", "Ich gehe mit meinem Hund.")
        self.cli("roleplay-stop", scene)
        self.assertNotIn("verification", mistakes_path.read_text(encoding="utf-8"))
        self.assertNotIn("verification", sessions_path.read_text(encoding="utf-8"))

    def test_there_is_no_validator_command_or_flag(self):
        for arguments in (("verify", "--original", "a", "--corrected", "b"), (*self.RECORD, "--verify")):
            with self.subTest(arguments=arguments[0]), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                dna.main(["--home", str(self.home), *arguments])
        self.assertFalse(hasattr(dna, "verify_correction"))


class VarietyTests(CliTestCase):
    def test_a_review_in_the_same_sentence_frame_is_flagged(self):
        mistake, _, _ = self.record_example()
        same_frame = json.loads(self.cli(
            "grade", mistake["id"], "--result", "pass", "--prompt", "Dein Vater hat Zeit. Mit wem sprichst du?",
            "--answer", "Ich spreche mit meinem Vater.", "--at", "2026-09-11T12:00:00Z",
        ))
        self.assertEqual(same_frame["mistake"]["review_step"], 1)
        self.assertEqual(same_frame["variety"]["field"], "answer")
        self.assertEqual(same_frame["variety"]["similar_to"], "Ich spreche mit meinem Chef.")
        fresh = json.loads(self.cli(
            "grade", mistake["id"], "--result", "pass", "--prompt", CASE_REVIEWS[1][0],
            "--answer", CASE_REVIEWS[1][1], "--at", "2026-09-14T12:00:00Z",
        ))
        self.assertIsNone(fresh["variety"])
