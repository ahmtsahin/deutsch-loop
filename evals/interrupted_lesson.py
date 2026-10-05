#!/usr/bin/env python3
"""Check that an interrupted lesson leaves no trace and cannot turn help into an unaided success.

A scripted learner writes a German sentence with one mistake, and the session ends after the tutor's
hint, before the learner answers. A fresh session on the same state then gets the repaired sentence,
as if the learner resumed the lesson, followed by a new sentence with the same mistake, its repair,
and one more sentence with the same structure. The checks read the saved state:

- the unanswered hint saved nothing: no mistake, attempt, or review;
- the resumed answer counted for nothing, and the first sentence was never recorded;
- the new mistake was saved once;
- no answer given after a hint was saved as unaided, and no transfer was claimed on the same day.

This makes real model calls on your accounts and takes a few minutes per run. It never uses
~/.deutschloop: the host gets its own state directory, and the run fails if the real one changes.

    python evals/interrupted_lesson.py --host claude
    python evals/interrupted_lesson.py --host codex --model gpt-6-astra
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from first_session import (  # noqa: E402
    CLAUDE_ALLOW_RULES, INTERNAL_TERMS, ROOT, SKILL_NAME, Check, ClaudeHost, CodexHost, Exchange, Run,
    dna, fingerprint, install_skill, normalized, write_transcript,
)

# None stands for the host's own opening prompt.
SESSIONS = (
    ("A", [("opener", None), ("mistake", "Heute bin ich mit mein Bruder ins Kino gegangen.")]),
    ("B", [("opener", None), ("resumed answer", "Heute bin ich mit meinem Bruder ins Kino gegangen."),
           ("new mistake", "Morgen fahre ich mit mein Auto zur Arbeit."),
           ("repair", "Morgen fahre ich mit meinem Auto zur Arbeit."),
           ("new sentence", "Am Samstag spiele ich mit meinem Freund Fußball.")]),
)
UNAIDED = {"independent", "spontaneous", "review pass"}


def saved(state: Path) -> list[dict[str, Any]]:
    path = state / "mistakes.json"
    return json.loads(path.read_text(encoding="utf-8")).get("mistakes", []) if path.exists() else []


def evidence(mistakes: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Every saved learner sentence, labelled with what it counts as."""
    items = []
    for mistake in mistakes:
        items += [("mistake", example.get("original") or "") for example in mistake.get("examples", [])]
        items += [(entry.get("outcome") or "attempt", entry.get("answer") or "") for entry in mistake.get("coaching_history", [])]
        items += [("spontaneous", entry.get("context") or "") for entry in mistake.get("correct_use_history", [])]
        items += [(f"review {entry.get('result')}", entry.get("answer") or "") for entry in mistake.get("review_history", [])]
    return items


