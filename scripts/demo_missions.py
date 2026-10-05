#!/usr/bin/env python3
"""Replay continuing interview preparation with scripted answers and real mission state."""

from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import deutsch_loop as dna


START = datetime(2026, 5, 20, 9, 0, tzinfo=timezone.utc)


def mission_demo_payload(home: Path) -> dict[str, Any]:
    if home.exists() and any(home.iterdir()):
        raise dna.DeutschLoopError("The mission demo requires an empty, isolated state directory")
    store = dna.StateStore(home)
    store.init_profile(name="Alex", level="B1", explanation_language="en", at=START - timedelta(days=1))
    mit, _, _ = store.record(original="Ich spreche mit mein Chef.", corrected="Ich spreche mit meinem Chef.",
                             category="case", pattern="mit + dative", rule="mit always governs the dative.",
                             at=START - timedelta(days=1))
    mission_id = store.mission_create(goal="I have a German-language job interview on Friday.",
                                       scenario="interview", deadline="friday", at=START)["mission"]["id"]
    frames = []

    def capture(at: datetime, chapter: str, title: str, story: str) -> None:
        frame = dna.dashboard_snapshot(store, at=at)
        frame.update(chapter=chapter, title=title, story=story)
        frames.append(frame)

    def scene(at: datetime, answer: str, *, hint: bool = False, corrected: str | None = None,
              outcome: str = "achieved", note: str) -> None:
        started = store.mission_start(mission_id, at=at)
        sid = started["session"]["id"]
        store.roleplay_turn(sid, speaker="partner", text=started["contract"]["opening"], at=at)
        turn = store.roleplay_turn(sid, speaker="learner", text=answer, at=at + timedelta(minutes=1))["utterance"]
        evidence = turn
        if hint:
            store.roleplay_turn(sid, speaker="partner", text="Schau auf mit mein Team. Frage dich: mit wem?",
                                 support="hint", at=at + timedelta(minutes=2))
            evidence = store.roleplay_turn(sid, speaker="learner", text=corrected,
                                            at=at + timedelta(minutes=3))["utterance"]
        store.roleplay_stop(sid, at=at + timedelta(minutes=4))
        if corrected:
            pattern = mit if hint else None
            params = {"mistake_id": pattern["id"]} if pattern else {
                "category": "word-order", "pattern": "weil sends finite verb to end", "rule": "After weil the finite verb goes last."}
            store.record(original=answer, corrected=corrected, session_id=sid, turn_id=turn["id"], **params)
            if hint:
                store.coach(mit["id"], outcome="assisted", prompt="Schau auf mit mein Team.", answer=evidence["text"],
                            strategy="Kasusfrage", hint="Schau auf mit mein Team. Frage dich: mit wem?", at=dna.parse_moment(evidence["at"]))
        else:
            # These scripted, unprompted productions use the known pattern in a new sentence.
            if "mit " in answer.casefold():
                store.observe([mit["id"]], context=answer, at=dna.parse_moment(turn["at"]))
            weil_id = dna.mistake_id("word-order", "weil sends finite verb to end")
            if "weil " in answer.casefold() and any(row["id"] == weil_id for row in store.list()):
                store.observe([weil_id], context=answer, at=dna.parse_moment(turn["at"]))
        store.roleplay_finish(sid, at=at + timedelta(minutes=5))
        store.mission_assess(mission_id, session_id=sid, result=outcome, support="hint" if hint else "none",
                             evidence_turn_ids=[evidence["id"]], note=note, at=at + timedelta(minutes=6))

    capture(START, "The goal", "Friday has a plan",
            "Alex's interview date and three communication goals are saved locally. Creating the plan earns no learning points.")
    original = "Ich bin Entwickler. Ich habe mit mein Team ein Kundenportal gebaut. Ich möchte Ihre Projekte unterstützen."
    correction = "Ich bin Entwickler. Ich habe mit meinem Team ein Kundenportal gebaut. Ich möchte Ihre Projekte unterstützen."
    scene(START + timedelta(minutes=10), original, hint=True, corrected=correction, outcome="practice",
          note="Alex introduced a role, a project, and motivation after a hint. The introduction stays open for a new unaided attempt.")
    capture(START + timedelta(minutes=20), "With help", "A smaller next attempt",
            "The first introduction needed a hint. The next scene keeps the goal, changes the opening, and carries the actual sentence and helpful cue.")
    scene(START + timedelta(days=1),
          "Ich entwickle Backend-Systeme. Mit meinen Kolleginnen habe ich ein Buchungssystem gebaut. Ich möchte diese Erfahrung in Ihr Team einbringen.",
          note="Alex independently described a role, a relevant project, and motivation in a new introduction.")
    difficult = "Einmal kam eine Anfrage zu spät. Weil der Termin war knapp, habe ich die Aufgaben mit dem Team neu verteilt. Danach konnten wir pünktlich liefern."
    scene(START + timedelta(days=1, hours=3), difficult,
          corrected="Einmal kam eine Anfrage zu spät. Weil der Termin knapp war, habe ich die Aufgaben mit dem Team neu verteilt. Danach konnten wir pünktlich liefern.",
          note="Alex explained a difficult situation, an action, and the result without help. A recorded weil word-order error becomes a focus for the follow-up.")
    capture(START + timedelta(days=1, hours=3, minutes=10), "The next session", "A follow-up shaped by history",
            "Two communication steps are complete. The next follow-up receives Alex's previous answer and the recorded weil error, alongside the earlier case pattern.")
    scene(START + timedelta(days=2),
          "Wenn die erste Lösung nicht funktioniert, spreche ich mit meinen Kollegen über eine Alternative, weil wir gemeinsam schneller eine Lösung finden.",
          note="Alex responded to the changed situation with a concrete alternative and a reason, without a hint.")
    capture(START + timedelta(days=2, minutes=10), "The result", "Three practice steps completed",
            "The communication-practice plan is complete. This is evidence from the scripted scenes, not a claim of interview readiness or overall fluency.")
    return {"version": 1, "demo": True, "experience": "missions", "frames": frames}


def main(argv: list[str] | None = None) -> int:
    dna._configure_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "demo" / "missions.html")
    parser.add_argument("--force", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix="deutschloop-mission-demo-") as temporary:
            payload = mission_demo_payload(Path(temporary))
            result = dna.write_dashboard(payload, arguments.output, force=arguments.force)
        dna._print_json(result)
        return 0
    except dna.DeutschLoopError as exc:
        dna._print_json({"error": str(exc)}, stream=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
