#!/usr/bin/env python3
"""Capture real Claude Code replies to scripted learner messages for the README.

Uses the existing Claude Code login, a project-local copy of the skill, and an
isolated state directory. No API key or global permission changes are needed.
Raw host logs stay in ignored demo-home/; the exported JSON contains only the
demo conversation and selected learning evidence. This makes real model calls.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from first_session import ClaudeHost, TutorTurn, dna, fingerprint, parse_jsonl  # noqa: E402


MESSAGES = (
    (1, "Use /deutsch-loop-demo. Please explain in English and keep replies brief. "
        "I'd like to practise my German: Ich spreche mit mein Chef."),
    (1, "Ich spreche mit meinem Chef."),
    (2, "Use /deutsch-loop-demo. Please explain in English and keep replies brief. "
        "Heute habe ich mit unseren Kunden gesprochen. "
        "How does that compare with what I practised earlier?"),
)


def write_transcript(path: Path, recording: dict) -> None:
    lines = ["# An actual DeutschLoop conversation", "", "[Back to the README](../README.md)", "",
             recording["disclosure"], "",
             "The tutor replies below are reproduced in full. The GIF uses checked excerpts with "
             "emphasis formatting removed and waiting time compressed. It is a transcript replay.", "",
             f"Host: {recording['host']} · Model: {', '.join(recording['models'])} · "
             f"Captured: {recording['recorded_at']}", "",
             f"[Captured replies and engine evidence]({path.with_suffix('.json').name})", ""]
    for index, exchange in enumerate(recording["exchanges"], 1):
        lines += [f"## Chat {exchange['session']} · exchange {index}", "", "### Scripted learner", "",
                  "```text", exchange["learner"], "```", "", "### Tutor", "", exchange["tutor"], ""]
    evidence = recording["evidence"]
    lines += ["## Saved learning evidence", "", "```text",
              f"Original: {evidence['first_example']['original']}",
              f"Repair: {evidence['first_example']['corrected']}",
              f"Hint: {evidence['coaching_history'][0]['hint']}",
              f"New use: {evidence['correct_use_history'][-1]['context']}", "```", "",
              "This demonstrates memory across separate chats. Same-day success does not establish "
              "next-day retention or overall German proficiency.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "demo" / "conversation.json")
    parser.add_argument("--resume-run", type=Path, help="Resume an interrupted folder under demo-home/")
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error("output already exists; choose a new path to preserve the previous recording")

    work = arguments.resume_run or ROOT / "demo-home" / f"conversation-{uuid.uuid4().hex[:8]}"
    work = work.resolve()
    if not work.is_relative_to((ROOT / "demo-home").resolve()):
        parser.error("the recording folder must be inside this repository's demo-home/")
    project, state, logs = work / "project", work / "state", work / "logs"
    skill = project / ".claude" / "skills" / "deutsch-loop-demo"
    for directory in (skill, state, logs):
        directory.mkdir(parents=True, exist_ok=True)
    for directory in ("scripts", "references", "agents"):
        if not (skill / directory).exists():
            shutil.copytree(ROOT / directory, skill / directory,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    instructions = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    (skill / "SKILL.md").write_text(
        instructions.replace("name: deutsch-loop\n", "name: deutsch-loop-demo\n", 1), encoding="utf-8")
    settings = work / "settings.json"
    settings.write_text(json.dumps({"permissions": {"allow": [
        f"{tool}({program} *deutsch_loop.py*)"
        for tool in ("Bash", "PowerShell") for program in ("python", "python3", "py")
    ]}}), encoding="utf-8")
    env = {**os.environ, "DEUTSCHLOOP_HOME": str(state), "PYTHONIOENCODING": "utf-8"}
    real_home = dna.standard_home()
    before = fingerprint(real_home)
    exchanges, models = [], set()
    host, current_session = None, None
    try:
        for index, (session, message) in enumerate(MESSAGES):
            if session != current_session:
                host = ClaudeHost(project=project, env=env, model=None, effort=None,
                                  settings=settings, logs=logs)
                current_session = session
            print(f"Recording session {session}, message {index + 1}...", flush=True)
            log_path = logs / f"claude-turn-{index}.jsonl"
            if log_path.exists():
                events = parse_jsonl(log_path.read_text(encoding="utf-8"))
                result = next(event for event in events if event.get("type") == "result")
                if result.get("is_error") or result.get("permission_denials"):
                    raise RuntimeError("The saved host turn failed; inspect its raw log")
                blocks = [block for event in events if event.get("type") == "assistant"
                          for block in event["message"].get("content", [])]
                host.session_id = result.get("session_id")
                reply = TutorTurn("\n\n".join(block["text"].strip() for block in blocks
                                             if block.get("type") == "text"),
                                  [host._call(block) for block in blocks if block.get("type") == "tool_use"],
                                  result.get("duration_ms", 0) / 1000)
            else:
                reply = host.send(message, index)
            if reply.error or not reply.text:
                raise RuntimeError(reply.error or "The host returned no tutor text")
            if any(call.denied for call in reply.calls):
                raise RuntimeError("A helper call was denied; inspect the local raw log")
            for line in (logs / f"claude-turn-{index}.jsonl").read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                model = (event.get("message") or {}).get("model")
                if model:
                    models.add(model)
            exchanges.append({"session": session, "learner": message, "tutor": reply.text,
                              "seconds": round(reply.seconds, 1),
                              "helper_calls": sum(call.is_cli for call in reply.calls)})
            print(reply.text, flush=True)
    finally:
        if fingerprint(real_home) != before:
            raise RuntimeError("The real learner state changed during capture; do not publish this run")

    mistakes = json.loads((state / "mistakes.json").read_text(encoding="utf-8"))["mistakes"]
    pattern = next(item for item in mistakes if item.get("first_example", {}).get("original")
                   == "Ich spreche mit mein Chef.")
    if not any(item.get("outcome") == "assisted" and item.get("hint")
               for item in pattern.get("coaching_history", [])):
        raise RuntimeError("No saved self-repair with a hint; inspect the recording before publishing")
    if not any("unseren Kunden" in item.get("context", "")
               for item in pattern.get("correct_use_history", [])):
        raise RuntimeError("The fresh chat did not record the new correct use")
    public = {
        "host": "Claude Code", "models": sorted(models),
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "disclosure": "Scripted learner messages; actual, unedited tutor replies from two separate "
                      "Claude Code chats sharing an isolated DeutschLoop state directory. "
                      "Both chats were recorded on the same day. No simulated time jump.",
        "exchanges": exchanges,
        "evidence": {key: pattern.get(key) for key in
                     ("pattern", "first_example", "coaching_history", "correct_use_history")},
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_transcript(arguments.output.with_suffix(".md"), public)
    print(f"Saved public conversation: {arguments.output}")
    print(f"Raw local logs: {logs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
