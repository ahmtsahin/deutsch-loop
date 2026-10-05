#!/usr/bin/env python3
"""Capture how a session opens for a returning learner, in a real Claude Code chat.

The four-month demo learner from scripts/demo.py is seeded into an isolated state
directory, so the board and the quoted sentence come from the engine. The tutor's
replies are real and unedited. The learner's answer to the opening task is scripted
after reading that task, and is passed with --answer in a second run.
This makes real model calls with the existing Claude Code login.

    python evals/record_session.py
    python evals/record_session.py --resume-run demo-home/session-XXXXXXXX --answer "..." --output demo/session.json
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
sys.path.insert(0, str(ROOT / "scripts"))
import demo  # noqa: E402
import deutsch_loop as dna  # noqa: E402
from first_session import ClaudeHost, TutorTurn, fingerprint, parse_jsonl  # noqa: E402

SKILL_NAME = "deutsch-loop-demo"
DISCLOSURE = ("Scripted four-month learner history, seeded through the engine; actual, unedited tutor "
              "replies from one Claude Code chat with an isolated DeutschLoop state directory. "
              "The learner's answer was scripted after reading the tutor's task.")


def saved_turn(host: ClaudeHost, log_path: Path) -> TutorTurn:
    """Read a completed turn from its raw log instead of asking the host again."""
    events = parse_jsonl(log_path.read_text(encoding="utf-8"))
    result = next(event for event in events if event.get("type") == "result")
    if result.get("is_error") or result.get("permission_denials"):
        raise RuntimeError("The saved host turn failed; inspect its raw log")
    blocks = [block for event in events if event.get("type") == "assistant"
              for block in event["message"].get("content", [])]
    host.session_id = result.get("session_id")
    return TutorTurn("\n\n".join(block["text"].strip() for block in blocks
                                 if block.get("type") == "text" and block["text"].strip()),
                     [host._call(block) for block in blocks if block.get("type") == "tool_use"],
                     result.get("duration_ms", 0) / 1000)


def models_in(log_path: Path) -> set[str]:
    models = set()
    for event in parse_jsonl(log_path.read_text(encoding="utf-8")):
        model = (event.get("message") or {}).get("model")
        if model and not model.startswith("<"):
            models.add(model)
    return models


def write_transcript(path: Path, recording: dict) -> None:
    lines = ["# A returning learner opens a new chat", "", "[Back to the README](../README.md)", "",
             recording["disclosure"], "",
             f"The chat starts with `/{SKILL_NAME}`, a copy of the skill under another name, so that an "
             "installed `deutsch-loop` cannot answer in its place.", "",
             f"Host: {recording['host']} · Model: {', '.join(recording['models'])} · "
             f"Captured: {recording['recorded_at']}", "",
             f"[Captured replies and engine evidence]({path.with_suffix('.json').name})", ""]
    for index, exchange in enumerate(recording["exchanges"], 1):
        # Quoted, so that a heading inside a reply stays part of that reply.
        reply = [f"> {line}".rstrip() for line in exchange["tutor"].splitlines()]
        lines += [f"## Exchange {index}", "", "### Learner", "", "```text", exchange["learner"], "```", "",
                  "### Tutor", "", *reply, ""]
    evidence = recording["evidence"]
    lines += ["## Saved evidence", "", "```text",
              f"Pattern: {evidence['label']}",
              f"Quoted sentence: {evidence['quoted']['original']} ({evidence['quoted']['seen_at_local']})"]
    if evidence.get("review"):
        lines += [f"New answer: {evidence['review']['answer']}",
                  f"Review result: {evidence['review']['result']} · "
                  f"step {evidence['step_before']}/6 → {evidence['step_after']}/6"]
    lines += ["```", "",
              "This shows what a session looks like after four months of scripted history. "
              "It is not a claim about how fast anyone learns.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=ROOT / "demo" / "session.json")
    parser.add_argument("--resume-run", type=Path, help="Continue a recording folder under demo-home/")
    parser.add_argument("--answer", help="The learner's answer to the opening task; needs --resume-run")
    parser.add_argument("--explanation-language", default="en", help="Support language of the demo learner")
    parser.add_argument("--model", help="Host model; defaults to the Claude Code setting")
    arguments = parser.parse_args()
    if arguments.answer and not arguments.resume_run:
        parser.error("--answer continues a recorded opening; pass its folder with --resume-run")
    if arguments.answer and arguments.output.exists():
        parser.error("output already exists; choose a new path to preserve the previous recording")

    work = (arguments.resume_run or ROOT / "demo-home" / f"session-{uuid.uuid4().hex[:8]}").resolve()
    if not work.is_relative_to((ROOT / "demo-home").resolve()):
        parser.error("the recording folder must be inside this repository's demo-home/")
    project, state, logs = work / "project", work / "state", work / "logs"
    skill = project / ".claude" / "skills" / SKILL_NAME
    fresh = not state.exists()
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

    store = dna.StateStore(state)
    if fresh:
        demo.seed(state)
        store.init_profile(explanation_language=arguments.explanation_language)
        target = store.recap()["callback"]
        (work / "callback.json").write_text(json.dumps(target, ensure_ascii=False, indent=2), encoding="utf-8")
        (work / "card.txt").write_text(dna.render_recap_card(store.recap()), encoding="utf-8")
    target = json.loads((work / "callback.json").read_text(encoding="utf-8"))
    card = (work / "card.txt").read_text(encoding="utf-8")

    env = {**os.environ, "DEUTSCHLOOP_HOME": str(state), "PYTHONIOENCODING": "utf-8"}
    real_home = dna.standard_home()
    before = fingerprint(real_home)
    host = ClaudeHost(project=project, env=env, model=arguments.model, effort=None, settings=settings, logs=logs)
    messages = [f"/{SKILL_NAME}"] + ([arguments.answer] if arguments.answer else [])
    exchanges, models = [], set()
    try:
        for index, message in enumerate(messages):
            log_path = logs / f"claude-turn-{index}.jsonl"
            if log_path.exists():
                reply = saved_turn(host, log_path)
            else:
                print(f"Recording message {index + 1}...", flush=True)
                reply = host.send(message, index)
            if reply.error or not reply.text:
                raise RuntimeError(reply.error or "The host returned no tutor text")
            if any(call.denied for call in reply.calls):
                raise RuntimeError("A helper call was denied; inspect the local raw log")
            models |= models_in(log_path)
            exchanges.append({"learner": message, "tutor": reply.text, "seconds": round(reply.seconds, 1),
                              "helper_calls": sum(call.is_cli for call in reply.calls)})
            print(reply.text, flush=True)
    finally:
        if fingerprint(real_home) != before:
            raise RuntimeError("The real learner state changed during capture; do not publish this run")

    if not arguments.answer:
        print(f"\nOpening recorded. Read the task, then continue with:\n"
              f"  python evals/record_session.py --resume-run {work} --answer \"...\" --output {arguments.output}")
        return 0

    after = store.show(target["id"])
    answered = dna.text_fingerprint(arguments.answer)
    review = next((item for item in reversed(after.get("review_history", []))
                   if dna.text_fingerprint(item.get("answer") or "") == answered), None)
    if card.splitlines()[0] not in exchanges[0]["tutor"]:
        raise RuntimeError("The opening reply does not show the engine's board; inspect the recording")
    if target["last_example"]["original"] not in exchanges[0]["tutor"]:
        raise RuntimeError("The opening reply does not quote the learner's stored sentence")
    if review is None:
        raise RuntimeError("The answer was not saved as a review of the quoted pattern; inspect the recording")
    public = {
        "host": "Claude Code", "models": sorted(models),
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "disclosure": DISCLOSURE,
        "card": card,
        "exchanges": exchanges,
        "evidence": {"label": target["label"], "quoted": target["last_example"],
                     "step_before": target["review_step"], "step_after": after["review_step"],
                     "review": {key: review.get(key) for key in ("result", "prompt", "answer")}},
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_transcript(arguments.output.with_suffix(".md"), public)
    print(f"Saved public session: {arguments.output}")
    print(f"Raw local logs: {logs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
