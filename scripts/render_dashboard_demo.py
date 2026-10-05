#!/usr/bin/env python3
"""Build an offline, explorable story from isolated snapshots of the real engine."""

from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import deutsch_loop as dna


STORY_START = datetime(2026, 5, 20, 9, 0, tzinfo=timezone.utc)


def demo_payload(home: Path) -> dict[str, Any]:
    """Capture each chapter before later events exist; never reconstruct old scores."""
    if home.exists() and any(home.iterdir()):
        raise dna.DeutschLoopError("The dashboard demo requires an empty, isolated state directory")
    store = dna.StateStore(home)
    start = STORY_START
    store.init_profile(name="Alex", level="B2", at=start - timedelta(days=120))

    # Alex already has one older pattern. Its six reviews take the full scheduled time.
    article, _, _ = store.record(original="Der Rechnung ist hoch.", corrected="Die Rechnung ist hoch.",
                                 category="article", pattern="-ung nouns are feminine",
                                 rule="Nouns ending in -ung are feminine.", at=start - timedelta(days=120))
    article_tasks = [
        ("Was ist im Briefkasten angekommen? Nutze Rechnung.", "Heute ist die Rechnung angekommen."),
        ("Du hast das Büro gemietet. Was fehlt noch? Nutze Versicherung.", "Die Versicherung fehlt noch."),
        ("Du suchst eine neue Bleibe. Beschreibe die Wohnung.", "Die Wohnung ist hell und ruhig."),
        ("Was hast du heute gelesen? Nutze Zeitung.", "Ich habe die Zeitung im Zug gelesen."),
        ("Das Team bekommt eine neue Leitung. Wie findest du sie?", "Die neue Leitung ist sehr freundlich."),
        ("Wie war die Besprechung heute?", "Die Besprechung war kurz und hilfreich."),
    ]
    for prompt, answer in article_tasks:
        article, _ = store.grade(article["id"], result="pass", prompt=prompt, answer=answer,
                                 at=dna.parse_moment(article["next_review"]))

    mit, _, _ = store.record(original="Ich spreche mit mein Chef.", corrected="Ich spreche mit meinem Chef.",
                             category="case", pattern="mit + dative", rule="mit always governs the dative.", at=start)
    store.coach(mit["id"], outcome="assisted", prompt="Schau noch einmal auf mit mein Chef.",
                answer="Ich spreche mit meinem Chef.", strategy="Kasusfrage", hint="Frage dich: mit wem?",
                at=start + timedelta(minutes=2))
    warten, _, _ = store.record(original="Ich warte für den Bus.", corrected="Ich warte auf den Bus.",
                                category="preposition", pattern="warten auf + accusative",
                                rule="warten takes auf + accusative.", at=start + timedelta(minutes=3))
    store.coach(warten["id"], outcome="assisted", prompt="Welche Präposition gehört zu warten?",
                answer="Ich warte auf den Bus.", strategy="Verb und Präposition", hint="Denk an warten auf.",
                at=start + timedelta(minutes=4))
    weil, _, _ = store.record(original="Ich bleibe zu Hause, weil ich bin müde.",
                              corrected="Ich bleibe zu Hause, weil ich müde bin.", category="word-order",
                              pattern="weil sends finite verb to end", rule="In a weil clause the finite verb goes last.",
                              at=start + timedelta(minutes=5))
    store.record(original="Das ist ein wichtige Termin.", corrected="Das ist ein wichtiger Termin.",
                 category="agreement", pattern="adjective ending after ein-word",
                 rule="After ein, kein, mein the adjective shows the gender: ein wichtiger Termin.",
                 at=start + timedelta(minutes=6))
    frames = []

    def capture(days: int, minutes: int, chapter: str, title: str, story: str) -> None:
        snapshot = dna.dashboard_snapshot(store, at=start + timedelta(days=days, minutes=minutes))
        snapshot.update(chapter=chapter, title=title, story=story)
        frames.append(snapshot)

    capture(0, 8, "First try", "A hint, then self-repair",
            "Alex repairs mit mein Chef after a small hint. Useful practice; there is no later-day milestone yet.")
    store.grade(mit["id"], result="pass", prompt="Du telefonierst mit einer Kollegin. Erzähle davon in der Vergangenheit.",
                answer="Ich habe mit meiner Kollegin gesprochen.", at=start + timedelta(days=1, minutes=10))
    store.observe([warten["id"]], context="Vor dem Büro warte ich auf meinen Kollegen.",
                  at=start + timedelta(days=1, minutes=11))
    capture(1, 15, "Next day", "A new sentence, unaided",
            "A new review answer earns mit + Dativ its first milestone. warten auf also appears in Alex's own writing.")

    store.grade(weil["id"], result="hard", prompt="Warum bleibst du heute zu Hause?",
                answer="Ich bleibe zu Hause, weil ich krank bin.", strategy="Verbposition",
                hint="Nach weil steht das konjugierte Verb am Ende.", at=start + timedelta(days=2, minutes=20))
    store.grade(mit["id"], result="pass", prompt="Du reist nicht allein. Dein Bruder kommt mit. Mit wem reist du?",
                answer="Am Wochenende reise ich mit meinem Bruder nach Hamburg.", at=start + timedelta(days=4, minutes=10))
    store.record(mistake_id=warten["id"], original="Ich warte für meinen Kollegen.",
                 corrected="Ich warte auf meinen Kollegen.", at=start + timedelta(days=4, minutes=12))
    store.coach(warten["id"], outcome="assisted", prompt="Denk noch einmal an das Verb warten.",
                answer="Ich warte auf meinen Kollegen.", strategy="Verb und Präposition", hint="warten gehört zu auf.",
                at=start + timedelta(days=4, minutes=14))
    store.grade(weil["id"], result="pass", prompt="Es regnet stark. Erkläre, warum ihr zu Hause bleibt.",
                answer="Wir bleiben zu Hause, weil es stark regnet.", at=start + timedelta(days=5, minutes=10))
    store.grade(warten["id"], result="pass", prompt="Du bist am Bahnhof. Dein Bruder kommt mit dem Zug. Was machst du?",
                answer="Am Bahnsteig warte ich auf meinen Bruder.", at=start + timedelta(days=7, minutes=20))
    capture(7, 30, "One week later", "The pattern travels with you",
            "mit + Dativ now works in a travel situation too. Three patterns have saved learning milestones; they are still in practice.")

    store.record(mistake_id=mit["id"], original="Heute habe ich mit mein Nachbar gesprochen.",
                 corrected="Heute habe ich mit meinem Nachbarn gesprochen.", at=start + timedelta(days=103))
    capture(103, 5, "103 days later", "A return, with memory intact",
            "The mistake comes back. The engine resets its review ladder, while the earlier hint and learning milestone remain part of the story.")
    return {"version": 1, "demo": True, "frames": frames}


def main(argv: list[str] | None = None) -> int:
    dna._configure_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "demo" / "index.html")
    parser.add_argument("--force", action="store_true", help="Replace an existing demo HTML file")
    arguments = parser.parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix="deutschloop-dashboard-demo-") as temporary:
            result = dna.write_dashboard(demo_payload(Path(temporary)), arguments.output, force=arguments.force)
        dna._print_json(result)
        return 0
    except dna.DeutschLoopError as exc:
        dna._print_json({"error": str(exc)}, stream=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