def has(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {normalized(text)} "


def listing(items: list[tuple[str, str]]) -> str:
    return "; ".join(f"{kind}: {text}" for kind, text in items[:3])


def evaluate(run: Run, after_hint: list[dict[str, Any]] | None, mistakes: list[dict[str, Any]],
             real_before: dict[str, str], real_after: dict[str, str]) -> list[Check]:
    calls = [call for exchange in run.exchanges for call in exchange.tutor.calls]
    cli = [call for call in calls if call.is_cli]
    blocked = [call for call in calls if call.denied]
    failed = [call for call in cli if call.ok is False and not call.denied]
    checks = [
        Check("real state untouched", real_before == real_after, "~/.deutschloop unchanged" if real_before == real_after else "~/.deutschloop CHANGED during the run"),
        Check("no blocked calls", not blocked, f"{len(blocked)} blocked: " + "; ".join(call.text[:120] for call in blocked[:3]) if blocked else "none"),
        Check("no failed helper calls", not failed, "; ".join(f"{call.text[:100]} → {call.output[:160]}" for call in failed[:3]) or "none", hard=False),
    ]

    # Session A ends right after this reply, so it must be a hint: the reply and its visible commands keep the fix back.
    hint = next((exchange.tutor for exchange in run.exchanges if exchange.kind == "A: mistake"), None)
    said = hint is not None and re.search(r"(?<!\w)meinem(?!\w)", hint.text, re.I)
    shown = [call.text[:160] for call in hint.calls if "meinem" in call.text] if hint else []
    checks.append(Check("a hint, not the answer", hint is not None and not said and not shown,
                        "no reply to the mistake" if hint is None else "the reply shows meinem" if said else
                        f"a visible tool call shows the fix: {shown[0]}" if shown else "the session ended after a hint"))
    left = evidence(after_hint) if after_hint is not None else None
    checks.append(Check("the unanswered hint saved nothing", left == [],
                        "session A did not finish" if left is None else listing(left) if left else "no mistake, attempt, or review"))

    items = evidence(mistakes)
    first = [item for item in items if has(item[1], "mit mein bruder") or has(item[1], "mit meinem bruder")]
    checks.append(Check("the resumed answer counted for nothing", not first,
                        listing(first) if first else "nothing saved about the first sentence"))
    again = [item for item in items if item[0] == "mistake" and has(item[1], "mit mein auto")]
    checks.append(Check("the new mistake was saved once", len(again) == 1, f"{len(again)} records of the new sentence"))
    helped = {normalized(text) for kind, text in items if kind in {"assisted", "shown"}}
    unaided = [item for item in items if item[0] in UNAIDED and (has(item[1], "mit meinem auto") or normalized(item[1]) in helped)]
    proofs = [mistake.get("label") or mistake["pattern"] for mistake in mistakes if mistake.get("learning_proof")]
    checks.append(Check("help stayed help", not unaided and not proofs,
                        listing(unaided) if unaided else f"same-day transfer claimed for {proofs[0]}" if proofs
                        else "nothing after a hint was saved as unaided"))

    repaired = [item for item in items if item[0] == "assisted" and has(item[1], "mit meinem auto")]
    checks.append(Check("repair saved as assisted", bool(repaired), repaired[0][1] if repaired else "no assisted attempt for the repair", hard=False))
    transfer = [item for item in items if item[0] == "independent" and has(item[1], "mit meinem freund")]
    checks.append(Check("new sentence saved as unaided practice", bool(transfer),
                        transfer[0][1] if transfer else "not saved as independent practice", hard=False))
    leaks = [match.group(0) for exchange in run.exchanges for match in INTERNAL_TERMS.finditer(exchange.tutor.text)]
    checks.append(Check("no internals shown", not leaks, ", ".join(sorted(set(leaks))) or "none", hard=False))
    checks.append(Check("tool calls", None, f"{len(calls)} total, {len(cli)} helper", hard=False))
    return checks


def one_run(arguments: argparse.Namespace, host_name: str, number: int, out: Path) -> bool:
    token = uuid.uuid4().hex[:8]
    # Not mkdtemp: on Windows it limits the folder to the current user, and the Codex sandbox could not read it.
    work = Path(tempfile.gettempdir()) / f"deutschloop-interrupted-{host_name}-{token}"
    project, logs = work / "project", out / f"{host_name}-{number}"
    for directory in (project, logs):
        directory.mkdir(parents=True, exist_ok=True)
    state = Path.home() / f".deutschloop-smoke-{token}"
    skill_dir = project / (".claude" if host_name == "claude" else ".agents") / "skills" / SKILL_NAME
    real_home = dna.standard_home()
    real_before = fingerprint(real_home)
    env = {**os.environ, "DEUTSCHLOOP_HOME": str(state), "PYTHONIOENCODING": "utf-8"}
    env.pop("DEUTSCHLOOP_UTC_OFFSET", None)
    settings = work / "settings.json"
    settings.write_text(json.dumps({"permissions": {"allow": CLAUDE_ALLOW_RULES}}), encoding="utf-8")
    run = Run(host=host_name, setup="done")
    after_hint = None
    print(f"{host_name} run {number} · logs {logs}", flush=True)
    try:
        install_skill(arguments.source, skill_dir)
        state.mkdir()
        index = 0
        for session, script in SESSIONS:
            # A new host object starts a new chat; only the state directory carries over.
            host = (ClaudeHost(project=project, env=env, model=arguments.model, effort=arguments.effort, settings=settings, logs=logs)
                    if host_name == "claude" else
                    CodexHost(project=project, env=env, model=arguments.model, effort=arguments.effort, writable=state, logs=logs))
            for kind, message in script:
                message = message or host.first_prompt(skill_dir)
                turn = host.send(message, index)
                index += 1
                run.exchanges.append(Exchange(message, f"{session}: {kind}", turn))
                print(f"  {session} {kind} · {turn.seconds:.0f}s · {len(turn.calls)} tool calls" + (f" · error: {turn.error}" if turn.error else ""), flush=True)
                if turn.error and not turn.text:
                    raise RuntimeError(turn.error)
            if session == "A":
                after_hint = saved(state)
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        run.error = f"{type(exc).__name__}: {exc}"
    finally:
        checks = evaluate(run, after_hint, saved(state), real_before, fingerprint(real_home))
        if run.error:
            checks.insert(0, Check("host finished", False, run.error))
        write_transcript(logs / "transcript.md", run, checks, title="Interrupted lesson")
        report = {
            "host": host_name, "model": arguments.model, "effort": arguments.effort,
            "checks": [check.__dict__ for check in checks],
            "state_after_session_a": after_hint, "state_at_end": saved(state),
            "exchanges": [{"learner": exchange.learner, "kind": exchange.kind, "tutor": exchange.tutor.text,
                           "seconds": round(exchange.tutor.seconds, 1), "error": exchange.tutor.error,
                           "calls": [call.__dict__ for call in exchange.tutor.calls]} for exchange in run.exchanges],
        }
        (logs / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if not arguments.keep:
            shutil.rmtree(work, ignore_errors=True)
            shutil.rmtree(state, ignore_errors=True)
    passed = all(check.ok for check in checks if check.hard)
    print(f"\n{host_name} run {number}: {'PASS' if passed else 'FAIL'}")
    for check in checks:
        print(f"  {'✓' if check.ok else '✗' if check.ok is False else '·'} {check.name}: {check.detail}")
    print(f"  transcript: {logs / 'transcript.md'}\n")
    return passed


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Check an interrupted lesson in a real agent host")
    parser.add_argument("--host", choices=["claude", "codex", "both"], default="claude")
    parser.add_argument("--model", help="host model, for example opus or gpt-6-astra")
    parser.add_argument("--effort", help="host reasoning effort")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--source", type=Path, default=ROOT, help="the skill folder to test (default: this working tree)")
    parser.add_argument("--out", type=Path, help="where transcripts and reports go (default: a temporary folder)")
    parser.add_argument("--keep", action="store_true", help="keep the project and state folders for inspection")
    arguments = parser.parse_args(argv)
    out = arguments.out or Path(tempfile.gettempdir()) / "deutschloop-interrupted" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    hosts = ["claude", "codex"] if arguments.host == "both" else [arguments.host]
    results = [(host_name, one_run(arguments, host_name, number, out))
               for host_name in hosts for number in range(1, arguments.runs + 1)]
    if len(results) > 1:
        print("Summary")
        for host_name in hosts:
            runs = [passed for name, passed in results if name == host_name]
            print(f"  {host_name}: {sum(runs)}/{len(runs)} passed")
    print(f"Reports: {out}")
    return 0 if all(passed for _, passed in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
