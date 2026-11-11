#!/usr/bin/env python3
"""Capture a practice exam in a real Claude Code chat for the README.

The tutor is the skill itself, in Claude Code, with an isolated state directory:
it writes the tasks, starts the clock, stores the texts, rates them, records the
mistakes, and shows the engine's report. The learner's texts are scripted after
reading the tasks and passed one message at a time. Because the engine's clock is
real, --not-before waits until that many minutes after the exam started before
sending, so the report shows a realistic writing time. This makes real model calls
with the existing Claude Code login.

    python evals/record_exam.py
    python evals/record_exam.py --resume-run demo-home/exam-XXXXXXXX --say-file texts.txt --not-before 46
    python evals/record_exam.py --resume-run demo-home/exam-XXXXXXXX --say "Abgeben"
    python evals/record_exam.py --resume-run demo-home/exam-XXXXXXXX --output demo/exam.json
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "scripts"))
import deutsch_loop as dna  # noqa: E402
from first_session import ClaudeHost, fingerprint  # noqa: E402
from record_session import SKILL_NAME, models_in, saved_turn  # noqa: E402

OPENING = (f"Use /{SKILL_NAME}. Please explain in English and keep replies brief. "
           "I'm preparing for the Goethe-Zertifikat B1. Let's do a full practice exam for Schreiben.")
DISCLOSURE = ("Actual, unedited tutor replies from one Claude Code chat with a fresh, isolated DeutschLoop "
              "state directory. The learner's texts were scripted after reading the tutor's tasks; they were "
              "sent {minutes} minutes after the clock started, so the time in the report is real elapsed time, "
              "not writing time.")


def exam_session(state: Path) -> dict | None:
    path = state / "sessions.json"
    if not path.exists():
        return None
    sessions = json.loads(path.read_text(encoding="utf-8"))["sessions"]
    return next((item for item in reversed(sessions) if item.get("type") == "exam"), None)


def wait_until(started: datetime, minutes: float) -> None:
    target = started.timestamp() + minutes * 60
    while (left := target - time.time()) > 0:
        print(f"Waiting {left / 60:.1f} more minutes before sending...", flush=True)
        time.sleep(min(left, 300))


def write_transcript(path: Path, recording: dict) -> None:
    lines = ["# A practice exam: Goethe-Zertifikat B1, Schreiben", "", "[Back to the README](../README.md)", "",
             recording["disclosure"], "",
             f"The chat starts with `/{SKILL_NAME}`, a copy of the skill under another name, so that an "
             "installed `deutsch-loop` cannot answer in its place.", "",
             f"Host: {recording['host']} · Model: {', '.join(recording['models'])} · "
             f"Captured: {recording['recorded_at']}", "",
             f"[Captured replies and engine evidence]({path.with_suffix('.json').name})", ""]
    for index, exchange in enumerate(recording["exchanges"], 1):
        reply = [f"> {line}".rstrip() for line in exchange["tutor"].splitlines()]
        lines += [f"## Exchange {index}", "", "### Learner", "", "```text", exchange["learner"], "```", "",
                  "### Tutor", "", *reply, ""]
    lines += ["## The engine's report", "", "```text", recording["report"], "```", "",
              "The ratings are one model's practice estimate against the published criteria, not an "
              "official result.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--resume-run", type=Path, help="Continue a recording folder under demo-home/")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--say", help="The learner's next message")
    group.add_argument("--say-file", type=Path, help="The learner's next message, read from a UTF-8 file")
    parser.add_argument("--not-before", type=float, help="Send no earlier than this many minutes after the exam started")
    parser.add_argument("--output", type=Path, help="Export the finished recording, e.g. demo/exam.json")
    parser.add_argument("--model", help="Host model; defaults to the Claude Code setting")
    arguments = parser.parse_args()
    say = arguments.say_file.read_text(encoding="utf-8").strip() if arguments.say_file else arguments.say
    if (say or arguments.output) and not arguments.resume_run:
        parser.error("--say and --output continue a recording; pass its folder with --resume-run")
    if arguments.output and arguments.output.exists():
        parser.error("output already exists; choose a new path to preserve the previous recording")

    work = (arguments.resume_run or ROOT / "demo-home" / f"exam-{uuid.uuid4().hex[:8]}").resolve()
    if not work.is_relative_to((ROOT / "demo-home").resolve()):
        parser.error("the recording folder must be inside this repository's demo-home/")
    project, state, logs = work / "project", work / "state", work / "logs"
    skill = project / ".claude" / "skills" / SKILL_NAME
    for directory in (skill, state, logs):
        directory.mkdir(parents=True, exist_ok=True)
    for directory in ("scripts", "references", "agents"):
        if not (skill / directory).exists():
            shutil.copytree(ROOT / directory, skill / directory,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    instructions = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    (skill / "SKILL.md").write_text(
        instructions.replace("name: deutsch-loop\n", f"name: {SKILL_NAME}\n", 1), encoding="utf-8")
    settings = work / "settings.json"
    settings.write_text(json.dumps({"permissions": {"allow": [
        f"{tool}({program} *deutsch_loop.py*)"
        for tool in ("Bash", "PowerShell") for program in ("python", "python3", "py")
    ]}}), encoding="utf-8")
    messages_path = work / "messages.json"
    messages = json.loads(messages_path.read_text(encoding="utf-8")) if messages_path.exists() else [OPENING]
    if say:
        session = exam_session(state)
        if session is None:
            parser.error("the tutor has not started an exam in this recording")
        if arguments.not_before:
            wait_until(dna.parse_moment(session["started_at"]), arguments.not_before)
        messages.append(say)
    messages_path.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")

    env = {**os.environ, "DEUTSCHLOOP_HOME": str(state), "PYTHONIOENCODING": "utf-8"}
    real_home = dna.standard_home()
    before = fingerprint(real_home)
    host = ClaudeHost(project=project, env=env, model=arguments.model, effort=None, settings=settings, logs=logs)
    exchanges, models = [], set()
    try:
        for index, message in enumerate(messages):
            log_path = logs / f"claude-turn-{index}.jsonl"
            if log_path.exists():
                reply = saved_turn(host, log_path)
            else:
                print(f"Recording message {index + 1}...", flush=True)
                reply = host.send(message, index)
                print(reply.text, flush=True)
            if reply.error or not reply.text:
                raise RuntimeError(reply.error or "The host returned no tutor text")
            if any(call.denied for call in reply.calls):
                raise RuntimeError("A helper call was denied; inspect the local raw log")
            models |= models_in(log_path)
            exchanges.append({"learner": message, "tutor": reply.text, "seconds": round(reply.seconds, 1),
                              "helper_calls": sum(call.is_cli for call in reply.calls)})
    finally:
        if fingerprint(real_home) != before:
            raise RuntimeError("The real learner state changed during capture; do not publish this run")

    session = exam_session(state)
    if not arguments.output:
        status = session.get("status") if session else "not started"
        print(f"\nExam status: {status}. Continue with --resume-run {work} --say ... or export with --output.")
        return 0
    if session is None or session.get("status") != "complete":
        raise RuntimeError("The exam is not finished; nothing to export")
    store = dna.StateStore(state)
    shown = store.exam_show(session["id"])
    card, report = dna.render_exam_card(shown), shown["learner_message"]
    if card.splitlines()[0] not in exchanges[0]["tutor"]:
        raise RuntimeError("The opening reply does not show the engine's exam card; inspect the recording")
    if report not in exchanges[-1]["tutor"]:
        raise RuntimeError("The final reply does not show the engine's report as printed; inspect the recording")
    texts = {item["task"]: item for item in shown["session"]["texts"]}
    sent_after = round(session["duration_seconds"] / 60)
    public = {
        "host": "Claude Code", "models": sorted(models),
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "disclosure": DISCLOSURE.format(minutes=sent_after),
        "exam": session["exam"], "card": card,
        "tasks": [{"number": task["number"], "type": task["type"], "prompt": task["prompt"],
                   "text": texts.get(task["number"], {}).get("text")} for task in shown["session"]["tasks"]],
        "exchanges": exchanges,
        "report": report,
        "result": {key: shown["report"][key] for key in ("points", "max_points", "percent", "duration_seconds",
                                                          "target_seconds", "unaided", "confirmed_patterns")},
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_transcript(arguments.output.with_suffix(".md"), public)
    print(f"Saved public exam: {arguments.output}")
    print(f"Raw local logs: {logs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
