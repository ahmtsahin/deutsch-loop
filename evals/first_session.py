#!/usr/bin/env python3
"""Put DeutschLoop's first session through a real agent host.

A simulated learner, played by a small Claude model with a fixed script, talks to Claude Code or
Codex. The host uses a copy of this working tree as a skill. Afterwards the script reads the saved
state and the transcript and checks the first two minutes: how soon the learner writes German,
whether a hint comes before the answer, and whether the self-repair and the new situation were
saved.

This makes real model calls on your accounts and takes a few minutes per run. It never uses
~/.deutschloop: the host gets its own state directory, and the run fails if the real one changes.

    python evals/first_session.py --host claude
    python evals/first_session.py --host codex --model gpt-6-astra --setup none
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import deutsch_loop as dna  # noqa: E402

SKILL_NAME = "deutsch-loop-smoke"
TURN_TIMEOUT = 900
LEARNER_TIMEOUT = 300

# The one-time rules from the README that let the helper run without a prompt in every project.
CLAUDE_ALLOW_RULES = [
    f"{tool}({program} *deutsch_loop.py*)"
    for tool in ("Bash", "PowerShell")
    for program in ("python", "python3", "py")
] + [f"Read(~/.claude/skills/{SKILL_NAME}/**)"]

PERSONA = """You play a real person who opens a German tutor for the first time. You are Elif from Istanbul. You know a little German (about A2) and prefer explanations in Turkish. You only see the tutor's messages. Write like a person in a chat: short and natural, with no commentary about the exercise.

Follow these rules in order:
1. Answer only what the tutor asked. Use Turkish when the tutor asks about you: which language you prefer, how much German you know, your name or your goals. Examples: "Türkçe olsun." or "Biraz biliyorum." Do not write German until the tutor asks you to write or say something in German.
2. The first time the tutor asks you to write or say anything in German, answer with ONE short German sentence that fits the task and contains exactly one mistake: after "mit", use the wrong form of a masculine or neuter possessive, for example "mit mein Chef", "mit mein Bruder" or "mit mein Fahrrad", instead of the dative ("mit meinem ..."). Everything else in the sentence must be correct German.
3. If the tutor then hints that something in your sentence is wrong, or asks you to look again, send the same sentence again with only that mistake fixed.
4. If the tutor simply shows you the corrected sentence without letting you try, reply "Ah, danke!" and continue with rule 6.
5. After your repair, if the tutor gives you a new situation or task, answer with ONE new, correct German sentence that fits it and uses "mit" with the dative.
6. If the tutor asks anything else after that, or the conversation reaches a natural end, reply briefly and use kind "stop".

Return only a JSON object: {"message": "<what you type>", "kind": "setup" | "german" | "repair" | "transfer" | "chat" | "stop"}.
Use "german" only for your first German sentence, "repair" for the fixed version of it, and "transfer" for the new sentence in rule 5."""

INTERNAL_TERMS = re.compile(
    r"deutsch_loop|\bpython\b|\.json\b|\bJSON\b|--[a-z]|\bm_[0-9a-f]{6,}\b|\bmistake[_-]id\b|\brecap\b|\bonboarding\b|"
    r"\bstate director|\bshell\b|\bquoting\b|\bparser\b|\bCLI\b|\bsandbox\b",
    re.IGNORECASE,
)
SANDBOX_DENIAL = re.compile(
    r"access is denied|erişim engellendi|permission denied|PermissionError|operation not permitted",
    re.IGNORECASE,
)
# The helper's own report of a blocked state folder. SKILL.md quotes it too, so it counts only for a helper call:
# a failed command that also printed SKILL.md is not a blocked one.
STATE_DENIAL = re.compile(
    r"state_not_writable|could not open the state lock|could not create the state directory",
    re.IGNORECASE,
)


@dataclass
class ToolCall:
    kind: str
    text: str
    ok: bool | None = None
    output: str = ""
    denied: bool = False

    @property
    def is_cli(self) -> bool:
        return self.kind == "shell" and "deutsch_loop.py" in self.text


@dataclass
class TutorTurn:
    text: str
    calls: list[ToolCall]
    seconds: float
    cost_usd: float | None = None
    error: str | None = None


@dataclass
class Exchange:
    learner: str
    kind: str
    tutor: TutorTurn


@dataclass
class Check:
    name: str
    ok: bool | None
    detail: str
    hard: bool = True


@dataclass
class Run:
    host: str
    setup: str
    exchanges: list[Exchange] = field(default_factory=list)
    learner_cost_usd: float = 0.0
    error: str | None = None


# --------------------------------------------------------------------------- helpers


def parse_jsonl(text: str) -> list[dict[str, Any]]:
    events = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def flatten(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(flatten(item.get("text", item)) if isinstance(item, dict) else str(item) for item in content)
    return json.dumps(content, ensure_ascii=False)


def normalized(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def fingerprint(directory: Path) -> dict[str, str]:
    if not directory.is_dir():
        return {}
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*")) if path.is_file()
    }


def run_process(command: list[str], *, stdin: str, cwd: Path, env: dict[str, str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=cwd, env=env, timeout=timeout, check=False,
    )


def install_skill(source: Path, target: Path) -> None:
    """Copy the skill under a separate name, so an installed deutsch-loop cannot shadow it."""
    if target.exists():
        raise SystemExit(f"{target} already exists; remove it or pick another --install location")
    target.mkdir(parents=True)
    shutil.copytree(source / "references", target / "references")
    shutil.copytree(source / "agents", target / "agents")
    shutil.copytree(source / "docs", target / "docs")
    (target / "scripts").mkdir()
    for name in ("deutsch_loop.py", "scenario_catalog.py", "dashboard.html"):
        shutil.copy2(source / "scripts" / name, target / "scripts" / name)
    skill = re.sub(r"^name: .*$", f"name: {SKILL_NAME}", (source / "SKILL.md").read_text(encoding="utf-8"), count=1, flags=re.M)
    (target / "SKILL.md").write_bytes(skill.encode("utf-8"))


def codex_command() -> list[str]:
    """Run codex.js with node directly on Windows: the npm .cmd shim would pass arguments through cmd.exe."""
    shim = shutil.which("codex")
    if not shim:
        raise SystemExit("codex is not on PATH")
    script = Path(shim).parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
    node = shutil.which("node")
    return [node, str(script)] if os.name == "nt" and node and script.exists() else [shim]


def default_codex_prompt(skill_dir: Path) -> str:
    text = (skill_dir / "agents" / "openai.yaml").read_text(encoding="utf-8")
    match = re.search(r'default_prompt:\s*"(.*)"', text)
    prompt = match.group(1) if match else "Use $deutsch-loop to help me start practising German."
    return prompt.replace("$deutsch-loop", f"${SKILL_NAME}")


# --------------------------------------------------------------------------- hosts


class ClaudeHost:
    name = "claude"

    def __init__(self, *, project: Path, env: dict[str, str], model: str | None, effort: str | None,
                 settings: Path | None, logs: Path):
        self.exe = shutil.which("claude") or "claude"
        self.project, self.env, self.model, self.effort, self.settings, self.logs = project, env, model, effort, settings, logs
        self.session_id: str | None = None

    def first_prompt(self, skill_dir: Path) -> str:
        return f"/{SKILL_NAME}"

    def send(self, message: str, index: int) -> TutorTurn:
        command = [self.exe, "-p", "--output-format", "stream-json", "--verbose", "--setting-sources", "project,local",
                   "--permission-prompts", "none", "--strict-mcp-config"]
        if self.model:
            command += ["--model", self.model]
        if self.effort:
            command += ["--effort", self.effort]
        if self.settings:
            command += ["--settings", str(self.settings)]
        if self.session_id:
            command += ["--resume", self.session_id]
        started = time.monotonic()
        completed = run_process(command, stdin=message, cwd=self.project, env=self.env, timeout=TURN_TIMEOUT)
        seconds = time.monotonic() - started
        (self.logs / f"claude-turn-{index}.jsonl").write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
        texts: list[str] = []
        calls: list[ToolCall] = []
        by_id: dict[str, ToolCall] = {}
        cost, error = None, None
        for event in parse_jsonl(completed.stdout):
            kind = event.get("type")
            if kind == "assistant":
                for block in event["message"].get("content", []):
                    if block.get("type") == "text":
                        texts.append(block["text"])
                    elif block.get("type") == "tool_use":
                        call = self._call(block)
                        by_id[block.get("id")] = call
                        calls.append(call)
            elif kind == "user" and isinstance(event["message"].get("content"), list):
                for block in event["message"]["content"]:
                    call = by_id.get(block.get("tool_use_id")) if block.get("type") == "tool_result" else None
                    if call:
                        call.ok = not block.get("is_error")
                        call.output = flatten(block.get("content"))[:2000]
            elif kind == "result":
                self.session_id = event.get("session_id") or self.session_id
                for denial in event.get("permission_denials") or []:
                    if denial.get("tool_use_id") in by_id:
                        by_id[denial["tool_use_id"]].denied = True
                cost = event.get("total_cost_usd")
                if event.get("is_error"):
                    error = str(event.get("result"))[:500]
        if completed.returncode and not error:
            error = completed.stderr.strip()[:500] or f"claude exited with {completed.returncode}"
        return TutorTurn("\n\n".join(text.strip() for text in texts if text.strip()), calls, seconds, cost, error)

    @staticmethod
    def _call(block: dict[str, Any]) -> ToolCall:
        name, data = block.get("name"), block.get("input") or {}
        if name in ("Bash", "PowerShell"):
            return ToolCall("shell", data.get("command", ""))
        if name == "Read":
            return ToolCall("read", data.get("file_path", ""))
        return ToolCall("skill" if name == "Skill" else "other", f"{name} {json.dumps(data, ensure_ascii=False)[:300]}")


class CodexHost:
    name = "codex"

    def __init__(self, *, project: Path, env: dict[str, str], model: str | None, effort: str | None,
                 writable: Path | None, logs: Path):
        self.base = codex_command()
        self.project, self.env, self.model, self.effort, self.writable, self.logs = project, env, model, effort, writable, logs
        self.thread_id: str | None = None

    def first_prompt(self, skill_dir: Path) -> str:
        return default_codex_prompt(skill_dir)

    def send(self, message: str, index: int) -> TutorTurn:
        options = ["--json", "--skip-git-repo-check", "-C", str(self.project),
                   "-c", 'sandbox_mode="workspace-write"', "-c", 'approval_policy="never"']
        if self.writable:
            options += ["-c", f"sandbox_workspace_write.writable_roots=['{self.writable}']"]
        if self.model:
            options += ["-m", self.model]
        if self.effort:
            options += ["-c", f'model_reasoning_effort="{self.effort}"']
        command = [*self.base, "exec", *options, *(["resume", self.thread_id] if self.thread_id else []), "-"]
        started = time.monotonic()
        completed = run_process(command, stdin=message, cwd=self.project, env=self.env, timeout=TURN_TIMEOUT)
        seconds = time.monotonic() - started
        (self.logs / f"codex-turn-{index}.jsonl").write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
        texts: list[str] = []
        calls: list[ToolCall] = []
        error = None
        for event in parse_jsonl(completed.stdout):
            kind = event.get("type")
            if kind == "thread.started":
                self.thread_id = self.thread_id or event.get("thread_id")
            elif kind == "item.completed":
                item = event.get("item") or {}
                if item.get("type") == "agent_message":
                    texts.append(item.get("text", ""))
                elif item.get("type") == "command_execution":
                    command, output = item.get("command", ""), item.get("aggregated_output") or ""
                    ok = item.get("exit_code") == 0
                    denied = SANDBOX_DENIAL.search(output) or ("deutsch_loop.py" in command and STATE_DENIAL.search(output))
                    calls.append(ToolCall("shell", command, ok, output[:2000], denied=not ok and bool(denied)))
            elif kind in ("turn.failed", "error"):
                error = json.dumps(event, ensure_ascii=False)[:500]
        if completed.returncode and not error:
            error = completed.stderr.strip()[-500:] or f"codex exited with {completed.returncode}"
        return TutorTurn("\n\n".join(text.strip() for text in texts if text.strip()), calls, seconds, None, error)


# --------------------------------------------------------------------------- learner


class Learner:
    def __init__(self, *, model: str, cwd: Path, env: dict[str, str]):
        self.exe = shutil.which("claude") or "claude"
        self.model, self.cwd, self.env = model, cwd, env

    def reply(self, exchanges: list[Exchange]) -> tuple[str, str, float]:
        lines = []
        for exchange in exchanges:
            if exchange.kind != "opener":
                lines.append(f"You: {exchange.learner}")
            lines.append(f"Tutor: {exchange.tutor.text or '(no reply)'}")
        done = {exchange.kind for exchange in exchanges}
        progress = ", ".join(f"{label}: {'done' if kind in done else 'not yet'}" for kind, label in (
            ("german", "first German sentence"), ("repair", "repaired sentence"), ("transfer", "new-situation sentence")))
        prompt = "Conversation so far:\n\n" + "\n\n".join(lines) + f"\n\nYour progress: {progress}.\n\nWrite your next message now, as JSON only."
        command = [self.exe, "-p", "--model", self.model, "--system-prompt", PERSONA, "--tools", "",
                   "--disable-slash-commands", "--strict-mcp-config", "--setting-sources", "project",
                   "--no-session-persistence", "--output-format", "json"]
        completed = run_process(command, stdin=prompt, cwd=self.cwd, env=self.env, timeout=LEARNER_TIMEOUT)
        try:
            data = json.loads(completed.stdout)
            match = re.search(r"\{.*\}", data.get("result", ""), re.S)
            reply = json.loads(match.group(0)) if match else {}
        except (json.JSONDecodeError, AttributeError):
            raise RuntimeError(f"The simulated learner returned no JSON: {completed.stdout[:300]} {completed.stderr[:300]}")
        message, kind = str(reply.get("message", "")).strip(), str(reply.get("kind", "chat"))
        if not message:
            kind = "stop"
        return message, kind, float(data.get("total_cost_usd") or 0)


# --------------------------------------------------------------------------- session and checks


def converse(host: ClaudeHost | CodexHost, learner: Learner, skill_dir: Path, *, max_turns: int, log) -> Run:
    run = Run(host=host.name, setup="")
    message, kind = host.first_prompt(skill_dir), "opener"
    for index in range(max_turns + 1):
        turn = host.send(message, index)
        run.exchanges.append(Exchange(message, kind, turn))
        log(f"  tutor turn {index} · {turn.seconds:.0f}s · {len(turn.calls)} tool calls" + (f" · error: {turn.error}" if turn.error else ""))
        if turn.error and not turn.text:
            run.error = turn.error
            break
        if kind == "transfer" or index == max_turns:
            break
        message, kind, cost = learner.reply(run.exchanges)
        run.learner_cost_usd += cost
        log(f"  learner ({kind}): {message}")
        if kind == "stop":
            break
    return run


def first(exchanges: list[Exchange], kind: str) -> int | None:
    return next((index for index, exchange in enumerate(exchanges) if exchange.kind == kind), None)


def evaluate(run: Run, state: Path, real_before: dict[str, str], real_after: dict[str, str]) -> list[Check]:
    profile = json.loads((state / "profile.json").read_text(encoding="utf-8")) if (state / "profile.json").exists() else {}
    mistakes = json.loads((state / "mistakes.json").read_text(encoding="utf-8")).get("mistakes", []) if (state / "mistakes.json").exists() else []
    exchanges = run.exchanges
    calls = [call for exchange in exchanges for call in exchange.tutor.calls]
    cli = [call for call in calls if call.is_cli]
    blocked = [call for call in calls if call.denied]
    failed = [call for call in cli if call.ok is False and not call.denied]
    checks = [
        Check("real state untouched", real_before == real_after, "~/.deutschloop unchanged" if real_before == real_after else "~/.deutschloop CHANGED during the run"),
        Check("state saved", bool(profile), f"{len(cli)} helper calls, profile {'written' if profile else 'missing'}"),
        Check("no blocked calls", not blocked, f"{len(blocked)} blocked: " + "; ".join(call.text[:120] for call in blocked[:3]) if blocked else "none"),
        Check("no failed helper calls", not failed, "; ".join(f"{call.text[:100]} → {call.output[:160]}" for call in failed[:3]) or "none", hard=False),
    ]

    german = first(exchanges, "german")
    checks.append(Check("German by learner turn 2", german is not None and german <= 2,
                        f"first German sentence in learner turn {german}" if german else "the learner never wrote German"))
    checks.append(Check("onboarding complete", bool(profile.get("onboarding_completed_at")),
                        f"completed at {profile.get('onboarding_completed_at')}" if profile.get("onboarding_completed_at") else "not marked"))

    sentence = exchanges[german].learner if german is not None else None
    record = None
    for mistake in mistakes:
        for example in [mistake.get("first_example") or {}, *mistake.get("examples", [])]:
            # The learner's message may hold more than the one sentence that was recorded.
            if sentence and example.get("original") and normalized(example["original"]) in normalized(sentence):
                record = (mistake, example)
    checks.append(Check("mistake saved", record is not None,
                        f"{record[0].get('label') or record[0]['pattern']}: {record[1]['original']} → {record[1]['corrected']}" if record else "no record of the learner's sentence"))

    if german is None:
        checks.append(Check("hint before the answer", False, "no German sentence to repair"))
    else:
        # The reply to the learner's sentence, and its tool calls, which both hosts display, must not contain the fix.
        hint_turn = exchanges[german].tutor
        if record:
            changed = [token for change in dna.analyze_correction(record[1]["original"], record[1]["corrected"])["changes"]
                       for token in change.get("corrected_tokens", [])]
        else:
            changed = ["meinem"]
        repaired = first(exchanges, "repair") is not None
        said = [token for token in changed if re.search(rf"(?<!\w){re.escape(token)}(?!\w)", hint_turn.text, re.I)]
        shown = [call.text[:160] for call in hint_turn.calls if any(token in call.text for token in changed)]
        checks.append(Check("hint before the answer", repaired and not said and not shown,
                            "the learner repaired it after a hint" if repaired and not said and not shown else
                            f"the reply shows {said}" if said else f"a visible tool call shows the fix: {shown[0]}" if shown
                            else "no self-repair happened"))

    coaching = [entry for mistake in mistakes for entry in mistake.get("coaching_history", [])]
    assisted = [entry for entry in coaching if entry.get("outcome") == "assisted" and entry.get("hint")]
    checks.append(Check("self-repair saved", bool(assisted), f"hint: {assisted[-1]['hint']}" if assisted else "no assisted attempt saved"))
    transfer = first(exchanges, "transfer")
    independent = [entry for entry in coaching if entry.get("outcome") == "independent"]
    matched = [entry for entry in independent if transfer is not None and entry.get("answer")
               and normalized(entry["answer"]) in normalized(exchanges[transfer].learner)]
    checks.append(Check("new situation saved", bool(matched),
                        f"task: {matched[-1]['prompt'][:120]}" if matched else
                        "the learner never got a new situation" if transfer is None else "the new sentence was not saved as independent practice"))

    leaks = [match.group(0) for exchange in exchanges for match in INTERNAL_TERMS.finditer(exchange.tutor.text)]
    checks.append(Check("no internals shown", not leaks, ", ".join(sorted(set(leaks))) or "none"))

    hint_index = german if german is not None else len(exchanges) - 1
    seconds = sum(exchange.tutor.seconds for exchange in exchanges[: hint_index + 1])
    checks.append(Check("tutor time to first hint", None, f"{seconds:.0f}s over {hint_index + 1} tutor turns", hard=False))
    checks.append(Check("tool calls", None, f"{len(calls)} total, {len(cli)} helper, " +
                        ", ".join(f"turn {i}: {len(exchange.tutor.calls)}" for i, exchange in enumerate(exchanges)), hard=False))
    if run.host == "claude":
        # In manual mode every helper call asks unless the learner added the README rule or chose "don't ask again".
        checks.append(Check("prompts without the one-time rule", None, f"up to {len(cli)} helper calls would ask", hard=False))
    if profile.get("explanation_language"):
        checks.append(Check("explanation language", None, profile["explanation_language"], hard=False))
    return checks


def write_transcript(path: Path, run: Run, checks: list[Check], title: str = "First session") -> None:
    lines = [f"# {title} · {run.host} · setup {run.setup}", ""]
    for index, exchange in enumerate(run.exchanges):
        lines += [f"## Turn {index} · learner ({exchange.kind})", "", exchange.learner, ""]
        for call in exchange.tutor.calls:
            status = "denied" if call.denied else "ok" if call.ok else "failed" if call.ok is False else "?"
            lines.append(f"- `{call.kind}` [{status}] {call.text[:300]}")
        lines += ["", f"### Tutor · {exchange.tutor.seconds:.0f}s", "", exchange.tutor.text or "(no text)", ""]
        if exchange.tutor.error:
            lines += [f"> error: {exchange.tutor.error}", ""]
    lines += ["## Checks", ""] + [f"- {'✓' if check.ok else '✗' if check.ok is False else '·'} {check.name}: {check.detail}" for check in checks]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def one_run(arguments: argparse.Namespace, host_name: str, number: int, out: Path) -> tuple[bool, list[Check]]:
    token = uuid.uuid4().hex[:8]
    # Not mkdtemp: on Windows it limits the folder to the current user, and the Codex sandbox could not read it.
    work = Path(tempfile.gettempdir()) / f"deutschloop-{host_name}-{token}"
    project, learner_dir, logs = work / "project", work / "learner", out / f"{host_name}-{number}"
    for directory in (project, learner_dir, logs):
        directory.mkdir(parents=True, exist_ok=True)
    # Where a real installation keeps its state: in the home directory, outside the project and temp folders.
    state = Path.home() / f".deutschloop-smoke-{token}"
    personal = {"claude": Path.home() / ".claude" / "skills", "codex": Path.home() / ".codex" / "skills"}[host_name]
    skills = personal if arguments.install == "personal" else project / (".claude" if host_name == "claude" else ".agents") / "skills"
    skill_dir = skills / SKILL_NAME
    real_home = dna.standard_home()
    real_before = fingerprint(real_home)
    env = {**os.environ, "DEUTSCHLOOP_HOME": str(state), "PYTHONIOENCODING": "utf-8"}
    env.pop("DEUTSCHLOOP_UTC_OFFSET", None)
    log = lambda text: print(text, flush=True)  # noqa: E731
    run = Run(host=host_name, setup=arguments.setup)
    checks: list[Check] = []
    installed = False
    try:
        install_skill(arguments.source, skill_dir)
        installed = True
        if host_name == "claude":
            settings = None
            if arguments.setup == "done":
                settings = work / "settings.json"
                settings.write_text(json.dumps({"permissions": {"allow": CLAUDE_ALLOW_RULES}}), encoding="utf-8")
            host: ClaudeHost | CodexHost = ClaudeHost(project=project, env=env, model=arguments.model, effort=arguments.effort,
                                                      settings=settings, logs=logs)
        else:
            if arguments.setup == "done":
                state.mkdir()
            host = CodexHost(project=project, env=env, model=arguments.model, effort=arguments.effort,
                             writable=state if arguments.setup == "done" else None, logs=logs)
        learner = Learner(model=arguments.learner_model, cwd=learner_dir, env=env)
        log(f"{host_name} run {number} · setup {arguments.setup} · install {arguments.install} · logs {logs}")
        run = converse(host, learner, skill_dir, max_turns=arguments.max_turns, log=log)
        run.setup = arguments.setup
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        run.error = f"{type(exc).__name__}: {exc}"
    finally:
        real_after = fingerprint(real_home)
        checks = evaluate(run, state, real_before, real_after)
        if run.error:
            checks.insert(0, Check("host finished", False, run.error))
        write_transcript(logs / "transcript.md", run, checks)
        report = {
            "host": host_name, "setup": arguments.setup, "install": arguments.install, "model": arguments.model,
            "effort": arguments.effort, "learner_model": arguments.learner_model,
            "tutor_seconds": round(sum(exchange.tutor.seconds for exchange in run.exchanges), 1),
            "tutor_cost_usd": sum(exchange.tutor.cost_usd or 0 for exchange in run.exchanges) or None,
            "learner_cost_usd": round(run.learner_cost_usd, 4),
            "checks": [check.__dict__ for check in checks],
            "exchanges": [{"learner": exchange.learner, "kind": exchange.kind, "tutor": exchange.tutor.text,
                           "seconds": round(exchange.tutor.seconds, 1), "error": exchange.tutor.error,
                           "calls": [call.__dict__ for call in exchange.tutor.calls]} for exchange in run.exchanges],
        }
        (logs / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if not arguments.keep:
            shutil.rmtree(work, ignore_errors=True)
            shutil.rmtree(state, ignore_errors=True)
        if installed and arguments.install == "personal":
            shutil.rmtree(skill_dir, ignore_errors=True)
    passed = all(check.ok for check in checks if check.hard)
    print(f"\n{host_name} run {number}: {'PASS' if passed else 'FAIL'} · tutor time {report['tutor_seconds']:.0f}s")
    for check in checks:
        print(f"  {'✓' if check.ok else '✗' if check.ok is False else '·'} {check.name}: {check.detail}")
    print(f"  transcript: {logs / 'transcript.md'}\n")
    return passed, checks


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Check DeutschLoop's first session in a real agent host")
    parser.add_argument("--host", choices=["claude", "codex", "both"], default="claude")
    parser.add_argument("--setup", choices=["done", "none"], default="done",
                        help="done: the one-time permission setup from the README; none: a fresh install where nobody approves prompts")
    parser.add_argument("--install", choices=["project", "personal"], default="project",
                        help="where the skill copy goes; personal uses ~/.claude/skills or ~/.codex/skills and removes it afterwards")
    parser.add_argument("--model", help="host model, for example opus or gpt-6-astra")
    parser.add_argument("--effort", help="host reasoning effort")
    parser.add_argument("--learner-model", default="haiku", help="Claude model that plays the learner")
    parser.add_argument("--max-turns", type=int, default=6, help="learner messages before the run stops")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--source", type=Path, default=ROOT, help="the skill folder to test (default: this working tree)")
    parser.add_argument("--out", type=Path, help="where transcripts and reports go (default: a temporary folder)")
    parser.add_argument("--keep", action="store_true", help="keep the project and state folders for inspection")
    arguments = parser.parse_args(argv)
    out = arguments.out or Path(tempfile.gettempdir()) / "deutschloop-first-session" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    hosts = ["claude", "codex"] if arguments.host == "both" else [arguments.host]
    results = []
    for host_name in hosts:
        for number in range(1, arguments.runs + 1):
            passed, checks = one_run(arguments, host_name, number, out)
            results.append((host_name, passed, checks))
    if len(results) > 1:
        print("Summary")
        for host_name in hosts:
            runs = [result for result in results if result[0] == host_name]
            print(f"  {host_name}: {sum(passed for _, passed, _ in runs)}/{len(runs)} passed")
    print(f"Reports: {out}")
    return 0 if all(passed for _, passed, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
