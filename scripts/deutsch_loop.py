#!/usr/bin/env python3
"""DeutschLoop's dependency-free local mistake memory, word deck, and review engine.

All learner state is plain JSON under one directory, and nothing leaves the machine.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import difflib
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from scenario_catalog import SCENARIOS, SCENARIO_ALIASES, mission_steps, scenario_examples

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt


SCHEMA_VERSION = 3
REVIEW_INTERVALS = (1, 3, 7, 14, 30, 60)
RECENT_DAYS = 7
EXAMPLE_LIMIT = 12
HISTORY_LIMIT = 30
DUPLICATE_RECORD_WINDOW = timedelta(minutes=30)
DUPLICATE_EVENT_WINDOW = timedelta(minutes=5)
SIMILARITY_HINT_THRESHOLD = 0.72
# Two keys in the same template (`mit + dative`, `bei + dative`, `Tisch`/`Fisch is masculine`)
# name different patterns; only a near-identical spelling of the differing word suggests one
# root cause. Umlauts and ß are compared as ae/oe/ue/ss, since agents sometimes write them so.
SPELLING_VARIANT_THRESHOLD = 0.85
# A review or unaided answer sharing this share of its words with an earlier one reuses its frame.
VARIETY_WARNING_THRESHOLD = 0.6
VARIETY_MIN_WORDS = 4
LOCK_TIMEOUT_SECONDS = 20.0
CLUSTER_MIN_PATTERNS = 2
CLUSTER_MIN_OCCURRENCES = 3
WEAK_ACCURACY_THRESHOLD = 60
CLUSTER_WINDOW = timedelta(days=30)
TIMELINE_LIMIT = 16
FULL_PROFILE_INTERVAL_DAYS = 7
STARTING_POINTS = frozenset({"beginner", "some", "comfortable", "unsure"})
CEFR_LEVELS = frozenset({"A1", "A2", "B1", "B2", "C1", "C2"})
MISSION_SCHEMA_VERSION = 1
BOARD_ROWS = 5
LABEL_WIDTH = 36
LABEL_MAX_LENGTH = 60
WEEKDAYS_DE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
REVIEW_CONTEXT = "spaced-repetition review"
# A scene yields a handful of useful words; each one then enters the learner's word deck.
SCENE_VOCABULARY_LIMIT = 5
WORD_SOURCE_LIMIT = 5
VOCABULARY_SCHEMA_VERSION = 1
LEADING_ARTICLE = re.compile(r"^(der|die|das)\s+", re.IGNORECASE)

CATEGORY_ORDER = (
    "article",
    "case",
    "preposition",
    "word-order",
    "verb",
    "agreement",
    "plural",
    "spelling",
    "vocabulary",
    "register",
    "punctuation",
    "other",
)
CATEGORIES = frozenset(CATEGORY_ORDER)
# German display names for the human-readable profile; JSON keeps the English IDs.
CATEGORY_LABELS = {
    "article": "Artikel",
    "case": "Kasus",
    "preposition": "Präpositionen",
    "word-order": "Wortstellung",
    "verb": "Verben",
    "agreement": "Endungen",
    "plural": "Plural",
    "spelling": "Rechtschreibung",
    "vocabulary": "Wortschatz",
    "register": "Register",
    "punctuation": "Zeichensetzung",
    "other": "Sonstiges",
}
# Pattern keys are normalized so that German and English case names, common
# abbreviations, and "governs/takes" phrasings all land on the same key.
PATTERN_ALIASES = {
    "dativ": "dative",
    "dat": "dative",
    "akkusativ": "accusative",
    "akk": "accusative",
    "acc": "accusative",
    "accusativ": "accusative",
    "nominativ": "nominative",
    "nom": "nominative",
    "genitiv": "genitive",
    "gen": "genitive",
    "governs": "+",
    "takes": "+",
    "requires": "+",
    "needs": "+",
    "verlangt": "+",
    "regiert": "+",
}
DROPPED_PATTERN_TOKENS = frozenset({"case", "kasus", "the"})


class DeutschLoopError(Exception):
    """A user-facing CLI error; `code` names the errors an agent handles in its own way."""

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


STATE_NOT_WRITABLE = "state_not_writable"


def _state_not_writable(home: Path, exc: OSError) -> DeutschLoopError:
    return DeutschLoopError(
        f"Cannot write the learner's progress in {home}: {exc}. An agent sandbox may be blocking this folder; "
        "run the command again with the learner's approval, or allow the folder once as the README describes.",
        code=STATE_NOT_WRITABLE,
    )


# --------------------------------------------------------------------------- time


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def parse_moment(value: str | None) -> datetime:
    if not value:
        return utc_now()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DeutschLoopError(f"Invalid ISO-8601 time: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _setting(name: str) -> str:
    """DEUTSCHLOOP_<name>, or DEUTSCHDNA_<name> as it was set before the project was renamed."""
    return os.environ.get(f"DEUTSCHLOOP_{name}") or os.environ.get(f"DEUTSCHDNA_{name}") or ""


def local_zone() -> timezone | None:
    """The learner's time zone: DEUTSCHLOOP_UTC_OFFSET such as +02:00, or the system zone by default."""
    configured = _setting("UTC_OFFSET").strip()
    if not configured:
        return None
    match = re.fullmatch(r"([+-])(\d{1,2}):?(\d{2})", configured)
    if not match:
        raise DeutschLoopError(f"Invalid DEUTSCHLOOP_UTC_OFFSET '{configured}'; use a form like +02:00")
    offset = timedelta(hours=int(match.group(2)), minutes=int(match.group(3)))
    return timezone(offset if match.group(1) == "+" else -offset)


def to_local(moment: datetime) -> datetime:
    """Stored times are UTC; everything shown to the learner is local."""
    zone = local_zone()
    return moment.astimezone(zone) if zone else moment.astimezone()


def local_date(moment: datetime) -> date:
    return to_local(moment).date()


def local_iso(stamp: str | None) -> str | None:
    parsed = _safe_moment(stamp)
    return to_local(parsed).isoformat() if parsed else None


def parse_deadline(value: str | None, moment: datetime) -> str | None:
    """Resolve a stated date on the learner's local calendar, without guessing an event time."""
    if value is None or not value.strip():
        return None
    text = value.strip().casefold()
    today = local_date(moment)
    if text in {"today", "heute", "bugün", "bugun"}:
        return today.isoformat()
    if text in {"tomorrow", "morgen", "yarın", "yarin"}:
        return (today + timedelta(days=1)).isoformat()
    weekdays = {
        "monday": 0, "montag": 0, "pazartesi": 0, "tuesday": 1, "dienstag": 1, "salı": 1, "sali": 1,
        "wednesday": 2, "mittwoch": 2, "çarşamba": 2, "carsamba": 2, "thursday": 3, "donnerstag": 3, "perşembe": 3, "persembe": 3,
        "friday": 4, "freitag": 4, "cuma": 4, "saturday": 5, "samstag": 5, "cumartesi": 5,
        "sunday": 6, "sonntag": 6, "pazar": 6,
    }
    if text in weekdays:
        return (today + timedelta(days=(weekdays[text] - today.weekday()) % 7)).isoformat()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            pass
    raise DeutschLoopError("Deadline must be YYYY-MM-DD, today/tomorrow, or a weekday in English, German, or Turkish")


def _safe_moment(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parse_moment(value)
    except DeutschLoopError:
        return None


def within(stamp: str | None, moment: datetime, window: timedelta) -> bool:
    parsed = _safe_moment(stamp)
    return parsed is not None and abs(parsed - moment) <= window


def streak_days(days: set[date], today: date) -> int:
    cursor = today if today in days else today - timedelta(days=1)
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


# --------------------------------------------------------------------------- keys


def normalized(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).strip().lower())


def pattern_key(pattern: str) -> str:
    """Canonical key for a root-cause pattern; tolerant of casing, spacing, and German case names."""
    text = normalized(pattern)
    text = re.sub(r"\s*\+\s*", " + ", text)
    text = re.sub(r"[^\w+\s/-]", " ", text)
    tokens: list[str] = []
    for token in text.split():
        token = PATTERN_ALIASES.get(token, token)
        if not token or token in DROPPED_PATTERN_TOKENS:
            continue
        if token == "+" and tokens and tokens[-1] == "+":
            continue
        tokens.append(token)
    return " ".join(tokens).strip("+ ")


def compact_key(key: str) -> str:
    return re.sub(r"[^\w]", "", key)


def mistake_id_for(category: str, key: str) -> str:
    digest = hashlib.sha256(f"{category}\0{key}".encode("utf-8")).hexdigest()[:12]
    return f"m_{digest}"


def mistake_id(category: str, pattern: str) -> str:
    return mistake_id_for(category, pattern_key(pattern))


def auto_event_id(original: str, corrected: str) -> str:
    digest = hashlib.sha256(f"{normalized(original)}\0{normalized(corrected)}".encode("utf-8")).hexdigest()[:16]
    return f"auto_{digest}"


def category_rank(category: str) -> int:
    return CATEGORY_ORDER.index(category) if category in CATEGORY_ORDER else len(CATEGORY_ORDER)


# --------------------------------------------------------------------------- German labels

# German names for catalog keys that are not a plain "<word> + <case>" rule. Keys are
# normalized with pattern_key, so spelling variants of a key share one label.
_CATALOG_LABELS_RAW = {
    "-ung nouns are feminine": "-ung-Wörter sind feminin",
    "-heit/-keit nouns are feminine": "-heit/-keit sind feminin",
    "-chen/-lein nouns are neuter": "-chen/-lein sind neutral",
    "-ment/-um nouns are neuter": "-ment/-um sind meist neutral",
    "-ismus nouns are masculine": "-ismus ist maskulin",
    "nominalized infinitives are neuter": "das Essen, das Lernen",
    "no article before profession or nationality": "kein Artikel vor Berufen",
    "country names with article": "Länder mit Artikel",
    "two-way preposition: location takes dative": "Wo? → Dativ",
    "two-way preposition: direction takes accusative": "Wohin? → Akkusativ",
    "masculine accusative -en": "den/einen im Akkusativ",
    "n-declension nouns take -n/-en": "n-Deklination: dem Kunden",
    "dative plural -n": "Dativ Plural: -n",
    "predicate noun after sein takes nominative": "sein + Nominativ",
    "pronoun case after preposition": "mir/mich nach Präposition",
    "nach vs zu for destinations": "nach oder zu?",
    "in vs nach for countries": "in die Türkei, nach Deutschland",
    "seit vs vor": "seit oder vor?",
    "am/um/im for time expressions": "am/um/im bei Zeitangaben",
    "bei for at a person or company": "bei + Firma oder Person",
    "zu Hause vs nach Hause": "zu Hause oder nach Hause?",
    "finite verb in second position": "Verb an Position 2",
    "relative clause verb to end": "Relativsatz: Verb ans Ende",
    "separable prefix goes to clause end": "trennbares Präfix ans Ende",
    "past participle at clause end": "Partizip ans Satzende",
    "infinitive after modal at clause end": "Infinitiv ans Satzende",
    "time-manner-place order": "Zeit, Art, Ort",
    "nicht position": "Position von nicht",
    "coordinating conjunctions keep word order": "und/aber/denn: Verb bleibt",
    "adverb connectors trigger inversion": "deshalb/dann: Verb zuerst",
    "dative before accusative noun objects": "Dativ vor Akkusativ",
    "yes/no question verb first": "Ja/Nein-Frage: Verb zuerst",
    "sein as perfect auxiliary for motion and change": "Perfekt mit sein",
    "-ieren verbs take no ge-": "-ieren ohne ge-",
    "inseparable prefix verbs take no ge-": "be-/ver-/er- ohne ge-",
    "stem vowel change in du/er forms": "Vokalwechsel: du fährst",
    "modal verbs have no -t in 3rd person": "er kann, er muss",
    "infinitive with zu after non-modal verbs": "zu + Infinitiv",
    "Präteritum for sein/haben/modals": "war, hatte, konnte",
    "werden for future and passive": "werden: Futur und Passiv",
    "hätte/wäre/würde for polite and unreal": "hätte, wäre, würde",
    "adjective ending after der-word": "Adjektiv nach der/die/das",
    "adjective ending after ein-word": "Adjektiv nach ein/kein/mein",
    "adjective ending without article": "Adjektiv ohne Artikel",
    "possessive agrees with the possessed noun": "mein/meine: das Nomen zählt",
    "subject-verb agreement": "Subjekt und Verb",
    "der-word endings": "dieser, jeder, welcher",
    "-ung plural adds -en": "-ung → -ungen",
    "feminine -e plural adds -n": "-e → -en im Plural",
    "-in plural is -innen": "-in → -innen",
    "umlaut plural": "Plural mit Umlaut",
    "-s plural for loanwords": "-s-Plural: die Autos",
    "plural after numbers above one": "Plural nach Zahlen",
    "German nouns are capitalized": "Nomen großschreiben",
    "dass vs das": "dass oder das?",
    "ß after long vowel, ss after short": "ß oder ss?",
    "compound nouns are one word": "Komposita zusammenschreiben",
    "formal Sie is capitalized": "Sie großschreiben",
    "umlauts are written": "Umlaute schreiben",
    "kennen vs wissen": "kennen oder wissen?",
    "wenn vs als vs wann": "wenn, als oder wann?",
    "möchten vs mögen vs gern": "möchte, mag oder gern?",
    "bekommen means receive": "bekommen heißt erhalten",
    "eine Entscheidung treffen": "eine Entscheidung treffen",
    "einen Termin vereinbaren": "einen Termin vereinbaren",
    "lernen vs studieren": "lernen oder studieren?",
    "also means therefore": "also heißt deshalb",
    "Sie in formal exchanges": "Sie im formellen Kontext",
    "du/Sie consistency": "du und Sie nicht mischen",
    "formal email opening and closing": "formelle E-Mail",
    "comma before subordinate clause": "Komma vor Nebensatz",
    "comma before relative clause": "Komma vor Relativsatz",
    "comma before um/ohne/anstatt zu": "Komma vor um … zu",
}
CATALOG_LABELS = {pattern_key(key): label for key, label in _CATALOG_LABELS_RAW.items()}
CASE_NAMES_DE = {
    "dative": "Dativ", "dativ": "Dativ", "dat": "Dativ",
    "accusative": "Akkusativ", "akkusativ": "Akkusativ", "akk": "Akkusativ", "acc": "Akkusativ",
    "genitive": "Genitiv", "genitiv": "Genitiv", "gen": "Genitiv",
    "nominative": "Nominativ", "nominativ": "Nominativ", "nom": "Nominativ",
}
GENDERS_DE = {"masculine": "maskulin", "feminine": "feminin", "neuter": "neutral"}
_CASE_WORD = re.compile(r"\b(" + "|".join(CASE_NAMES_DE) + r")\b\.?", re.IGNORECASE)
_LABEL_RULES: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], str]], ...] = (
    (
        re.compile(r"^(?P<noun>.+?) is (?P<gender>masculine|feminine|neuter)$", re.IGNORECASE),
        lambda match: f"{match['noun']} ist {GENDERS_DE[match['gender'].lower()]}",
    ),
    (
        re.compile(r"^(?P<noun>.+?) plural is (?P<form>.+)$", re.IGNORECASE),
        lambda match: f"Plural von {match['noun']}: {match['form']}",
    ),
    (
        re.compile(r"^(?P<verb>.+?) past participle is (?P<form>.+)$", re.IGNORECASE),
        lambda match: f"{match['verb']}: Partizip {match['form']}",
    ),
    (
        re.compile(r"^(?P<verb>.+?) is reflexive$", re.IGNORECASE),
        lambda match: f"{match['verb']} (reflexiv)",
    ),
    (
        re.compile(r"^(?P<conj>\S+) sends (?:the )?finite verb to (?:the )?end$", re.IGNORECASE),
        lambda match: f"{match['conj']}: Verb ans Ende",
    ),
)


def _german_case_names(value: str) -> tuple[str, int]:
    return _CASE_WORD.subn(lambda match: CASE_NAMES_DE[match.group(1).lower()], value)


def display_label(mistake: dict[str, Any]) -> tuple[str, str]:
    """The German name shown to the learner, and its source: custom, catalog, rule, or key."""
    custom = (mistake.get("label") or "").strip()
    if custom:
        return custom, "custom"
    raw = (mistake.get("pattern") or "").strip()
    catalog = CATALOG_LABELS.get(mistake.get("pattern_key") or pattern_key(raw))
    if catalog:
        return catalog, "catalog"
    for rule, build in _LABEL_RULES:
        match = rule.match(raw)
        if match:
            return _german_case_names(build(match))[0], "rule"
    translated, found = _german_case_names(raw)
    return (translated, "rule") if found else (raw, "key")


def clean_label(label: str | None) -> str | None:
    if label is None:
        return None
    value = label.strip()
    if not value:
        raise DeutschLoopError("label must not be empty")
    if len(value) > LABEL_MAX_LENGTH:
        raise DeutschLoopError(f"label must be at most {LABEL_MAX_LENGTH} characters")
    return value


# --------------------------------------------------------------------------- scoring


def review_passes(mistake: dict[str, Any]) -> int:
    return sum(
        1
        for entry in mistake.get("review_history", [])
        if entry.get("result") == "pass" and entry.get("source", "review") == "review"
    )


def correct_total(mistake: dict[str, Any]) -> int:
    return int(mistake.get("correct_uses", 0)) + review_passes(mistake)


def evidence(mistake: dict[str, Any]) -> int:
    """How often the learner had a chance to show progress: graded reviews plus correct uses."""
    return int(mistake.get("review_attempts", 0)) + int(mistake.get("correct_uses", 0))


def example_view(example: dict[str, Any] | None) -> dict[str, Any] | None:
    if not example:
        return None
    return {
        "original": example.get("original"),
        "corrected": example.get("corrected"),
        "seen_at": example.get("seen_at"),
        "seen_at_local": local_iso(example.get("seen_at")),
        "context": example.get("context"),
    }


def accuracy_percent(correct: int, errors: int) -> int:
    """Laplace-smoothed share of correct productions among all tracked productions."""
    return round(100 * (correct + 1) / (correct + errors + 2))


def text_fingerprint(text: str) -> str:
    """Recognize a reused task/answer despite casing, punctuation or whitespace."""
    words = re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())
    return hashlib.sha256(" ".join(words).encode("utf-8")).hexdigest()


def remember_text(mistake: dict[str, Any], field: str, text: str | None) -> None:
    if text and text.strip():
        fingerprint = text_fingerprint(text)
        known = mistake.setdefault(field, [])
        if fingerprint not in known:
            known.append(fingerprint)


def initialize_learning(mistake: dict[str, Any]) -> None:
    """Pin retained evidence, including legacy undo snapshots, without inventing history."""
    examples = mistake.get("examples") or []
    if "first_example" not in mistake:
        first = min(examples, key=lambda row: row.get("seen_at") or "") if examples else None
        mistake["first_example"] = copy.deepcopy(first)
    mistake.setdefault("coaching_history", [])
    mistake.setdefault("helpful_hint", None)
    mistake.setdefault("learning_proof", None)
    mistake.setdefault("seen_prompts", [])
    mistake.setdefault("seen_answers", [])
    for example in examples:
        remember_text(mistake, "seen_answers", example.get("corrected"))
    for entry in mistake.get("review_history", []) + mistake["coaching_history"]:
        remember_text(mistake, "seen_prompts", entry.get("prompt"))
        remember_text(mistake, "seen_answers", entry.get("answer"))
    for entry in mistake.get("correct_use_history", []):
        remember_text(mistake, "seen_answers", entry.get("context"))
    previous = (mistake.get("undo") or {}).get("state")
    if previous:
        initialize_learning(previous)


def learning_event_view(event: dict[str, Any] | None) -> dict[str, Any] | None:
    return {**event, "at_local": local_iso(event.get("at"))} if event else None


def learning_proof_view(proof: dict[str, Any] | None) -> dict[str, Any] | None:
    if not proof:
        return None
    return {key: learning_event_view(proof[key]) for key in ("with_help", "independent")}


def coaching_view(mistake: dict[str, Any]) -> dict[str, Any]:
    return {
        "helpful_hint": learning_event_view(mistake.get("helpful_hint")),
        "last_attempt": learning_event_view((mistake.get("coaching_history") or [None])[-1]),
        "learning_proof": learning_proof_view(mistake.get("learning_proof")),
    }


def independent_use(
    mistake: dict[str, Any], answer: str, moment: datetime, *, source: str, prompt: str | None = None
) -> dict[str, Any] | None:
    """A different, unaided production on a later local day is evidence of transfer."""
    support = mistake.get("helpful_hint")
    if not support or text_fingerprint(answer) in mistake.get("seen_answers", []):
        return None
    supported_at = parse_moment(support["at"])
    last_error = _safe_moment(mistake.get("last_seen"))
    proof = mistake.get("learning_proof")
    if (
        local_date(moment) <= local_date(supported_at)
        or (last_error is not None and last_error > supported_at)
        or (proof and proof["with_help"]["id"] == support["id"])
    ):
        return None
    proof = {
        "with_help": copy.deepcopy(support),
        "independent": {"answer": answer, "prompt": prompt, "source": source, "at": iso(moment)},
    }
    mistake["learning_proof"] = proof
    return learning_proof_view(proof)


def append_coaching(
    mistake: dict[str, Any], *, outcome: str, prompt: str, answer: str,
    strategy: str | None, hint: str | None, moment: datetime,
) -> dict[str, Any]:
    entry = {
        "id": f"c_{uuid.uuid4().hex[:12]}", "at": iso(moment), "outcome": outcome,
        "prompt": prompt, "answer": answer, "strategy": strategy, "hint": hint,
    }
    mistake.setdefault("coaching_history", []).append(entry)
    mistake["coaching_history"] = mistake["coaching_history"][-HISTORY_LIMIT:]
    if outcome == "assisted":
        mistake["helpful_hint"] = copy.deepcopy(entry)
    remember_text(mistake, "seen_prompts", prompt)
    remember_text(mistake, "seen_answers", answer)
    return entry


def compact(mistake: dict[str, Any]) -> dict[str, Any]:
    occurrences = int(mistake.get("occurrences", 0))
    examples = mistake.get("examples") or []
    label, label_source = display_label(mistake)
    return {
        "id": mistake["id"],
        "pattern": mistake["pattern"],
        "label": label,
        "label_source": label_source,
        "category": mistake["category"],
        "status": mistake.get("status"),
        "rule": mistake.get("rule"),
        "occurrences": occurrences,
        "correct_uses": int(mistake.get("correct_uses", 0)),
        "right": correct_total(mistake),
        "accuracy_percent": accuracy_percent(correct_total(mistake), occurrences),
        "new": evidence(mistake) == 0,
        "review_step": int(mistake.get("review_step", 0)),
        "review_steps_total": len(REVIEW_INTERVALS),
        "next_review": mistake.get("next_review"),
        "next_review_local": local_iso(mistake.get("next_review")),
        "last_seen": mistake.get("last_seen"),
        "last_example": example_view(examples[-1]) if examples else None,
        "first_example": example_view(mistake.get("first_example")),
        "coaching": coaching_view(mistake),
    }


def brief(mistake: dict[str, Any]) -> dict[str, Any]:
    """One row of a list: enough to reuse, rename, or schedule a pattern. `compact` adds examples and coaching."""
    occurrences = int(mistake.get("occurrences", 0))
    label, label_source = display_label(mistake)
    return {
        "id": mistake["id"],
        "pattern": mistake["pattern"],
        "label": label,
        "label_source": label_source,
        "category": mistake["category"],
        "status": mistake.get("status"),
        "occurrences": occurrences,
        "right": correct_total(mistake),
        "accuracy_percent": accuracy_percent(correct_total(mistake), occurrences),
        "new": evidence(mistake) == 0,
        "review_step": int(mistake.get("review_step", 0)),
        "review_steps_total": len(REVIEW_INTERVALS),
        "next_review_local": local_iso(mistake.get("next_review")),
    }


def row_view(verbose: bool) -> Callable[[dict[str, Any]], dict[str, Any]]:
    return compact if verbose else brief


# --------------------------------------------------------------------------- word deck


def word_key(term: str) -> str:
    """One card per word. An article or a capital marks a German noun, so `der Morgen` and `morgen`,
    or `das Essen` and `essen`, stay two words; an article, spacing, or umlaut spelling alone does not split one."""
    text = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", term).strip())
    bare = LEADING_ARTICLE.sub("", text)
    noun = bare != text or bare[:1].isupper()
    return ("noun:" if noun else "word:") + spelling(bare)


def word_id_for(key: str) -> str:
    return "w_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def learn_word(
    words: list[dict[str, Any]], *, term: str, meaning: str, source: dict[str, Any], moment: datetime
) -> tuple[dict[str, Any], str]:
    """Add a scene word to the deck, or give a known word one more source without resetting its schedule."""
    key = word_key(term)
    word = next((item for item in words if item.get("key") == key), None)
    if word is not None:
        if not any(item.get("session_id") == source["session_id"] and item.get("turn_id") == source["turn_id"]
                   for item in word.get("sources", [])):
            word["sources"] = (word.get("sources", []) + [source])[-WORD_SOURCE_LIMIT:]
        # `Reservierung` becomes `die Reservierung`; a respelling such as `die Strasse` never replaces `Straße`.
        if LEADING_ARTICLE.sub("", term) == word["term"]:
            word["term"] = term
        remember_text(word, "seen_answers", source.get("example"))
        return word, "known"
    word = {
        "id": word_id_for(key), "key": key, "term": term, "meaning": meaning, "status": "active",
        "review_step": 0, "right": 0, "wrong": 0, "added_at": iso(moment),
        "next_review": iso(moment + timedelta(days=REVIEW_INTERVALS[0])),
        "last_reviewed": None, "mastered_at": None, "sources": [source],
        "review_history": [], "seen_prompts": [], "seen_answers": [],
    }
    # The scene's own sentence cannot count as a new one in a review.
    remember_text(word, "seen_answers", source.get("example"))
    words.append(word)
    return word, "added"


def _is_due(item: dict[str, Any], moment: datetime) -> bool:
    next_review = _safe_moment(item.get("next_review"))
    return item.get("status") == "active" and next_review is not None and next_review <= moment


def word_view(word: dict[str, Any], moment: datetime) -> dict[str, Any]:
    """A word as agents use it: the cue to give, where it was met, earlier tasks, and its schedule."""
    source = (word.get("sources") or [None])[-1]
    return {
        "id": word["id"],
        "term": word["term"],
        "meaning": word["meaning"],
        "status": word.get("status"),
        "due": _is_due(word, moment),
        "review_step": int(word.get("review_step", 0)),
        "review_steps_total": len(REVIEW_INTERVALS),
        "right": int(word.get("right", 0)),
        "wrong": int(word.get("wrong", 0)),
        "next_review_local": local_iso(word.get("next_review")),
        "source": {"scenario": source.get("scenario"), "example": source.get("example"),
                   "at_local": local_iso(source.get("at"))} if source else None,
        "recent_prompts": [entry["prompt"] for entry in word.get("review_history", [])[-3:]],
    }


def word_row(word: dict[str, Any], moment: datetime) -> dict[str, Any]:
    """One line of the deck listing: enough to find a word's ID and schedule."""
    return {
        "id": word["id"],
        "term": word["term"],
        "meaning": word["meaning"],
        "status": word.get("status"),
        "due": _is_due(word, moment),
        "review_step": int(word.get("review_step", 0)),
        "next_review_local": local_iso(word.get("next_review")),
    }


def word_output(word: dict[str, Any], moment: datetime, verbose: bool) -> dict[str, Any]:
    if not verbose:
        return word_view(word, moment)
    view = {key: value for key, value in word.items() if key not in {"undo", "seen_prompts", "seen_answers"}}
    if word.get("undo"):
        view["undo_available"] = {"action": word["undo"].get("action"), "at": word["undo"].get("at")}
    return {**view, "due": _is_due(word, moment), "next_review_local": local_iso(word.get("next_review"))}


def vocabulary_overview(words: list[dict[str, Any]], moment: datetime) -> dict[str, Any]:
    active = [word for word in words if word.get("status") == "active"]
    upcoming = sorted(
        value for value in (_safe_moment(word.get("next_review")) for word in active) if value is not None and value > moment
    )
    return {
        "total": len(words),
        "active": len(active),
        "mastered": sum(word.get("status") == "mastered" for word in words),
        "due_now": sum(_is_due(word, moment) for word in active),
        "next_local": to_local(upcoming[0]).isoformat() if upcoming else None,
    }


def errors_between(mistake: dict[str, Any], start: datetime, end: datetime) -> int:
    count = 0
    for example in mistake.get("examples", []):
        seen = _safe_moment(example.get("seen_at"))
        if seen is not None and start < seen <= end:
            count += 1
    return count


# Validator results from the removed LanguageTool check. They are dropped when state is read,
# so the next write takes them off the disk too.
LEGACY_FIELDS = frozenset({"verification_history", "verification_status"})


def drop_legacy_fields(value: Any) -> Any:
    if isinstance(value, dict):
        for key in LEGACY_FIELDS & value.keys():
            del value[key]
        for item in value.values():
            drop_legacy_fields(item)
    elif isinstance(value, list):
        for item in value:
            drop_legacy_fields(item)
    return value


def public(mistake: dict[str, Any]) -> dict[str, Any]:
    """The pattern as shown to callers: the undo snapshot is summarized, not dumped."""
    view = {key: value for key, value in mistake.items() if key not in {"undo", "seen_prompts", "seen_answers"}}
    view["label"], view["label_source"] = display_label(mistake)
    view["coaching"] = coaching_view(mistake)
    snapshot = mistake.get("undo")
    if snapshot:
        view["undo_available"] = {"action": snapshot.get("action"), "at": snapshot.get("at")}
    return view


def _snapshot(mistake: dict[str, Any], action: str, moment: datetime) -> None:
    """Keep one level of undo: the pattern exactly as it was before this change."""
    state = copy.deepcopy({key: value for key, value in mistake.items() if key != "undo"})
    mistake["undo"] = {"action": action, "at": iso(moment), "state": state}


def profile_view(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": profile.get("name"),
        "level": profile.get("level"),
        "native_language": profile.get("native_language"),
        "goal": profile.get("goal"),
        "explanation_language": profile.get("explanation_language"),
        "starting_point": profile.get("starting_point"),
    }


def onboarding_view(profile: dict[str, Any], *, has_activity: bool) -> dict[str, Any]:
    """Resume the first encounter without requiring a name or a CEFR self-assessment."""
    if profile.get("onboarding_completed_at") or has_activity:
        stage = "complete"
    elif profile.get("starting_point") or profile.get("level") in CEFR_LEVELS:
        stage = "first_practice"
    elif profile.get("welcome_shown_at"):
        stage = "choose_start"
    else:
        stage = "welcome"
    return {
        "stage": stage,
        "explanation_language": profile.get("explanation_language") or profile.get("native_language"),
        "starting_point": profile.get("starting_point"),
        "welcome_shown_at_local": local_iso(profile.get("welcome_shown_at")),
        "completed_at_local": local_iso(profile.get("onboarding_completed_at")),
    }


def session_timing(session: dict[str, Any], moment: datetime) -> dict[str, Any]:
    ended = _safe_moment(session.get("ended_at"))
    elapsed = max(0, int(((ended or moment) - parse_moment(session["started_at"])).total_seconds()))
    turns = sum(turn["speaker"] == "learner" for turn in session.get("utterances", []))
    if not session.get("utterances"):
        turns = session.get("turns") or 0
    return {
        "session_id": session["id"], "elapsed_seconds": elapsed, "learner_turns": turns,
        "started_at_local": local_iso(session.get("started_at")), "ended_at_local": local_iso(session.get("ended_at")),
        "target_seconds": session.get("target_seconds", 300),
        "should_close": session.get("status") == "active" and elapsed >= session.get("target_seconds", 300),
    }


def is_scene_end_request(text: str) -> bool:
    """Recognize unambiguous standalone controls, not words inside a learner sentence."""
    folded = unicodedata.normalize("NFKC", text).casefold().replace("\u0307", "")
    command = " ".join(re.findall(r"\w+", folded))
    return command in {
        "bitir", "bitirelim", "konuşmayı bitir", "konusmayi bitir", "sohbeti bitir",
        "rollenspiel beenden", "szene beenden", "stop roleplay", "end roleplay",
    }


def session_debrief(
    session: dict[str, Any], mistakes: list[dict[str, Any]], words: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Report linked, confirmed errors in this scene, not lifetime totals or invented diagnoses.

    Each scene word carries `review`: `active` while its card is still being reviewed, `mastered`
    when an earlier scene already took it to the top of the ladder, or null without a card.
    """
    cards = {word.get("key"): word for word in words or []}
    vocabulary = [
        {**item, "review": (cards.get(word_key(item["term"])) or {}).get("status")}
        for item in session.get("vocabulary", [])
    ]
    patterns = {item["id"]: item for item in mistakes}
    groups: dict[str, dict[str, Any]] = {}
    seen = set()
    for entry in session.get("feedback", []):
        identifier = entry["mistake_id"]
        identity = (identifier, entry["turn_id"], entry["original"])
        if identifier not in patterns or identity in seen:
            continue
        seen.add(identity)
        pattern = patterns[identifier]
        group = groups.setdefault(identifier, {
            "mistake_id": identifier, "label": display_label(pattern)[0], "rule": pattern["rule"],
            "category": pattern["category"], "session_occurrences": 0,
            "previously_tracked": identifier in session.get("known_pattern_ids", []),
            "example": entry,
        })
        group["session_occurrences"] += 1
    ranked = sorted(groups.values(), key=lambda item: (-int(item["previously_tracked"]), -item["session_occurrences"], item["label"]))
    return {
        "scenario": session["scenario"], "duration_seconds": session.get("duration_seconds"),
        "duration_source": session.get("duration_source", "unknown"), "learner_turns": session.get("turns") or 0,
        "confirmed_patterns": len(ranked), "confirmed_occurrences": sum(item["session_occurrences"] for item in ranked),
        "corrections": ranked[:3], "recurring": [item for item in ranked if item["previously_tracked"] or item["session_occurrences"] > 1][:3],
        "vocabulary": vocabulary,
    }


def mission_view(mission: dict[str, Any], moment: datetime, sessions: list[dict[str, Any]]) -> dict[str, Any]:
    index = int(mission.get("step_index", 0))
    steps = mission["steps"]
    attempts = mission.get("attempts") or []
    assessed = {attempt["session_id"] for attempt in attempts}
    pending = [session for session in sessions if session.get("mission_id") == mission["id"] and session["id"] not in assessed]
    session = max(pending, key=lambda item: item["started_at"]) if pending else None
    status = mission["status"]
    next_action = {"active": "start_scene", "completed": "mission_complete", "cancelled": "mission_cancelled"}[status]
    if status == "active" and session:
        next_action = {"active": "resume_scene", "debriefing": "present_debrief", "complete": "assess_mission"}[session["status"]]
    deadline = mission.get("deadline")
    remaining = (date.fromisoformat(deadline) - local_date(moment)).days if deadline else None
    last = attempts[-1] if attempts else None
    return {"id": mission["id"], "goal": mission["goal"], "scenario": mission["scenario"],
            "scenario_title": SCENARIOS[mission["scenario"]]["title"], "status": status,
            "deadline": deadline, "days_remaining": remaining, "overdue": status == "active" and remaining is not None and remaining < 0,
            "completed_steps": index, "total_steps": len(steps), "attempts": len(attempts),
            "current_step": {key: steps[index][key] for key in ("id", "label", "goal", "criteria", "difficulty")} if index < len(steps) else None,
            "steps": [{"id": step["id"], "label": step["label"], "goal": step["goal"],
                       "status": "completed" if number < index else "current" if number == index and status == "active" else "upcoming"}
                      for number, step in enumerate(steps)],
            "last_attempt": {**copy.deepcopy(last), "at_local": local_iso(last["at"])} if last else None,
            "pending_session_id": session["id"] if session and status == "active" else None,
            "next_action": next_action, "completed_at_local": local_iso(mission.get("completed_at")),
            "completion_basis": "Completed communication-practice steps; not a proficiency or readiness certificate."}


def _event_moments(
    mistakes: list[dict[str, Any]], sessions: list[dict[str, Any]], profile: dict[str, Any] | None = None,
    words: list[dict[str, Any]] | None = None,
) -> list[datetime]:
    stamps: list[str | None] = []
    # A first German production is activity even when it contains no mistake.
    # Merely viewing the welcome or choosing a starting point is not practice.
    if profile:
        stamps.append(profile.get("onboarding_completed_at"))
    for mistake in mistakes:
        stamps.extend(example.get("seen_at") for example in mistake.get("examples", []))
        stamps.extend(entry.get("reviewed_at") for entry in mistake.get("review_history", []))
        stamps.extend(entry.get("observed_at") for entry in mistake.get("correct_use_history", []))
        stamps.extend(entry.get("at") for entry in mistake.get("coaching_history", []))
    for session in sessions:
        stamps.append(session.get("started_at"))
        stamps.append(session.get("ended_at"))
        stamps.extend(turn.get("at") for turn in session.get("utterances", []))
    for word in words or []:
        stamps.extend(entry.get("reviewed_at") for entry in word.get("review_history", []))
    moments = []
    for stamp in stamps:
        parsed = _safe_moment(stamp)
        if parsed is not None:
            moments.append(parsed)
    return moments


_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue"})


def spelling(text: str) -> str:
    """One spelling for comparisons: für/fuer and daß/dass match (casefold turns ß into ss)."""
    return text.casefold().translate(_UMLAUTS)


def differs_only_in_spelling(left: str, right: str) -> bool:
    """Keys that only add words or respell one are candidates for one root cause; a swapped word is not."""
    before, after = left.split(), right.split()
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace":
            continue
        old, new = spelling(" ".join(before[i1:i2])), spelling(" ".join(after[j1:j2]))
        if old != new and difflib.SequenceMatcher(None, old, new, autojunk=False).ratio() < SPELLING_VARIANT_THRESHOLD:
            return False
    return True


def similar_patterns(mistakes: list[dict[str, Any]], key: str, *, exclude_id: str | None = None) -> list[dict[str, Any]]:
    target = spelling(compact_key(key))
    hits = []
    for mistake in mistakes:
        if mistake.get("id") == exclude_id:
            continue
        other = mistake.get("pattern_key", "")
        ratio = difflib.SequenceMatcher(None, target, spelling(compact_key(other)), autojunk=False).ratio()
        if ratio >= SIMILARITY_HINT_THRESHOLD and differs_only_in_spelling(key, other):
            hits.append(
                {
                    "id": mistake["id"],
                    "pattern": mistake["pattern"],
                    "category": mistake["category"],
                    "similarity": round(ratio, 3),
                }
            )
    hits.sort(key=lambda item: (-item["similarity"], item["pattern"]))
    return hits[:3]


# --------------------------------------------------------------------------- storage


def standard_home() -> Path:
    """~/.deutschloop, or ~/.deutschdna for a learner who started before the rename and has no new folder."""
    home, legacy = Path.home() / ".deutschloop", Path.home() / ".deutschdna"
    return legacy if legacy.is_dir() and not home.exists() else home


def default_home(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    configured = _setting("HOME")
    if configured:
        return Path(configured).expanduser()
    return standard_home()


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeutschLoopError(f"Could not read valid JSON from {path}") from exc
    if not isinstance(value, dict):
        raise DeutschLoopError(f"Expected a JSON object in {path}")
    return value


@contextlib.contextmanager
def state_lock(home: Path, *, timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    """Serialize whole commands on one state directory; the OS releases the lock if a process dies.

    Every command reads, changes, and rewrites a JSON document. Without this lock, two
    parallel `record` calls both read the old document and the later write drops the
    other's pattern while both report success.
    """
    try:
        home.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(home / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise _state_not_writable(home, exc) from exc
    deadline = time.monotonic() + timeout
    locked = False
    try:
        while not locked:
            try:
                if fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                locked = True
            except OSError:
                if time.monotonic() >= deadline:
                    raise DeutschLoopError(f"Another DeutschLoop command kept {home} busy for {timeout:g}s; try again") from None
                time.sleep(0.02)
        yield
    finally:
        if locked:
            try:
                if fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                else:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        os.close(descriptor)


def _replace_file(source: Path, target: Path) -> None:
    """os.replace, retried briefly: on Windows a scanner or sync client may hold the target for a moment."""
    for attempt in range(6):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.05 * (attempt + 1))


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DeutschLoopError(f"Could not create the state directory {path.parent}: {exc}") from exc
    temporary_path = path.parent / f"{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary_path.open("x", encoding="utf-8", newline="\n") as temporary:
            json.dump(value, temporary, ensure_ascii=False, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        _replace_file(temporary_path, path)
    except Exception as exc:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        if isinstance(exc, DeutschLoopError):
            raise
        if isinstance(exc, OSError):
            raise DeutschLoopError(f"Could not write state file {path}: {exc}") from exc
        raise


def _migrate_mistakes(document: dict[str, Any]) -> dict[str, Any]:
    """Upgrade old state in memory; the next write persists it. IDs are kept."""
    try:
        version = int(document.get("schema_version") or 1)
    except (TypeError, ValueError):
        version = 1
    if version >= SCHEMA_VERSION:
        return document
    for mistake in document["mistakes"]:
        if isinstance(mistake.get("pattern"), str):
            mistake["pattern_key"] = pattern_key(mistake["pattern"]) or mistake.get("pattern_key", "")
        mistake.setdefault("correct_uses", 0)
        mistake.setdefault("last_correct_use", None)
        mistake.setdefault("mastered_at", None)
        for field in ("examples", "review_history", "correct_use_history", "aliases", "merged_from"):
            mistake.setdefault(field, [])
        initialize_learning(mistake)
    document["schema_version"] = SCHEMA_VERSION
    return document


class StateStore:
    def __init__(self, home: Path):
        self.home = home
        self.profile_path = home / "profile.json"
        self.mistakes_path = home / "mistakes.json"
        self.sessions_path = home / "sessions.json"
        self.vocabulary_path = home / "vocabulary.json"
        self.missions_path = home / "missions.json"

    # ---- documents

    def ensure(self) -> None:
        try:
            self.home.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise _state_not_writable(self.home, exc) from exc
        if not self.profile_path.exists():
            _atomic_write(
                self.profile_path,
                {
                    "schema_version": SCHEMA_VERSION,
                    "name": None,
                    "native_language": None,
                    "level": "unspecified",
                    "created_at": iso(utc_now()),
                    "updated_at": iso(utc_now()),
                },
            )
        if not self.mistakes_path.exists():
            _atomic_write(self.mistakes_path, {"schema_version": SCHEMA_VERSION, "mistakes": []})
        if not self.sessions_path.exists():
            _atomic_write(self.sessions_path, {"schema_version": SCHEMA_VERSION, "sessions": []})
        if not self.vocabulary_path.exists():
            _atomic_write(self.vocabulary_path, {"schema_version": VOCABULARY_SCHEMA_VERSION, "words": self._words_from_scenes()})

    def _words_from_scenes(self) -> list[dict[str, Any]]:
        """Words saved in scenes before the deck existed start their reviews now instead of being lost."""
        words: list[dict[str, Any]] = []
        for session in _read_json(self.sessions_path, {"sessions": []}).get("sessions", []):
            met = _safe_moment(session.get("ended_at")) or _safe_moment(session.get("started_at")) or utc_now()
            for item in session.get("vocabulary", []):
                source = {"session_id": session.get("id"), "scenario": session.get("scenario"), "turn_id": item.get("turn_id"),
                          "surface": item.get("surface"), "example": item.get("example"), "at": iso(met)}
                learn_word(words, term=item["term"], meaning=item["meaning"], source=source, moment=met)
        return words

    def _vocabulary_document(self) -> dict[str, Any]:
        self.ensure()
        document = _read_json(self.vocabulary_path, {"schema_version": VOCABULARY_SCHEMA_VERSION, "words": []})
        if not isinstance(document.get("words"), list):
            raise DeutschLoopError(f"Expected a words list in {self.vocabulary_path}")
        return document

    def _remove_scene_words(self, key: str, session_id: str | None = None) -> None:
        """Take a withdrawn word out of scene reports, in one scene or in all of them."""
        document = self._session_document()
        changed = False
        for session in document["sessions"]:
            if session_id is not None and session.get("id") != session_id:
                continue
            vocabulary = session.get("vocabulary", [])
            kept = [item for item in vocabulary if word_key(item["term"]) != key]
            if len(kept) != len(vocabulary):
                session["vocabulary"] = kept
                changed = True
        if changed:
            _atomic_write(self.sessions_path, document)

    def _profile(self) -> dict[str, Any]:
        self.ensure()
        return _read_json(self.profile_path, {})

    def _mistake_document(self) -> dict[str, Any]:
        self.ensure()
        document = _read_json(self.mistakes_path, {"schema_version": SCHEMA_VERSION, "mistakes": []})
        if not isinstance(document.get("mistakes"), list):
            raise DeutschLoopError(f"Expected a mistakes list in {self.mistakes_path}")
        return _migrate_mistakes(drop_legacy_fields(document))

    def _session_document(self) -> dict[str, Any]:
        self.ensure()
        document = _read_json(self.sessions_path, {"schema_version": SCHEMA_VERSION, "sessions": []})
        if not isinstance(document.get("sessions"), list):
            raise DeutschLoopError(f"Expected a sessions list in {self.sessions_path}")
        return drop_legacy_fields(document)

    def _mission_document(self) -> dict[str, Any]:
        document = _read_json(self.missions_path, {"schema_version": MISSION_SCHEMA_VERSION, "missions": []})
        if not isinstance(document.get("missions"), list):
            raise DeutschLoopError(f"Expected a missions list in {self.missions_path}")
        return document

    @staticmethod
    def _require_session(document: dict[str, Any], identifier: str) -> dict[str, Any]:
        session = next((item for item in document["sessions"] if item.get("id") == identifier), None)
        if session is None:
            raise DeutschLoopError(f"Unknown session ID: {identifier}")
        return session

    def _session_feedback(self, session_id: str, mistake: dict[str, Any], example: dict[str, Any]) -> None:
        """Keep session evidence after the rolling pattern history expires; repairable by undo/forget."""
        document = self._session_document()
        session = self._require_session(document, session_id)
        feedback = session.setdefault("feedback", [])
        if not any(item["event_id"] == example["event_id"] and item["mistake_id"] == mistake["id"] for item in feedback):
            feedback.append({**copy.deepcopy(example), "mistake_id": mistake["id"],
                             "label": display_label(mistake)[0], "category": mistake["category"], "rule": mistake["rule"]})
            _atomic_write(self.sessions_path, document)

    def _remove_session_feedback(self, mistake_id: str, event_id: str) -> None:
        document = self._session_document()
        changed = False
        for session in document["sessions"]:
            feedback = session.get("feedback", [])
            kept = [item for item in feedback if not (item["mistake_id"] == mistake_id and item["event_id"] == event_id)]
            if len(kept) != len(feedback):
                session["feedback"] = kept
                changed = True
        if changed:
            _atomic_write(self.sessions_path, document)

    @staticmethod
    def _find(mistakes: list[dict[str, Any]], identifier: str) -> dict[str, Any] | None:
        return next((item for item in mistakes if item.get("id") == identifier), None)

    def _require(self, mistakes: list[dict[str, Any]], identifier: str) -> dict[str, Any]:
        mistake = self._find(mistakes, identifier)
        if not mistake:
            raise DeutschLoopError(f"Unknown mistake ID: {identifier}")
        return mistake

    @staticmethod
    def _resolve(
        mistakes: list[dict[str, Any]], category: str, pattern: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        key = pattern_key(pattern)
        if not key:
            raise DeutschLoopError("pattern must contain letters or digits")
        exact = StateStore._find(mistakes, mistake_id_for(category, key))
        if exact:
            return exact, "id"
        for mistake in mistakes:
            if mistake.get("pattern_key") == key:
                return mistake, "pattern_key"
        for mistake in mistakes:
            for alias in mistake.get("aliases", []):
                if alias.get("pattern_key") == key:
                    return mistake, "alias"
        return None, None

    @staticmethod
    def _rewrite_session_ids(document: dict[str, Any], old_id: str, new_id: str | None) -> list[dict[str, Any]]:
        """Point session references at new_id (or drop them); return a journal that can reverse a merge."""
        journal = []
        for session in document["sessions"]:
            change: dict[str, Any] = {}
            if session.get("focus_id") == old_id:
                session["focus_id"] = new_id
                change["focus_id"] = True
            for field in ("known_pattern_ids", "mistake_ids", "mission_focus_ids"):
                values = session.get(field) or []
                if old_id in values:
                    change[field] = list(values)
                    session[field] = list(dict.fromkeys(item for item in (new_id if value == old_id else value for value in values) if item))
            moved = [item["event_id"] for item in session.get("feedback", []) if item["mistake_id"] == old_id]
            if moved:
                session["feedback"] = [
                    {**item, "mistake_id": new_id if item["mistake_id"] == old_id else item["mistake_id"]}
                    for item in session["feedback"] if item["mistake_id"] != old_id or new_id
                ]
                change["feedback_event_ids"] = moved
            if change:
                journal.append({"session_id": session.get("id"), **change})
        return journal

    @staticmethod
    def _put_back(values: list[str], before: list[str], source_id: str, target_id: str, *, keep_target: bool) -> list[str]:
        """Undo one ID replacement in a reference list, keeping whatever else changed since the merge."""
        result = [value for value in values if value != target_id or keep_target]
        if source_id not in result:
            position = before.index(source_id) if source_id in before else len(result)
            result.insert(min(position, len(result)), source_id)
        return result

    @staticmethod
    def _restore_session_ids(document: dict[str, Any], journal: list[dict[str, Any]], source_id: str, target_id: str) -> None:
        """Reverse a merge's reference changes ID by ID, so later scene changes and other merges survive."""
        for change in journal:
            session = next((item for item in document["sessions"] if item.get("id") == change["session_id"]), None)
            if session is None:
                continue
            if change.get("focus_id") and session.get("focus_id") == target_id:
                session["focus_id"] = source_id
            moved = set(change.get("feedback_event_ids", []))
            restored = False
            for item in session.get("feedback", []):
                if item["mistake_id"] == target_id and item["event_id"] in moved:
                    item["mistake_id"] = source_id
                    restored = True
            linked = {item["mistake_id"] for item in session.get("feedback", [])}
            if "known_pattern_ids" in change:
                before = change["known_pattern_ids"]
                session["known_pattern_ids"] = StateStore._put_back(
                    session.get("known_pattern_ids") or [], before, source_id, target_id, keep_target=target_id in before
                )
            if "mission_focus_ids" in change:
                before = change["mission_focus_ids"]
                session["mission_focus_ids"] = StateStore._put_back(
                    session.get("mission_focus_ids") or [], before, source_id, target_id, keep_target=target_id in before)
            # A scene finished after the merge listed the target for the source's feedback.
            if "mistake_ids" in change or (restored and session.get("mistake_ids")):
                before = change.get("mistake_ids") or []
                session["mistake_ids"] = StateStore._put_back(
                    session.get("mistake_ids") or [], before, source_id, target_id,
                    keep_target=target_id in before or target_id in linked,
                )

    def _replace_session_ids(self, old_id: str, new_id: str | None) -> None:
        document = self._session_document()
        if self._rewrite_session_ids(document, old_id, new_id):
            _atomic_write(self.sessions_path, document)

    # ---- profile

    def init_profile(
        self,
        *,
        name: str | None = None,
        native_language: str | None = None,
        level: str | None = None,
        goal: str | None = None,
        explanation_language: str | None = None,
        starting_point: str | None = None,
        welcome_shown: bool = False,
        onboarding_complete: bool = False,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        if starting_point is not None and starting_point not in STARTING_POINTS:
            raise DeutschLoopError("starting_point must be beginner, some, comfortable, or unsure")
        moment = at or utc_now()
        profile_was_missing = not self.profile_path.exists()
        self.ensure()
        profile = _read_json(self.profile_path, {})
        if profile_was_missing:
            profile["created_at"] = iso(moment)
        for key, value in (
            ("name", name), ("native_language", native_language), ("level", level), ("goal", goal),
            ("explanation_language", explanation_language), ("starting_point", starting_point),
        ):
            if value is not None:
                profile[key] = value
        if welcome_shown and not profile.get("welcome_shown_at"):
            profile["welcome_shown_at"] = iso(moment)
        if onboarding_complete and not profile.get("onboarding_completed_at"):
            profile["onboarding_completed_at"] = iso(moment)
        profile["updated_at"] = iso(moment)
        _atomic_write(self.profile_path, profile)
        return profile

    def mark_profile_shown(self, *, at: datetime | None = None) -> None:
        """Remember when the learner last saw the full profile card, for the weekly Wochenbilanz."""
        profile = self._profile()
        profile["last_full_profile_at"] = iso(at or utc_now())
        _atomic_write(self.profile_path, profile)

    # ---- recording

    def record(
        self,
        *,
        original: str,
        corrected: str,
        category: str | None = None,
        pattern: str | None = None,
        rule: str | None = None,
        mistake_id: str | None = None,
        context: str | None = None,
        at: datetime | None = None,
        event_id: str | None = None,
        label: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
    ) -> tuple[dict[str, Any], str, dict[str, Any]]:
        label = clean_label(label)
        if not original.strip() or not corrected.strip():
            raise DeutschLoopError("original and corrected must not be empty")
        moment = at or utc_now()
        if bool(session_id) != bool(turn_id):
            raise DeutschLoopError("Session feedback requires both --session-id and --turn-id")
        session = None
        if session_id:
            session = self._require_session(self._session_document(), session_id)
            if session.get("status") != "debriefing":
                raise DeutschLoopError("Stop the scene before recording feedback; only debriefing sessions accept corrections")
            turn = next((item for item in session.get("utterances", []) if item["id"] == turn_id), None)
            if not turn or turn["speaker"] != "learner" or original.strip() not in turn["text"]:
                raise DeutschLoopError("The original must be an actual sentence from the referenced learner turn")
            moment = parse_moment(turn["at"])
        document = self._mistake_document()
        mistakes = document["mistakes"]
        first_production = not mistakes
        resolved_by: str | None = None

        if mistake_id:
            existing: dict[str, Any] | None = self._require(mistakes, mistake_id)
            resolved_by = "mistake_id"
        else:
            if not (category and pattern and rule) or not pattern.strip() or not rule.strip():
                raise DeutschLoopError("Provide --mistake-id, or --category, --pattern, and --rule")
            if category not in CATEGORIES:
                raise DeutschLoopError(f"Unknown category '{category}'. Choose from: {', '.join(CATEGORY_ORDER)}")
            existing, resolved_by = self._resolve(mistakes, category, pattern)

        if session and session.get("input_mode") == "transcript":
            error_category = existing["category"] if existing else category
            if error_category in {"spelling", "punctuation"}:
                raise DeutschLoopError("A speech transcript cannot establish learner spelling or punctuation errors")
        effective_event_id = event_id or auto_event_id(original, corrected)
        if session is not None:
            identity = existing["id"] if existing else mistake_id_for(category, pattern_key(pattern))
            effective_event_id = f"{session_id}:{turn_id}:{identity}:{auto_event_id(original, corrected)}"
            if any(item["mistake_id"] == identity and item["turn_id"] == turn_id and item["original"] == original.strip()
                   for item in session.get("feedback", [])):
                return existing, "duplicate", {"resolved_by": resolved_by}
        if existing:
            for example in existing.get("examples", []):
                if example.get("event_id") != effective_event_id:
                    continue
                if event_id or session_id or within(example.get("seen_at"), moment, DUPLICATE_RECORD_WINDOW):
                    if session_id:
                        self._session_feedback(session_id, existing, example)
                    return existing, "duplicate", {"resolved_by": resolved_by}

        example = {
            "original": original.strip(),
            "corrected": corrected.strip(),
            "context": context,
            "seen_at": iso(moment),
            "event_id": effective_event_id,
        }
        if session_id:
            example.update({"session_id": session_id, "turn_id": turn_id})
        extra: dict[str, Any] = {"resolved_by": resolved_by}

        if existing:
            earlier = existing.get("examples") or []
            extra["previous"] = {
                "last_seen": existing.get("last_seen"),
                "review_step": int(existing.get("review_step", 0)),
                "status": existing.get("status"),
                "occurrences": int(existing.get("occurrences", 0)),
                "first_example": example_view(existing.get("first_example")),
                "first_example_is_original": bool(existing.get("first_example"))
                and existing["first_example"].get("seen_at") == existing.get("first_seen"),
                "last_example": example_view(earlier[-1] if earlier else None),
            }
            was_mastered = existing.get("status") == "mastered"
            _snapshot(existing, "record", moment)
            existing["occurrences"] = int(existing.get("occurrences", 1)) + 1
            existing["last_seen"] = iso(moment)
            if rule and rule.strip():
                existing["rule"] = rule.strip()
            if label:
                existing["label"] = label
            existing["status"] = "active"
            existing["review_step"] = 0
            existing["consecutive_successes"] = 0
            existing["mastery_score"] = 0.0
            existing["next_review"] = iso(moment + timedelta(days=REVIEW_INTERVALS[0]))
            if was_mastered:
                existing["reactivated_at"] = iso(moment)
                existing["previously_mastered_at"] = existing.get("mastered_at")
                existing["mastered_at"] = None
            existing.setdefault("examples", []).append(example)
            existing["examples"] = existing["examples"][-EXAMPLE_LIMIT:]
            status = "updated"
            mistake = existing
        else:
            assert category and pattern and rule
            key = pattern_key(pattern)
            mistake = {
                "id": mistake_id_for(category, key),
                "pattern": pattern.strip(),
                "pattern_key": key,
                "category": category,
                "rule": rule.strip(),
                "status": "active",
                "occurrences": 1,
                "correct_uses": 0,
                "review_step": 0,
                "review_attempts": 0,
                "review_failures": 0,
                "consecutive_successes": 0,
                "mastery_score": 0.0,
                "first_seen": iso(moment),
                "last_seen": iso(moment),
                "last_reviewed": None,
                "last_correct_use": None,
                "next_review": iso(moment + timedelta(days=REVIEW_INTERVALS[0])),
                "mastered_at": None,
                "examples": [example],
                "review_history": [],
                "correct_use_history": [],
                "aliases": [],
                "merged_from": [],
                "undo": {"action": "record", "at": iso(moment), "state": None},
                "label": label,
            }
            mistakes.append(mistake)
            initialize_learning(mistake)
            status = "recorded"
            extra["similar_patterns"] = similar_patterns(mistakes, key, exclude_id=mistake["id"])

        if mistake.get("first_example") is None:
            mistake["first_example"] = copy.deepcopy(example)
        remember_text(mistake, "seen_answers", corrected)
        extra["recent_occurrences"] = sum(
            1 for item in mistake.get("examples", []) if within(item.get("seen_at"), moment, timedelta(days=RECENT_DAYS))
        )
        _atomic_write(self.mistakes_path, document)
        if session_id:
            self._session_feedback(session_id, mistake, example)
        if first_production:
            extra["onboarding_completed"] = self._complete_onboarding(moment)
        return mistake, status, extra

    def _complete_onboarding(self, moment: datetime) -> bool:
        """A new learner's first recorded sentence is their first practice, as `init --onboarding-complete` records it."""
        profile = self._profile()
        if profile.get("onboarding_completed_at"):
            return False
        profile["onboarding_completed_at"] = iso(moment)
        profile["updated_at"] = iso(moment)
        _atomic_write(self.profile_path, profile)
        return True

    def observe(
        self,
        identifiers: list[str],
        *,
        context: str | None = None,
        at: datetime | None = None,
    ) -> list[dict[str, Any]]:
        if not context or not context.strip():
            raise DeutschLoopError("Provide the learner's unprompted sentence with --context")
        context = context.strip()
        moment = at or utc_now()
        document = self._mistake_document()
        mistakes = document["mistakes"]
        results = []
        for identifier in dict.fromkeys(identifiers):
            mistake = self._require(mistakes, identifier)
            history = mistake.setdefault("correct_use_history", [])
            duplicate = any(
                entry.get("context") == context and within(entry.get("observed_at"), moment, DUPLICATE_EVENT_WINDOW)
                for entry in history
            )
            if duplicate:
                results.append({"id": mistake["id"], "pattern": mistake["pattern"], "status": "duplicate", "learning_proof": None})
                continue
            if text_fingerprint(context) in mistake.get("seen_answers", []):
                # An earlier answer, correction, or use of this pattern is not new evidence, even in a later session.
                results.append({"id": mistake["id"], "pattern": mistake["pattern"], "status": "seen", "learning_proof": None})
                continue
            _snapshot(mistake, "observe", moment)
            proof = independent_use(mistake, context, moment, source="spontaneous")
            mistake["correct_uses"] = int(mistake.get("correct_uses", 0)) + 1
            history.append({"observed_at": iso(moment), "context": context})
            mistake["correct_use_history"] = history[-HISTORY_LIMIT:]
            mistake["last_correct_use"] = iso(moment)
            status = "observed"
            next_review = _safe_moment(mistake.get("next_review"))
            if mistake.get("status") == "active" and next_review is not None and next_review <= moment:
                self._apply_pass(mistake, moment, source="observed", answer=context)
                status = "observed_and_advanced"
            results.append(
                {
                    "id": mistake["id"],
                    "pattern": mistake["pattern"],
                    "status": status,
                    "correct_uses": mistake["correct_uses"],
                    "review_step": mistake.get("review_step", 0),
                    "next_review": mistake.get("next_review"),
                    "mastered": mistake.get("status") == "mastered",
                    "last_mistake": example_view((mistake.get("examples") or [None])[-1]),
                    "learning_proof": proof,
                }
            )
            remember_text(mistake, "seen_answers", context)
        _atomic_write(self.mistakes_path, document)
        return results

    def coach(
        self, identifier: str, *, outcome: str, prompt: str, answer: str,
        strategy: str | None = None, hint: str | None = None, at: datetime | None = None,
    ) -> dict[str, Any]:
        """Remember how an exercise went; guided practice never changes the review ladder."""
        if outcome not in {"independent", "assisted", "shown", "miss"}:
            raise DeutschLoopError("outcome must be independent, assisted, shown, or miss")
        prompt, answer = prompt.strip(), answer.strip()
        strategy, hint = (strategy or "").strip() or None, (hint or "").strip() or None
        if not prompt or not answer:
            raise DeutschLoopError("Provide the actual --prompt and --answer")
        if bool(strategy) != bool(hint) or (outcome in {"assisted", "shown"} and not hint):
            raise DeutschLoopError("Record both --strategy and the actual --hint for supported practice")
        if outcome == "independent" and hint:
            raise DeutschLoopError("An independent answer cannot include a hint; use assisted or shown")
        moment = at or utc_now()
        document = self._mistake_document()
        mistake = self._require(document["mistakes"], identifier)
        fields = {"outcome": outcome, "prompt": prompt, "answer": answer, "strategy": strategy, "hint": hint}
        if any(all(entry.get(key) == value for key, value in fields.items())
               and within(entry.get("at"), moment, DUPLICATE_EVENT_WINDOW)
               for entry in mistake.get("coaching_history", [])):
            return {"status": "duplicate", "mistake": mistake, "learning_proof": None}
        if outcome == "independent" and (
            text_fingerprint(prompt) in mistake.get("seen_prompts", [])
            or text_fingerprint(answer) in mistake.get("seen_answers", [])
        ):
            raise DeutschLoopError("Independent practice needs a new situation and answer; copied corrections are shown")
        _snapshot(mistake, "coach", moment)
        proof = independent_use(mistake, answer, moment, source="practice", prompt=prompt) if outcome == "independent" else None
        entry = append_coaching(mistake, **fields, moment=moment)
        _atomic_write(self.mistakes_path, document)
        return {"status": "coached", "attempt": learning_event_view(entry), "mistake": mistake, "learning_proof": proof}

    # ---- reviewing

    def due(self, *, at: datetime | None = None, limit: int = 5) -> list[dict[str, Any]]:
        moment = at or utc_now()
        document = self._mistake_document()
        due_items = []
        for mistake in document["mistakes"]:
            next_review = mistake.get("next_review")
            if mistake.get("status") != "active" or not next_review:
                continue
            if parse_moment(next_review) <= moment:
                due_items.append(mistake)
        due_items.sort(key=lambda item: (item.get("next_review", ""), -int(item.get("occurrences", 0))))
        return due_items[: max(0, limit)]

    @staticmethod
    def _apply_pass(mistake: dict[str, Any], moment: datetime, *, source: str, answer: str | None = None, prompt: str | None = None) -> None:
        step = int(mistake.get("review_step", 0)) + 1
        mistake["review_step"] = step
        mistake["consecutive_successes"] = int(mistake.get("consecutive_successes", 0)) + 1
        mistake["mastery_score"] = round(min(1.0, step / len(REVIEW_INTERVALS)), 3)
        if step >= len(REVIEW_INTERVALS):
            mistake["status"] = "mastered"
            mistake["next_review"] = None
            mistake["mastered_at"] = iso(moment)
        else:
            mistake["status"] = "active"
            mistake["next_review"] = iso(moment + timedelta(days=REVIEW_INTERVALS[step]))
        mistake["last_reviewed"] = iso(moment)
        entry = {"result": "pass", "reviewed_at": iso(moment), "source": source}
        if answer:
            entry["answer"] = answer
        if prompt:
            entry["prompt"] = prompt
        mistake.setdefault("review_history", []).append(entry)
        mistake["review_history"] = mistake["review_history"][-HISTORY_LIMIT:]

    def grade(
        self,
        identifier: str,
        *,
        result: str,
        answer: str | None = None,
        correction: str | None = None,
        prompt: str | None = None,
        strategy: str | None = None,
        hint: str | None = None,
        at: datetime | None = None,
    ) -> tuple[dict[str, Any], str]:
        if result not in {"pass", "hard", "fail"}:
            raise DeutschLoopError("result must be pass, hard, or fail")
        moment = at or utc_now()
        document = self._mistake_document()
        mistake = self._require(document["mistakes"], identifier)
        clean_answer = (answer or "").strip()
        prompt = (prompt or "").strip()
        strategy, hint = (strategy or "").strip() or None, (hint or "").strip() or None
        if not prompt or not clean_answer:
            raise DeutschLoopError("A review requires the actual --prompt and --answer; use coach for guided practice")
        if bool(strategy) != bool(hint):
            raise DeutschLoopError("Provide both --strategy and --hint")
        if result == "pass" and hint:
            raise DeutschLoopError("A hinted answer cannot pass; use hard or coach")

        history = mistake.get("review_history") or []
        last = history[-1] if history else None
        if (
            last
            and last.get("result") == result
            and last.get("source", "review") == "review"
            and last.get("answer") == clean_answer and last.get("prompt") == prompt
            and last.get("hint") == hint and last.get("strategy") == strategy
            and last.get("correction") == correction
            and within(last.get("reviewed_at"), moment, DUPLICATE_EVENT_WINDOW)
        ):
            return mistake, "duplicate"

        next_review = _safe_moment(mistake.get("next_review"))
        if mistake.get("status") != "active" or next_review is None or next_review > moment:
            raise DeutschLoopError("This pattern is not due; use coach for practice without advancing the schedule")
        if text_fingerprint(prompt) in mistake.get("seen_prompts", []):
            raise DeutschLoopError("This review prompt was already used; ask a new situation")
        if result == "pass" and text_fingerprint(clean_answer) in mistake.get("seen_answers", []):
            raise DeutschLoopError("This answer was already seen; test transfer with a new sentence")
        _snapshot(mistake, "grade", moment)
        mistake["review_attempts"] = int(mistake.get("review_attempts", 0)) + 1
        if result == "pass":
            independent_use(mistake, clean_answer, moment, source="review", prompt=prompt)
            self._apply_pass(mistake, moment, source="review", answer=clean_answer, prompt=prompt)
        else:
            if result == "hard":
                mistake["status"] = "active"
                mistake["consecutive_successes"] = 0
                mistake["next_review"] = iso(moment + timedelta(days=1))
            else:
                if mistake.get("status") == "mastered":
                    mistake["reactivated_at"] = iso(moment)
                    mistake["previously_mastered_at"] = mistake.get("mastered_at")
                    mistake["mastered_at"] = None
                mistake["occurrences"] = int(mistake.get("occurrences", 1)) + 1
                mistake["review_failures"] = int(mistake.get("review_failures", 0)) + 1
                mistake["review_step"] = 0
                mistake["consecutive_successes"] = 0
                mistake["mastery_score"] = 0.0
                mistake["status"] = "active"
                mistake["last_seen"] = iso(moment)
                mistake["next_review"] = iso(moment + timedelta(days=REVIEW_INTERVALS[0]))
                mistake.setdefault("examples", []).append(
                    {
                        "original": clean_answer,
                        "corrected": correction.strip() if correction else None,
                        "context": REVIEW_CONTEXT,
                        "seen_at": iso(moment),
                        "event_id": None,
                    }
                )
                mistake["examples"] = mistake["examples"][-EXAMPLE_LIMIT:]
                if mistake.get("first_example") is None:
                    mistake["first_example"] = copy.deepcopy(mistake["examples"][-1])
            mistake["last_reviewed"] = iso(moment)
            entry = {"result": result, "reviewed_at": iso(moment), "source": "review", "prompt": prompt}
            if clean_answer:
                entry["answer"] = clean_answer
            mistake.setdefault("review_history", []).append(entry)
            mistake["review_history"] = mistake["review_history"][-HISTORY_LIMIT:]

        mistake["review_history"][-1].update({"strategy": strategy, "hint": hint, "correction": correction})
        if hint:
            append_coaching(mistake, outcome="assisted" if result == "hard" else "miss",
                            prompt=prompt, answer=clean_answer, strategy=strategy, hint=hint, moment=moment)
        remember_text(mistake, "seen_prompts", prompt)
        remember_text(mistake, "seen_answers", clean_answer)
        remember_text(mistake, "seen_answers", correction)
        _atomic_write(self.mistakes_path, document)
        return mistake, "graded"

    # ---- inspection and repair

    def list(self, *, status: str = "active", category: str | None = None, verbose: bool = False) -> list[dict[str, Any]]:
        if status not in {"active", "mastered", "all"}:
            raise DeutschLoopError("status must be active, mastered, or all")
        if category is not None and category not in CATEGORIES:
            raise DeutschLoopError(f"Unknown category '{category}'. Choose from: {', '.join(CATEGORY_ORDER)}")
        view = row_view(verbose)
        rows = [
            view(mistake)
            for mistake in self._mistake_document()["mistakes"]
            if (status == "all" or mistake.get("status") == status)
            and (category is None or mistake.get("category") == category)
        ]
        rows.sort(key=lambda row: (category_rank(row["category"]), -row["occurrences"], row["pattern"]))
        return rows

    def show(self, identifier: str) -> dict[str, Any]:
        return self._require(self._mistake_document()["mistakes"], identifier)

    def forget(self, identifier: str) -> dict[str, Any]:
        document = self._mistake_document()
        mistake = self._require(document["mistakes"], identifier)
        document["mistakes"] = [item for item in document["mistakes"] if item.get("id") != identifier]
        _atomic_write(self.mistakes_path, document)
        self._replace_session_ids(identifier, None)
        return mistake

    def undo(self, identifier: str) -> dict[str, Any]:
        """Revert the most recent pattern change, including coaching. One level deep."""
        document = self._mistake_document()
        mistakes = document["mistakes"]
        mistake = self._require(mistakes, identifier)
        snapshot = mistake.get("undo")
        if not snapshot:
            raise DeutschLoopError(
                f"Nothing to undo for {identifier}: only the latest record, grade, observe, coach, or merge can be undone"
            )
        undone = {"undone": snapshot.get("action"), "undone_at": snapshot.get("at")}
        if snapshot.get("action") == "merge":
            source = snapshot["merged_source"]
            if self._find(mistakes, source["id"]):
                raise DeutschLoopError(f"Cannot undo the merge: {source['id']} exists again")
            restored = snapshot["state"]
            mistakes[mistakes.index(mistake)] = restored
            mistakes.insert(min(int(snapshot.get("source_index", len(mistakes))), len(mistakes)), source)
            sessions = self._session_document()
            self._restore_session_ids(sessions, snapshot.get("sessions") or [], source["id"], restored["id"])
            _atomic_write(self.mistakes_path, document)
            if snapshot.get("sessions"):
                _atomic_write(self.sessions_path, sessions)
            return {"status": "undone", **undone, "mistake": restored, "restored": source}
        if snapshot.get("action") == "record":
            latest = (mistake.get("examples") or [{}])[-1]
            if latest.get("session_id") and latest.get("event_id"):
                self._remove_session_feedback(identifier, latest["event_id"])
        if snapshot.get("state") is None:
            document["mistakes"] = [item for item in mistakes if item.get("id") != identifier]
            _atomic_write(self.mistakes_path, document)
            self._replace_session_ids(identifier, None)
            return {"status": "removed", **undone, "mistake": mistake}
        restored = snapshot["state"]
        mistakes[mistakes.index(mistake)] = restored
        _atomic_write(self.mistakes_path, document)
        return {"status": "undone", **undone, "mistake": restored}

    def merge(self, source_id: str, target_id: str, *, at: datetime | None = None) -> dict[str, Any]:
        if source_id == target_id:
            raise DeutschLoopError("source and target must be different mistake IDs")
        moment = at or utc_now()
        document = self._mistake_document()
        mistakes = document["mistakes"]
        source = self._require(mistakes, source_id)
        target = self._require(mistakes, target_id)
        # Both patterns are kept whole in the target's undo snapshot, so a wrong merge can be reverted.
        before = copy.deepcopy({key: value for key, value in target.items() if key != "undo"})
        merged_source = copy.deepcopy({key: value for key, value in source.items() if key != "undo"})
        source_index = mistakes.index(source)

        target["occurrences"] = int(target.get("occurrences", 0)) + int(source.get("occurrences", 0))
        for field in ("correct_uses", "review_attempts", "review_failures"):
            target[field] = int(target.get(field, 0)) + int(source.get(field, 0))
        for field, stamp, limit in (
            ("examples", "seen_at", EXAMPLE_LIMIT),
            ("review_history", "reviewed_at", HISTORY_LIMIT),
            ("correct_use_history", "observed_at", HISTORY_LIMIT),
            ("coaching_history", "at", HISTORY_LIMIT),
        ):
            combined = list(target.get(field, [])) + list(source.get(field, []))
            combined.sort(key=lambda item: item.get(stamp) or "")
            target[field] = combined[-limit:]
        for field in ("seen_prompts", "seen_answers"):
            target[field] = list(dict.fromkeys(target.get(field, []) + source.get(field, [])))
        anchors = [entry for entry in (target.get("first_example"), source.get("first_example")) if entry]
        target["first_example"] = min(anchors, key=lambda entry: entry.get("seen_at") or "") if anchors else None
        supports = [entry for entry in (target.get("helpful_hint"), source.get("helpful_hint")) if entry]
        target["helpful_hint"] = max(supports, key=lambda entry: entry["at"]) if supports else None
        proofs = [entry for entry in (target.get("learning_proof"), source.get("learning_proof")) if entry]
        target["learning_proof"] = max(proofs, key=lambda entry: entry["independent"]["at"]) if proofs else None
        first_seen = [value for value in (target.get("first_seen"), source.get("first_seen")) if value]
        last_seen = [value for value in (target.get("last_seen"), source.get("last_seen")) if value]
        if first_seen:
            target["first_seen"] = min(first_seen)
        if last_seen:
            target["last_seen"] = max(last_seen)
        if "active" in (target.get("status"), source.get("status")):
            step = min(int(target.get("review_step", 0)), int(source.get("review_step", 0)))
            target["status"] = "active"
            target["review_step"] = step
            target["consecutive_successes"] = min(
                int(target.get("consecutive_successes", 0)), int(source.get("consecutive_successes", 0))
            )
            target["mastery_score"] = round(min(1.0, step / len(REVIEW_INTERVALS)), 3)
            candidates = [value for value in (target.get("next_review"), source.get("next_review")) if value]
            target["next_review"] = min(candidates) if candidates else iso(moment + timedelta(days=REVIEW_INTERVALS[0]))
            target["mastered_at"] = None
        aliases = list(target.get("aliases", []))
        for alias in [{"category": source["category"], "pattern_key": source["pattern_key"]}] + list(source.get("aliases", [])):
            if alias not in aliases:
                aliases.append(alias)
        target["aliases"] = aliases
        target.setdefault("merged_from", []).append(
            {"id": source["id"], "pattern": source["pattern"], "category": source["category"], "merged_at": iso(moment)}
        )
        sessions = self._session_document()
        journal = self._rewrite_session_ids(sessions, source_id, target_id)
        target["undo"] = {"action": "merge", "at": iso(moment), "state": before, "merged_source": merged_source,
                          "source_index": source_index, "sessions": journal}
        document["mistakes"] = [item for item in mistakes if item.get("id") != source_id]
        _atomic_write(self.mistakes_path, document)
        if journal:
            _atomic_write(self.sessions_path, sessions)
        return target

    def rename(
        self,
        identifier: str,
        *,
        pattern: str | None = None,
        category: str | None = None,
        rule: str | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        if pattern is None and category is None and rule is None and label is None:
            raise DeutschLoopError("Provide --pattern, --category, --rule, or --label")
        label = clean_label(label)
        document = self._mistake_document()
        mistakes = document["mistakes"]
        mistake = self._require(mistakes, identifier)
        if category is not None and category not in CATEGORIES:
            raise DeutschLoopError(f"Unknown category '{category}'. Choose from: {', '.join(CATEGORY_ORDER)}")
        if pattern is not None and not pattern.strip():
            raise DeutschLoopError("pattern must not be empty")
        if rule is not None and not rule.strip():
            raise DeutschLoopError("rule must not be empty")

        new_category = category or mistake["category"]
        new_pattern = pattern.strip() if pattern else mistake["pattern"]
        new_key = pattern_key(new_pattern)
        if not new_key:
            raise DeutschLoopError("pattern must contain letters or digits")
        new_id = mistake_id_for(new_category, new_key)
        previous_id = mistake["id"]
        if new_id != previous_id:
            clash = self._find(mistakes, new_id) or next(
                (item for item in mistakes if item is not mistake and item.get("pattern_key") == new_key), None
            )
            if clash:
                raise DeutschLoopError(
                    f"'{new_pattern}' already exists as {clash['id']}; run: merge {previous_id} {clash['id']}"
                )
        if (new_category, new_key) != (mistake["category"], mistake.get("pattern_key")):
            aliases = [
                alias
                for alias in mistake.get("aliases", [])
                if not (alias.get("category") == new_category and alias.get("pattern_key") == new_key)
            ]
            old_alias = {"category": mistake["category"], "pattern_key": mistake.get("pattern_key")}
            if old_alias not in aliases:
                aliases.append(old_alias)
            mistake["aliases"] = aliases
        mistake.update({"id": new_id, "pattern": new_pattern, "pattern_key": new_key, "category": new_category})
        mistake.pop("undo", None)
        if rule is not None:
            mistake["rule"] = rule.strip()
        if label is not None:
            mistake["label"] = label
        _atomic_write(self.mistakes_path, document)
        if new_id != previous_id:
            self._replace_session_ids(previous_id, new_id)
        return {"previous_id": previous_id, "mistake": mistake}

    # ---- reporting

    def summary(self, *, at: datetime | None = None, verbose: bool = False) -> dict[str, Any]:
        moment = at or utc_now()
        view = row_view(verbose)
        profile = self._profile()
        mistakes = self._mistake_document()["mistakes"]
        sessions = self._session_document()["sessions"]
        words = self._vocabulary_document()["words"]

        categories: dict[str, dict[str, Any]] = {}
        for mistake in mistakes:
            bucket = categories.setdefault(
                mistake["category"],
                {
                    "patterns": 0,
                    "active": 0,
                    "mastered": 0,
                    "errors": 0,
                    "correct": 0,
                    "evidence": 0,
                    "due": 0,
                    "mastery_total": 0.0,
                },
            )
            is_active = mistake.get("status") == "active"
            next_review = _safe_moment(mistake.get("next_review"))
            bucket["patterns"] += 1
            bucket["active"] += int(is_active)
            bucket["mastered"] += int(mistake.get("status") == "mastered")
            bucket["errors"] += int(mistake.get("occurrences", 0))
            bucket["correct"] += correct_total(mistake)
            bucket["evidence"] += evidence(mistake)
            bucket["due"] += int(is_active and next_review is not None and next_review <= moment)
            bucket["mastery_total"] += float(mistake.get("mastery_score", 0.0))
        for bucket in categories.values():
            bucket["accuracy_percent"] = accuracy_percent(bucket["correct"], bucket["errors"])
            bucket["mastery_percent"] = round(100 * bucket.pop("mastery_total") / max(1, bucket["patterns"]))
            # Without a single review or correct use there is nothing to measure yet.
            bucket["new"] = bucket["evidence"] == 0
            bucket["weak"] = (
                not bucket["new"] and bucket["accuracy_percent"] < WEAK_ACCURACY_THRESHOLD and bucket["errors"] >= 2
            )

        # A cluster is a family of related patterns that keep failing. Breadth (how many
        # different members failed recently) outranks depth: many members failing means the
        # learner is missing the rule, not one word.
        window_start = moment - CLUSTER_WINDOW
        clusters = []
        for category in categories:
            active = [item for item in mistakes if item["category"] == category and item.get("status") == "active"]
            occurrences = sum(int(item.get("occurrences", 0)) for item in active)
            if len(active) < CLUSTER_MIN_PATTERNS or occurrences < CLUSTER_MIN_OCCURRENCES:
                continue
            recent = {item["id"]: errors_between(item, window_start, moment) for item in active}
            active.sort(key=lambda item: (-recent[item["id"]], -int(item.get("occurrences", 0)), item["pattern"]))
            clusters.append(
                {
                    "category": category,
                    "patterns": [item["pattern"] for item in active],
                    "labels": [display_label(item)[0] for item in active],
                    "pattern_ids": [item["id"] for item in active],
                    "occurrences": occurrences,
                    "recent_errors": sum(recent.values()),
                    "recent_patterns": sum(1 for value in recent.values() if value),
                }
            )
        clusters.sort(
            key=lambda cluster: (
                -cluster["recent_patterns"],
                -cluster["recent_errors"],
                -cluster["occurrences"],
                category_rank(cluster["category"]),
            )
        )

        active_rows = [view(item) for item in mistakes if item.get("status") == "active"]
        weakest = sorted(active_rows, key=lambda row: (row["accuracy_percent"], -row["occurrences"], row["pattern"]))[:5]
        due_rows = [view(item) for item in self.due(at=moment, limit=len(mistakes))]
        moments = [value for value in _event_moments(mistakes, sessions, profile, words) if value <= moment]
        days = {local_date(value) for value in moments}
        today = local_date(moment)
        return {
            "as_of": iso(moment),
            "profile": profile_view(profile),
            "total_patterns": len(mistakes),
            "active_patterns": len(active_rows),
            "mastered_patterns": sum(item.get("status") == "mastered" for item in mistakes),
            "errors_total": sum(int(item.get("occurrences", 0)) for item in mistakes),
            "correct_total": sum(correct_total(item) for item in mistakes),
            "due_now": len(due_rows),
            "streak_days": streak_days(days, today),
            "active_days_last_30": sum(1 for day in days if 0 <= (today - day).days < 30),
            "last_activity_at": iso(max(moments)) if moments else None,
            "categories": categories,
            "clusters": clusters,
            "cluster_window_days": CLUSTER_WINDOW.days,
            "recent_errors_total": sum(errors_between(item, window_start, moment) for item in mistakes),
            "weakest_patterns": weakest,
            "due_patterns": due_rows[:5],
            "vocabulary": vocabulary_overview(words, moment),
        }

    def recap(self, *, days: int = RECENT_DAYS, at: datetime | None = None, verbose: bool = False) -> dict[str, Any]:
        moment = at or utc_now()
        view = row_view(verbose)
        window = max(1, days)
        since = moment - timedelta(days=window)
        profile = self._profile()
        mistakes = self._mistake_document()["mistakes"]
        sessions = self._session_document()["sessions"]
        words = self._vocabulary_document()["words"]

        def in_window(stamp: str | None) -> bool:
            parsed = _safe_moment(stamp)
            return parsed is not None and since < parsed <= moment

        new_patterns: list[str] = []
        recurring: list[dict[str, Any]] = []
        errors_total = 0
        recurrences = 0
        reviews = {"total": 0, "pass": 0, "hard": 0, "fail": 0}
        observed = 0
        mastered: list[str] = []
        mastered_labels: list[str] = []
        for mistake in mistakes:
            examples_in = sum(1 for example in mistake.get("examples", []) if in_window(example.get("seen_at")))
            is_new = in_window(mistake.get("first_seen"))
            if is_new:
                new_patterns.append(mistake["pattern"])
            errors_total += examples_in
            repeat_count = examples_in - (1 if is_new and examples_in else 0)
            recurrences += repeat_count
            if repeat_count:
                recurring.append(
                    {
                        "id": mistake["id"],
                        "pattern": mistake["pattern"],
                        "label": display_label(mistake)[0],
                        "category": mistake["category"],
                        "count": examples_in,
                        "last_seen": mistake.get("last_seen"),
                    }
                )
            for entry in mistake.get("review_history", []):
                if entry.get("source", "review") != "review" or not in_window(entry.get("reviewed_at")):
                    continue
                reviews["total"] += 1
                reviews[entry.get("result", "pass")] = reviews.get(entry.get("result", "pass"), 0) + 1
            observed += sum(1 for entry in mistake.get("correct_use_history", []) if in_window(entry.get("observed_at")))
            if mistake.get("status") == "mastered" and in_window(mistake.get("mastered_at")):
                mastered.append(mistake["pattern"])
                mastered_labels.append(display_label(mistake)[0])
        recurring.sort(key=lambda row: row["last_seen"] or "", reverse=True)
        recurring.sort(key=lambda row: -row["count"])
        word_reviews = {"total": 0, "pass": 0, "hard": 0, "fail": 0}
        for word in words:
            for entry in word.get("review_history", []):
                if in_window(entry.get("reviewed_at")):
                    word_reviews["total"] += 1
                    word_reviews[entry["result"]] += 1

        roleplays = [
            session
            for session in sessions
            if session.get("type", "roleplay") == "roleplay" and in_window(session.get("started_at"))
        ]
        due_items = self.due(at=moment, limit=len(mistakes))
        due_rows = [view(item) for item in due_items]
        moments = [value for value in _event_moments(mistakes, sessions, profile, words) if value <= moment]
        last = max(moments) if moments else None
        day_set = {local_date(value) for value in moments}
        active = [item for item in mistakes if item.get("status") == "active"]
        active_rows = [view(item) for item in active]
        weakest = sorted(active_rows, key=lambda row: (row["accuracy_percent"], -row["occurrences"], row["pattern"]))
        next_focus = due_rows[0] if due_rows else (weakest[0] if weakest else None)
        # The opener quotes one old sentence: the first due pattern, else the most recent active mistake.
        recent = [item for item in active if item.get("examples")]
        callback_target = due_items[0] if due_items else (
            max(recent, key=lambda item: item["examples"][-1].get("seen_at") or "") if recent else None
        )
        callback = {**compact(callback_target), "reason": "due" if due_items else "recent"} if callback_target else None
        needs_label = [
            {"id": item["id"], "pattern": item["pattern"], "category": item["category"], "rule": item.get("rule")}
            for item in active if display_label(item)[1] == "key"
        ]
        upcoming = sorted(
            parsed
            for parsed in (_safe_moment(item.get("next_review")) for item in mistakes if item.get("status") == "active")
            if parsed is not None and parsed > moment
        )
        later_today = [value for value in upcoming if local_date(value) == local_date(moment)]
        schedule = {
            "due_now": len(due_rows),
            "later_today": len(later_today),
            "later_today_first_local": to_local(later_today[0]).isoformat() if later_today else None,
            "next_local": to_local(upcoming[0]).isoformat() if upcoming else None,
        }
        shown = _safe_moment(profile.get("last_full_profile_at")) or _safe_moment(profile.get("onboarding_completed_at"))
        full_profile_due = bool(mistakes) and last is not None and (
            shown is None
            or (moment - shown >= timedelta(days=FULL_PROFILE_INTERVAL_DAYS) and last > shown)
        )
        recurring_ids = {row["id"] for row in recurring}
        due_ids = {item["id"] for item in due_items}
        ranked = sorted(
            active,
            key=lambda item: (item["id"] not in due_ids, -int(item.get("occurrences", 0)),
                              item.get("next_review") or "~", display_label(item)[0]),
        )
        board = [
            {**view(item), "due": item["id"] in due_ids, "came_back": item["id"] in recurring_ids}
            for item in ranked[:BOARD_ROWS]
        ]
        open_scenes = [session for session in sessions if session.get("status") in {"active", "debriefing"}]
        active_scene = max(open_scenes, key=lambda session: session.get("started_at", "")) if open_scenes else None
        completed_scenes = [session for session in sessions if session.get("status") == "complete"]
        last_scene = max(completed_scenes, key=lambda session: session.get("ended_at") or session.get("started_at", "")) if completed_scenes else None
        result = {
            "as_of": iso(moment),
            "window_days": window,
            "since": iso(since),
            "profile": profile_view(profile),
            "onboarding": onboarding_view(profile, has_activity=last is not None),
            "active_roleplay": {"status": active_scene["status"], "scenario": active_scene["scenario"],
                                **({"mission_id": active_scene["mission_id"], "mission_step_id": active_scene["mission_step_id"]}
                                   if active_scene.get("mission_id") else {}),
                                **session_timing(active_scene, moment)} if active_scene else None,
            "last_roleplay": {"session_id": last_scene["id"], "scenario": last_scene["scenario"],
                              "ended_at_local": local_iso(last_scene.get("ended_at")),
                              "next_action": "present_debrief"} if last_scene else None,
            "last_activity_at": iso(last) if last else None,
            "last_activity_local": to_local(last).isoformat() if last else None,
            "days_since_last_activity": (local_date(moment) - local_date(last)).days if last else None,
            "streak_days": streak_days(day_set, local_date(moment)),
            "errors": {"total": errors_total, "new_patterns": len(new_patterns), "recurrences": recurrences},
            "new_patterns": new_patterns,
            "recurring_patterns": recurring[:5],
            "recurring_total": len(recurring),
            "reviews": reviews,
            "word_reviews": word_reviews,
            "correct_uses": observed,
            "mastered": mastered,
            "mastered_labels": mastered_labels,
            "roleplays": {"count": len(roleplays), "scenarios": [session.get("scenario") for session in roleplays]},
            "due_now": len(due_rows),
            "due_patterns": due_rows[:5],
            "next_focus": next_focus,
            "callback": callback,
            "needs_label": needs_label,
            "active_patterns": len(active_rows),
            "mastered_total": sum(item.get("status") == "mastered" for item in mistakes),
            "schedule": schedule,
            "full_profile_due": full_profile_due,
            "missions": self.mission_list(at=moment),
            "board": board,
            "board_more": max(0, len(ranked) - len(board)),
            "vocabulary": vocabulary_overview(words, moment),
        }
        result["card"] = render_recap_card(result)
        return result

    # ---- continuing real-life missions

    def mission_create(self, *, goal: str, scenario: str, deadline: str | None = None,
                       at: datetime | None = None) -> dict[str, Any]:
        moment = at or utc_now()
        goal = goal.strip()
        scenario = SCENARIO_ALIASES.get(scenario, scenario)
        if not goal or scenario not in SCENARIOS:
            raise DeutschLoopError("Provide a real learner-stated goal and a supported scenario")
        resolved = parse_deadline(deadline, moment)
        document = self._mission_document()
        existing = next((item for item in document["missions"] if item["status"] == "active"
                         and normalized(item["goal"]) == normalized(goal) and item["scenario"] == scenario
                         and item.get("deadline") == resolved), None)
        if existing:
            return {"status": "existing", "mission": self.mission_show(existing["id"], at=moment)}
        self.ensure()
        mission = {"id": f"g_{uuid.uuid4().hex[:12]}", "goal": goal, "scenario": scenario, "deadline": resolved,
                   "created_at": iso(moment), "updated_at": iso(moment), "status": "active", "step_index": 0,
                   "steps": mission_steps(scenario), "attempts": [], "completed_at": None}
        document["missions"].append(mission)
        _atomic_write(self.missions_path, document)
        return {"status": "created", "mission": self.mission_show(mission["id"], at=moment)}

    @staticmethod
    def _require_mission(document: dict[str, Any], identifier: str) -> dict[str, Any]:
        mission = next((item for item in document["missions"] if item.get("id") == identifier), None)
        if mission is None:
            raise DeutschLoopError(f"Unknown mission ID: {identifier}")
        return mission

    def mission_show(self, identifier: str, *, at: datetime | None = None) -> dict[str, Any]:
        mission = self._require_mission(self._mission_document(), identifier)
        sessions = _read_json(self.sessions_path, {"sessions": []})["sessions"]
        return mission_view(mission, at or utc_now(), sessions)

    def mission_list(self, *, status: str = "active", at: datetime | None = None) -> list[dict[str, Any]]:
        if status not in {"active", "completed", "cancelled", "all"}:
            raise DeutschLoopError("Unknown mission status")
        moment = at or utc_now()
        sessions = _read_json(self.sessions_path, {"sessions": []})["sessions"]
        missions = [mission_view(item, moment, sessions) for item in self._mission_document()["missions"]
                    if status == "all" or item["status"] == status]
        return sorted(missions, key=lambda item: (item.get("deadline") or "9999-12-31", item["goal"]))

    def mission_start(self, identifier: str, *, minutes: int = 5, input_mode: str = "text",
                      at: datetime | None = None) -> dict[str, Any]:
        moment = at or utc_now()
        mission = self._require_mission(self._mission_document(), identifier)
        view = self.mission_show(identifier, at=moment)
        if not 1 <= minutes <= 60 or input_mode not in {"text", "transcript"}:
            raise DeutschLoopError("Use 1–60 minutes and text/transcript input")
        if moment < parse_moment(mission["updated_at"]):
            raise DeutschLoopError("A mission scene cannot precede its saved progress")
        if mission["status"] != "active":
            raise DeutschLoopError("This mission is not active")
        index = mission["step_index"]
        step = mission["steps"][index]
        sessions = self._session_document()["sessions"]
        # A scene is the sole durable link to a mission, so interrupted starts never orphan an attempt.
        if view["pending_session_id"]:
            pending = self.roleplay_show(view["pending_session_id"], at=moment)
            return {"status": "resume", **pending, "mission": view, "next_action": view["next_action"]}
        unfinished = [item for item in sessions if item.get("status") in {"active", "debriefing"}]
        if unfinished:
            raise DeutschLoopError(f"Finish or resume scene {unfinished[-1]['id']} before starting a mission scene")
        attempts = mission.get("attempts") or []
        last = attempts[-1] if attempts else None
        previous_scene = next((item for item in sessions if last and item["id"] == last["session_id"]), None)
        mistakes = self._mistake_document()["mistakes"]
        active = [item for item in mistakes if item.get("status") == "active"]
        previous_corrections = session_debrief(previous_scene, mistakes)["corrections"] if previous_scene else []
        previous_ids = {row["mistake_id"] for row in previous_corrections}
        ranked = sorted(active, key=lambda item: (item["id"] not in previous_ids, not _is_due(item, moment),
                                                 -int(item.get("occurrences", 0)), item["id"]))
        focus_patterns = [compact(item) for item in ranked[:3]]
        repeat = sum(attempt["step_id"] == step["id"] for attempt in attempts)
        context = {"mission_id": identifier, "step": copy.deepcopy(step), "step_index": index,
                   "mission": view, "focus_patterns": focus_patterns,
                   "opening": step["openings"][repeat % len(step["openings"])],
                   "adaptation": {"mode": "repair" if last and last["result"] == "practice" else "challenge" if last else "start",
                                  "previous_result": last["result"] if last else None,
                                  "previous_support": last["support"] if last else None,
                                  "previous_evidence": copy.deepcopy(last["evidence"]) if last else [],
                                  "previous_note": last["note"] if last else None,
                                  "previous_corrections": previous_corrections,
                                  "policy": "Use a new situation. On repair, break the same goal into smaller prompts and keep useful hints in reserve. On progress, add one new complication. Weave recorded focus patterns in naturally; do not assume new personal facts."}}
        result = self.roleplay_start(mission["scenario"], minutes=minutes, input_mode=input_mode,
                                     at=moment, _mission_context=context)
        return {"status": "started", **result, "mission": self.mission_show(identifier, at=moment)}

    def mission_assess(self, identifier: str, *, session_id: str, result: str, support: str,
                       evidence_turn_ids: list[str], note: str, at: datetime | None = None) -> dict[str, Any]:
        moment = at or utc_now()
        if result not in {"achieved", "practice"} or support not in {"none", "hint", "shown"} or not note.strip():
            raise DeutschLoopError("Provide achieved/practice, the actual support, and a grounded assessment note")
        document = self._mission_document()
        mission = self._require_mission(document, identifier)
        session = self._require_session(self._session_document(), session_id)
        if session.get("mission_id") != identifier or session.get("status") != "complete":
            raise DeutschLoopError("Assess a completed scene belonging to this mission")
        if moment < parse_moment(session.get("finished_at") or session["ended_at"]):
            raise DeutschLoopError("A mission assessment cannot precede its completed scene")
        ids = list(dict.fromkeys(evidence_turn_ids))
        if not ids:
            raise DeutschLoopError("An assessment needs actual learner turn IDs as evidence")
        turns = {turn["id"]: turn for turn in session.get("utterances", [])}
        if any(key not in turns or turns[key]["speaker"] != "learner" for key in ids):
            raise DeutschLoopError("Evidence must cite real learner turns from this scene")
        observed = {turn.get("support", "none") for turn in session.get("utterances", []) if turn["speaker"] == "partner"}
        actual_support = "shown" if "shown" in observed or support == "shown" else "hint" if "hint" in observed or support == "hint" else "none"
        if result == "achieved" and actual_support != "none":
            raise DeutschLoopError("A supported scene cannot count as achieved unaided; use practice")
        attempts = mission["attempts"]
        previous = next((attempt for attempt in attempts if attempt["session_id"] == session_id), None)
        if previous:
            if (previous["result"], previous["support"], previous["note"], [row["turn_id"] for row in previous["evidence"]]) != (result, actual_support, note.strip(), ids):
                raise DeutschLoopError("This scene was already assessed differently; undo the latest mission assessment first")
            return {"status": "duplicate", "mission": self.mission_show(identifier, at=moment)}
        if moment < parse_moment(mission["updated_at"]):
            raise DeutschLoopError("An assessment cannot precede saved mission progress")
        if mission["status"] != "active" or session.get("mission_step_id") != mission["steps"][mission["step_index"]]["id"]:
            raise DeutschLoopError("This scene does not belong to the mission's current step")
        pending = self.mission_show(identifier, at=moment)["pending_session_id"]
        if pending != session_id:
            raise DeutschLoopError("Assess the mission's pending scene before any other scene")
        attempt = {"session_id": session_id, "step_id": session["mission_step_id"], "result": result,
                   "support": actual_support, "note": note.strip(), "at": iso(moment),
                   "previous_index": mission["step_index"],
                   "evidence": [{"turn_id": key, "text": turns[key]["text"], "at": turns[key]["at"]} for key in ids]}
        attempts.append(attempt)
        if result == "achieved":
            mission["step_index"] += 1
            if mission["step_index"] == len(mission["steps"]):
                mission["status"] = "completed"
                mission["completed_at"] = iso(moment)
        mission["updated_at"] = iso(moment)
        _atomic_write(self.missions_path, document)
        return {"status": "assessed", "mission": self.mission_show(identifier, at=moment)}

    def mission_undo(self, identifier: str, *, at: datetime | None = None) -> dict[str, Any]:
        moment = at or utc_now()
        document = self._mission_document()
        mission = self._require_mission(document, identifier)
        if mission["status"] == "cancelled" or not mission["attempts"]:
            raise DeutschLoopError("No mission assessment to undo")
        if moment < parse_moment(mission["updated_at"]):
            raise DeutschLoopError("Undo cannot precede saved mission progress")
        pending = self.mission_show(identifier, at=moment)["pending_session_id"]
        if pending:
            raise DeutschLoopError("Assess the newer pending scene before undoing the latest assessment")
        undone = mission["attempts"].pop()
        mission.update(step_index=undone["previous_index"], status="active", completed_at=None, updated_at=iso(moment))
        _atomic_write(self.missions_path, document)
        return {"status": "undone", "session_id": undone["session_id"], "mission": self.mission_show(identifier, at=moment)}

    def mission_update(self, identifier: str, *, goal: str | None = None, deadline: str | None = None,
                       cancel: bool = False, at: datetime | None = None) -> dict[str, Any]:
        moment = at or utc_now()
        document = self._mission_document()
        mission = self._require_mission(document, identifier)
        if mission["status"] != "active":
            raise DeutschLoopError("Only an active mission can be updated")
        if moment < parse_moment(mission["updated_at"]):
            raise DeutschLoopError("An update cannot precede saved mission progress")
        if goal is None and deadline is None and not cancel:
            raise DeutschLoopError("Provide a goal, deadline, or --cancel")
        if goal is not None:
            if not goal.strip():
                raise DeutschLoopError("A mission goal cannot be empty")
            mission["goal"] = goal.strip()
        if deadline is not None:
            mission["deadline"] = parse_deadline(deadline, moment)
        if cancel:
            pending = self.mission_show(identifier, at=moment)["pending_session_id"]
            if pending and self.roleplay_show(pending)["session"]["status"] != "complete":
                raise DeutschLoopError("End and finish the current scene before cancelling its mission")
            mission["status"] = "cancelled"
        mission["updated_at"] = iso(moment)
        _atomic_write(self.missions_path, document)
        return {"status": "updated", "mission": self.mission_show(identifier, at=moment)}

    # ---- roleplay

    def roleplay_start(
        self,
        scenario: str,
        *,
        focus: str | None = None,
        minutes: int = 5,
        input_mode: str = "text",
        at: datetime | None = None,
        _mission_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scenario = SCENARIO_ALIASES.get(scenario, scenario)
        if scenario not in SCENARIOS:
            raise DeutschLoopError(f"Unknown scenario '{scenario}'. Choose from: {', '.join(sorted(SCENARIOS))}")
        if not 1 <= minutes <= 60:
            raise DeutschLoopError("minutes must be between 1 and 60")
        if input_mode not in {"text", "transcript"}:
            raise DeutschLoopError("input_mode must be text or transcript")
        moment = at or utc_now()
        focus_pattern = None
        if not focus and _mission_context and _mission_context["focus_patterns"]:
            focus_pattern = _mission_context["focus_patterns"][0]
            focus = focus_pattern["label"]
        if not focus:
            due = self.due(at=moment, limit=1)
            active = [item for item in self._mistake_document()["mistakes"] if item.get("status") == "active"]
            target = due[0] if due else (max(active, key=lambda item: item.get("occurrences", 0)) if active else None)
            if target:
                focus_pattern = compact(target)
                focus = focus_pattern["label"]
        goal = _mission_context["mission"]["goal"] if _mission_context else self._profile().get("goal")
        document = self._session_document()
        session = {
            "id": f"s_{uuid.uuid4().hex[:12]}",
            "type": "roleplay",
            "scenario": scenario,
            "input_mode": input_mode,
            "focus": focus,
            "focus_id": focus_pattern["id"] if focus_pattern else None,
            "learner_goal": goal,
            "status": "active",
            "started_at": iso(moment),
            "ended_at": None,
            "target_seconds": minutes * 60,
            "utterances": [],
            "feedback": [],
            "vocabulary": [],
            "known_pattern_ids": [item["id"] for item in self._mistake_document()["mistakes"]],
            "turns": None,
            "duration_seconds": None,
            "mistake_ids": [],
            "notes": None,
            **({"mission_id": _mission_context["mission_id"], "mission_step_id": _mission_context["step"]["id"],
                "mission_focus_ids": [item["id"] for item in _mission_context["focus_patterns"]]} if _mission_context else {}),
        }
        document["sessions"].append(session)
        _atomic_write(self.sessions_path, document)
        return {
            "session": session,
            "contract": {
                **SCENARIOS[scenario],
                "feedback_policy": "Stay in character; defer ordinary corrections; give at most three in the debrief.",
                "focus": focus,
                "focus_pattern": focus_pattern,
                "personal_goal": goal,
                "target_seconds": minutes * 60,
                "input_mode": input_mode,
                "timing_policy": "At the next learner turn after the target, close naturally unless they want to continue. Elapsed session time is not speaking time.",
                **({"mission": _mission_context["mission"], "mission_step": _mission_context["step"],
                    "opening": _mission_context["opening"], "learner_goal": _mission_context["step"]["goal"],
                    "focus_patterns": _mission_context["focus_patterns"], "adaptation": _mission_context["adaptation"]}
                   if _mission_context else {}),
            },
        }

    def roleplay_turn(
        self, identifier: str, *, speaker: str, text: str, event_id: str | None = None, support: str = "none", at: datetime | None = None,
    ) -> dict[str, Any]:
        """Store one actual utterance. There is no correction or grading on this path."""
        if speaker not in {"learner", "partner"} or not text.strip():
            raise DeutschLoopError("Provide a learner or partner speaker and nonempty text")
        if support not in {"none", "hint", "shown"} or (speaker != "partner" and support != "none"):
            raise DeutschLoopError("Only a partner turn can record hint/shown support")
        moment = at or utc_now()
        document = self._session_document()
        session = self._require_session(document, identifier)
        utterances = session.get("utterances", [])
        retry = next((turn for turn in utterances if event_id and turn.get("event_id") == event_id), None)
        if retry:
            if retry["text"] != text or retry["speaker"] != speaker or retry.get("support", "none") != support:
                raise DeutschLoopError("This turn event ID already belongs to a different utterance")
            return {"status": "duplicate", "utterance": retry, **session_timing(session, moment)}
        if speaker == "learner" and is_scene_end_request(text):
            self.roleplay_stop(identifier, at=moment)
            return {"status": "scene_ended", "control": "end_scene", **self.roleplay_show(identifier, at=moment)}
        if session.get("status") != "active":
            raise DeutschLoopError("This scene is closed; start a new scene to continue")
        latest_at = utterances[-1]["at"] if utterances else session["started_at"]
        if moment < parse_moment(latest_at):
            raise DeutschLoopError("A turn cannot precede the scene or its previous turn")
        if not event_id and utterances:
            latest = utterances[-1]
            if latest["speaker"] == speaker and latest["text"] == text and latest.get("support", "none") == support and within(latest["at"], moment, DUPLICATE_EVENT_WINDOW):
                return {"status": "duplicate", "utterance": latest, **session_timing(session, moment)}
        turn = {"id": f"t_{uuid.uuid4().hex[:12]}", "speaker": speaker, "text": text, "at": iso(moment), "event_id": event_id}
        if support != "none":
            turn["support"] = support
        session.setdefault("utterances", []).append(turn)
        _atomic_write(self.sessions_path, document)
        return {"status": "stored", "utterance": turn, **session_timing(session, moment)}

    def roleplay_stop(self, identifier: str, *, at: datetime | None = None) -> dict[str, Any]:
        """Freeze scene duration before the tutor spends time on the debrief."""
        moment = at or utc_now()
        document = self._session_document()
        session = self._require_session(document, identifier)
        if session.get("status") != "active":
            return session
        latest_at = (session.get("utterances") or [{"at": session["started_at"]}])[-1]["at"]
        if moment < parse_moment(latest_at):
            raise DeutschLoopError("A scene cannot end before its last turn")
        session.update({"status": "debriefing", "ended_at": iso(moment),
                        "duration_seconds": int((moment - parse_moment(session["started_at"])).total_seconds()),
                        "duration_source": "elapsed", "turns": session_timing(session, moment)["learner_turns"]})
        _atomic_write(self.sessions_path, document)
        return session

    def roleplay_vocab(
        self, identifier: str, *, term: str, meaning: str, turn_id: str, surface: str | None = None,
    ) -> dict[str, Any]:
        document = self._session_document()
        session = self._require_session(document, identifier)
        if session.get("status") != "debriefing":
            raise DeutschLoopError("Vocabulary is collected in the debrief after stopping the scene")
        turn = next((item for item in session.get("utterances", []) if item["id"] == turn_id), None)
        term, meaning, surface = term.strip(), meaning.strip(), (surface or term).strip()
        if not term or not meaning or not surface or not turn:
            raise DeutschLoopError("Provide a term, meaning and an actual source turn")
        if not re.search(r"(?<!\w)" + re.escape(surface) + r"(?!\w)", turn["text"], re.IGNORECASE):
            raise DeutschLoopError("The vocabulary surface must occur in the referenced turn")
        entry = {"term": term, "meaning": meaning, "surface": surface, "turn_id": turn_id, "example": turn["text"]}
        vocabulary = session.setdefault("vocabulary", [])
        key = word_key(term)
        deck = self._vocabulary_document()
        stored = next((item for item in vocabulary if word_key(item["term"]) == key), None)
        if stored is not None:
            # A retry. When the earlier call saved the scene entry but not its card, finish that now.
            word = next((item for item in deck["words"] if item.get("key") == key), None)
            deck_status = "known"
            if word is None:
                stored_turn = next((item for item in session.get("utterances", []) if item["id"] == stored.get("turn_id")), turn)
                word, deck_status = self._add_scene_word(deck, session, stored, stored_turn)
                _atomic_write(self.vocabulary_path, deck)
            return {"status": "duplicate", "vocabulary": vocabulary, "deck": deck_status,
                    "word": word_view(word, parse_moment(turn["at"]))}
        if len(vocabulary) >= SCENE_VOCABULARY_LIMIT:
            raise DeutschLoopError(f"Keep at most {SCENE_VOCABULARY_LIMIT} useful vocabulary items per scene")
        vocabulary.append(entry)
        # Every scene word enters the deck; a word met before gets one more source, not a new schedule.
        word, deck_status = self._add_scene_word(deck, session, entry, turn)
        _atomic_write(self.sessions_path, document)
        _atomic_write(self.vocabulary_path, deck)
        return {"status": "stored", "vocabulary": vocabulary, "deck": deck_status, "word": word_view(word, parse_moment(turn["at"]))}

    @staticmethod
    def _add_scene_word(
        deck: dict[str, Any], session: dict[str, Any], entry: dict[str, Any], turn: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        """Put one scene word into the deck, with an undo snapshot that also knows its scene entry."""
        key = word_key(entry["term"])
        known = next((item for item in deck["words"] if item.get("key") == key), None)
        previous = copy.deepcopy({field: value for field, value in known.items() if field != "undo"}) if known else None
        moment = parse_moment(turn["at"])
        source = {"session_id": session["id"], "scenario": session.get("scenario"), "turn_id": turn["id"],
                  "surface": entry.get("surface"), "example": turn["text"], "at": turn["at"]}
        word, deck_status = learn_word(deck["words"], term=entry["term"], meaning=entry["meaning"], source=source, moment=moment)
        word["undo"] = {"action": "add", "at": iso(moment), "state": previous, "scene": {"session_id": session["id"], "key": key}}
        return word, deck_status

    # ---- word deck

    def vocab_list(self, *, status: str = "all") -> list[dict[str, Any]]:
        if status not in {"active", "mastered", "all"}:
            raise DeutschLoopError("status must be active, mastered, or all")
        words = [word for word in self._vocabulary_document()["words"] if status == "all" or word.get("status") == status]
        return sorted(words, key=lambda word: (word.get("status") != "active", word.get("next_review") or "~", word["key"]))

    def vocab_due(self, *, at: datetime | None = None, limit: int = 5) -> list[dict[str, Any]]:
        moment = at or utc_now()
        due = [word for word in self._vocabulary_document()["words"] if _is_due(word, moment)]
        due.sort(key=lambda word: (word.get("next_review") or "", -int(word.get("wrong", 0)), word["key"]))
        return due[: max(0, limit)]

    @staticmethod
    def _require_word(words: list[dict[str, Any]], identifier: str) -> dict[str, Any]:
        word = next((item for item in words if item.get("id") == identifier), None)
        if word is None:
            raise DeutschLoopError(f"Unknown word ID: {identifier}")
        return word

    def vocab_grade(
        self, identifier: str, *, result: str, prompt: str, answer: str,
        correction: str | None = None, at: datetime | None = None,
    ) -> tuple[dict[str, Any], str]:
        """A word review: the learner produced the word in a sentence for a new situation."""
        if result not in {"pass", "hard", "fail"}:
            raise DeutschLoopError("result must be pass, hard, or fail")
        prompt, answer = prompt.strip(), answer.strip()
        correction = (correction or "").strip() or None
        if not prompt or not answer:
            raise DeutschLoopError("A word review requires the actual --prompt and the learner's --answer")
        moment = at or utc_now()
        document = self._vocabulary_document()
        word = self._require_word(document["words"], identifier)
        history = word.get("review_history") or []
        last = history[-1] if history else None
        if (last and (last.get("result"), last.get("prompt"), last.get("answer"), last.get("correction")) == (result, prompt, answer, correction)
                and within(last.get("reviewed_at"), moment, DUPLICATE_EVENT_WINDOW)):
            return word, "duplicate"
        if not _is_due(word, moment):
            raise DeutschLoopError("This word is not due; review it when vocab-due lists it")
        if text_fingerprint(prompt) in word.get("seen_prompts", []):
            raise DeutschLoopError("This word prompt was already used; ask a new situation")
        if result == "pass" and text_fingerprint(answer) in word.get("seen_answers", []):
            raise DeutschLoopError("This sentence was already seen; a pass needs a new sentence")
        _snapshot(word, "grade", moment)
        if result == "pass":
            step = int(word.get("review_step", 0)) + 1
            word["review_step"] = step
            word["right"] = int(word.get("right", 0)) + 1
            if step >= len(REVIEW_INTERVALS):
                word.update({"status": "mastered", "next_review": None, "mastered_at": iso(moment)})
            else:
                word["next_review"] = iso(moment + timedelta(days=REVIEW_INTERVALS[step]))
        elif result == "hard":
            word["next_review"] = iso(moment + timedelta(days=REVIEW_INTERVALS[0]))
        else:
            word["review_step"] = 0
            word["wrong"] = int(word.get("wrong", 0)) + 1
            word["next_review"] = iso(moment + timedelta(days=REVIEW_INTERVALS[0]))
        word["last_reviewed"] = iso(moment)
        entry = {"result": result, "reviewed_at": iso(moment), "prompt": prompt, "answer": answer}
        if correction:
            entry["correction"] = correction
        word["review_history"] = (history + [entry])[-HISTORY_LIMIT:]
        for field, text in (("seen_prompts", prompt), ("seen_answers", answer), ("seen_answers", correction)):
            remember_text(word, field, text)
        _atomic_write(self.vocabulary_path, document)
        return word, "graded"

    def vocab_undo(self, identifier: str) -> dict[str, Any]:
        """Revert the latest grade, or the scene addition, of one word. One level deep."""
        document = self._vocabulary_document()
        word = self._require_word(document["words"], identifier)
        snapshot = word.get("undo")
        if not snapshot:
            raise DeutschLoopError(f"Nothing to undo for {identifier}: only its latest grade or scene addition can be undone")
        undone = {"undone": snapshot.get("action"), "undone_at": snapshot.get("at")}
        if snapshot.get("action") == "add":
            scene = snapshot.get("scene") or {}
            self._remove_scene_words(scene.get("key") or word["key"], scene.get("session_id"))
        if snapshot.get("state") is None:
            document["words"] = [item for item in document["words"] if item.get("id") != identifier]
            _atomic_write(self.vocabulary_path, document)
            return {"status": "removed", **undone, "word": word}
        restored = snapshot["state"]
        document["words"][document["words"].index(word)] = restored
        _atomic_write(self.vocabulary_path, document)
        return {"status": "undone", **undone, "word": restored}

    def vocab_forget(self, identifier: str) -> dict[str, Any]:
        """Remove a wrongly saved word from the deck and from every scene report that lists it."""
        document = self._vocabulary_document()
        word = self._require_word(document["words"], identifier)
        # Scene reports first: if the second write fails, a retry still finds the card and finishes.
        self._remove_scene_words(word["key"])
        document["words"] = [item for item in document["words"] if item.get("id") != identifier]
        _atomic_write(self.vocabulary_path, document)
        return word

    def roleplay_show(self, identifier: str, *, at: datetime | None = None) -> dict[str, Any]:
        session = self._require_session(self._session_document(), identifier)
        result = {"session": session, **session_timing(session, at or utc_now())}
        result["debrief"] = session_debrief(
            session, self._mistake_document()["mistakes"], self._vocabulary_document()["words"]
        ) if session.get("status") == "complete" else None
        # Persisting a report is not the same as showing it in a chat response.
        # Provide ready-to-display text even to agents using the JSON default.
        ready = result["debrief"] is not None
        result["learner_message"] = render_roleplay_text(result) if ready else None
        result["response_required"] = ready
        result["next_action"] = "present_debrief" if ready else (
            "prepare_debrief" if session.get("status") == "debriefing" else "continue_scene"
        )
        return result

    def roleplay_finish(
        self,
        identifier: str,
        *,
        turns: int | None = None,
        duration_seconds: int | None = None,
        mistake_ids: list[str] | None = None,
        notes: str | None = None,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        moment = at or utc_now()
        document = self._session_document()
        session = self._require_session(document, identifier)
        if session.get("status") == "complete":
            return session
        ended = _safe_moment(session.get("ended_at")) or moment
        started = _safe_moment(session.get("started_at"))
        if moment < ended:
            raise DeutschLoopError("Feedback cannot be finished before the scene ended")
        if started and ended < started:
            raise DeutschLoopError("A scene cannot end before it starts")
        if session.get("utterances"):
            if ended < parse_moment(session["utterances"][-1]["at"]):
                raise DeutschLoopError("A scene cannot end before its last turn")
            count = session_timing(session, ended)["learner_turns"]
            if turns is not None and turns != count:
                raise DeutschLoopError("The supplied turn count disagrees with the recorded learner turns")
            if duration_seconds is not None:
                raise DeutschLoopError("Recorded scenes use elapsed time; speaking duration is not measured")
            turns = count
        elif turns is None:
            turns = 0
        duration_source = "provided" if duration_seconds is not None else "elapsed"
        if duration_seconds is None and started is not None:
            duration_seconds = max(0, int((ended - started).total_seconds()))
        linked = [item["mistake_id"] for item in session.get("feedback", [])]
        session.update(
            {
                "status": "complete",
                "ended_at": iso(ended),
                "finished_at": iso(moment),
                "turns": max(0, turns),
                "duration_seconds": max(0, duration_seconds) if duration_seconds is not None else None,
                "duration_source": duration_source,
                "mistake_ids": list(dict.fromkeys((mistake_ids or []) + linked)),
                "notes": notes,
            }
        )
        _atomic_write(self.sessions_path, document)
        return session


# --------------------------------------------------------------------------- correction analysis


def tokenize(text: str) -> list[str]:
    return re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE)


def analyze_correction(original: str, corrected: str) -> dict[str, Any]:
    before = tokenize(original)
    after = tokenize(corrected)
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    changes = []
    changed_before = 0
    changed_after = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changed_before += i2 - i1
        changed_after += j2 - j1
        changes.append(
            {
                "operation": tag,
                "original_tokens": before[i1:i2],
                "corrected_tokens": after[j1:j2],
            }
        )
    denominator = max(1, len(before), len(after))
    edit_ratio = round(max(changed_before, changed_after) / denominator, 3)
    similarity = round(matcher.ratio(), 3)
    minimality_status = "minimal" if edit_ratio <= 0.35 and similarity >= 0.65 else "possible_rewrite"
    return {
        "original_tokens": len(before),
        "corrected_tokens": len(after),
        "changed_token_ratio": edit_ratio,
        "similarity": similarity,
        "minimality_status": minimality_status,
        "changes": changes,
    }


def minimality_view(original: str, corrected: str) -> dict[str, Any]:
    """Whether a correction changed only what grammar required; agents reconsider a `possible_rewrite`."""
    analysis = analyze_correction(original, corrected)
    return {
        "status": analysis["minimality_status"],
        "changed_token_ratio": analysis["changed_token_ratio"],
        "changes": analysis["changes"],
    }


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def variety_note(mistake: dict[str, Any], *, prompt: str, answer: str) -> dict[str, Any] | None:
    """Flag a task or answer that reuses an earlier sentence frame; exact reuse is already rejected.

    `Die Planung ist wichtig.` after `Die Einladung ist wichtig.` passes the exact-text check
    but tests the same frame again, not transfer to a new situation.
    """
    earlier: list[tuple[str, str, str | None]] = []
    for entry in mistake.get("review_history", []) + mistake.get("coaching_history", []):
        stamp = entry.get("reviewed_at") or entry.get("at")
        earlier.extend((field, entry[field], stamp) for field in ("prompt", "answer") if entry.get(field))
    for example in mistake.get("examples", []):
        earlier.extend(("answer", example[field], example.get("seen_at")) for field in ("original", "corrected") if example.get(field))
    for entry in mistake.get("correct_use_history", []):
        if entry.get("context"):
            earlier.append(("answer", entry["context"], entry.get("observed_at")))
    current = {"prompt": _words(prompt), "answer": _words(answer)}
    best = None
    for field, text, stamp in earlier:
        words = current[field]
        if len(words) < VARIETY_MIN_WORDS:
            continue
        other = _words(text)
        similarity = len(words & other) / len(words | other)
        if similarity >= VARIETY_WARNING_THRESHOLD and (best is None or similarity > best["similarity"]):
            best = {"field": field, "similar_to": text, "at_local": local_iso(stamp), "similarity": round(similarity, 2)}
    return best


# --------------------------------------------------------------------------- text rendering


def render_bar(percent: int, width: int = 10) -> str:
    filled = max(0, min(width, round(width * percent / 100)))
    return "█" * filled + "░" * (width - filled)


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _in_a_row(days: int) -> str:
    return f"{_plural(days, 'Tag', 'Tage')} in Folge"


def _heading(profile: dict[str, Any]) -> list[str]:
    """The card title: the learner's name and level only when they gave them."""
    parts = ["FehlerDNA"]
    if profile.get("name"):
        parts.append(profile["name"])
    if profile.get("level") and profile["level"] != "unspecified":
        parts.append(profile["level"])
    return parts


def _label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)


def _join_limited(items: list[str], limit: int, total: int | None = None) -> str:
    shown = " · ".join(items[:limit])
    hidden = (len(items) if total is None else total) - min(limit, len(items))
    if hidden > 0:
        shown += f" · +{hidden} weitere"
    return shown


def _cluster_detail(cluster: dict[str, Any], recent_total: int) -> str:
    recent_errors = cluster.get("recent_errors", 0)
    if recent_errors and recent_total:
        return (
            f"{recent_errors} von {recent_total} Fehlern der letzten {CLUSTER_WINDOW.days} Tage · "
            f"{_plural(cluster.get('recent_patterns', 0), 'verwandtes Muster', 'verwandte Muster')}"
        )
    return (f"{_plural(len(cluster['patterns']), 'verwandtes Muster', 'verwandte Muster')} · "
            f"{_plural(cluster['occurrences'], 'Fehler', 'Fehler')}")


def _score(accuracy: int, is_new: bool) -> str:
    """Fixed-width score column: a bar with a percentage, or "neu" when nothing is measured yet."""
    return "neu".ljust(15) if is_new else f"{render_bar(accuracy)} {accuracy:>3}%"


def render_summary_text(summary: dict[str, Any]) -> str:
    lines = [
        " · ".join(_heading(summary["profile"])),
        (
            f"{_plural(summary['total_patterns'], 'Muster', 'Muster')} · {summary['mastered_patterns']} gemeistert · "
            f"{summary['errors_total']}× falsch · {summary['correct_total']}× richtig · "
            f"{_in_a_row(summary['streak_days'])} · {summary['due_now']} fällig"
        ),
        "",
    ]
    categories = summary["categories"]
    if not categories:
        lines.append("Noch keine Fehler gespeichert. Deine FehlerDNA entsteht, während du schreibst.")
        return "\n".join(lines + _vocabulary_lines(summary))
    for category in sorted(categories, key=category_rank):
        bucket = categories[category]
        line = (
            f"{_label(category):<16}{_score(bucket['accuracy_percent'], bucket.get('new', False))}   "
            f"{_plural(bucket['patterns'], 'Muster', 'Muster'):<9} · {bucket['mastered']} gemeistert · "
            f"{bucket['errors']}× falsch · {bucket['correct']}× richtig"
        )
        if bucket["weak"]:
            line += "   ← schwach"
        lines.append(line)
    clusters = summary["clusters"]
    recent_total = summary.get("recent_errors_total", 0)
    if clusters:
        top = clusters[0]
        lines.append("")
        lines.append(f"Ursache: {_label(top['category'])} · {_cluster_detail(top, recent_total)}")
        for name in top.get("labels", top["patterns"])[:4]:
            lines.append(f"  → {name}")
        if len(top["patterns"]) > 4:
            lines.append(f"  → +{len(top['patterns']) - 4} weitere")
        for cluster in clusters[1:2]:
            lines.append(f"Außerdem: {_label(cluster['category'])} · {_cluster_detail(cluster, recent_total)}")
    weakest = [row for row in summary["weakest_patterns"] if not row.get("new")][:3]
    if weakest:
        lines.append("")
        lines.append("Schwächste Muster")
        width = max(len(row["label"]) for row in weakest)
        for row in weakest:
            lines.append(
                f"  {row['label']:<{width}}  {row['accuracy_percent']:>3}%  "
                f"{row['occurrences']}× falsch · {row['right']}× richtig · Stufe {row['review_step']}/{row['review_steps_total']}"
            )
    if summary["due_patterns"]:
        names = [row["label"] for row in summary["due_patterns"]]
        lines.append("")
        lines.append("Jetzt fällig: " + _join_limited(names, 3, summary["due_now"]))
    return "\n".join(lines + _vocabulary_lines(summary))


def render_recap_text(recap: dict[str, Any]) -> str:
    name = recap["profile"].get("name")
    gap = recap["days_since_last_activity"]
    if gap is None:
        return (f"Willkommen, {name}!" if name else "Willkommen!") + (
            "\nNoch keine Einträge. Schreib ein paar Sätze auf Deutsch, dann entsteht deine FehlerDNA."
        )
    when = "heute" if gap == 0 else ("gestern" if gap == 1 else f"vor {gap} Tagen")
    errors = recap["errors"]
    reviews = recap["reviews"]
    word_reviews = recap.get("word_reviews") or {"total": 0}
    practice = (
        f"Letzte {recap['window_days']} Tage: {_plural(errors['total'], 'Fehler', 'Fehler')} "
        f"({errors['new_patterns']} neu, {errors['recurrences']} wiederholt) · "
        f"{_plural(reviews['total'], 'Wiederholung', 'Wiederholungen')} ({reviews['pass']} bestanden) · "
    )
    if word_reviews["total"]:
        practice += (f"{_plural(word_reviews['total'], 'Wortwiederholung', 'Wortwiederholungen')} "
                     f"({word_reviews['pass']} bestanden) · ")
    practice += (
        f"{_plural(recap['correct_uses'], 'richtige Verwendung', 'richtige Verwendungen')} · "
        f"{_plural(recap['roleplays']['count'], 'Rollenspiel', 'Rollenspiele')}"
    )
    lines = [
        f"Willkommen zurück, {name}." if name else "Willkommen zurück.",
        f"Zuletzt geübt: {when} · {_in_a_row(recap['streak_days'])}",
        practice,
    ]
    if recap["recurring_patterns"]:
        names = [
            row.get("label", row["pattern"]) + (f" ×{row['count']}" if row["count"] > 1 else "")
            for row in recap["recurring_patterns"]
        ]
        lines.append("Wieder da: " + _join_limited(names, 2, recap.get("recurring_total")))
    if recap["mastered"]:
        lines.append("Gemeistert: " + _join_limited(recap.get("mastered_labels") or recap["mastered"], 3))
    words_due = (recap.get("vocabulary") or {}).get("due_now")
    if recap["due_now"]:
        lines.append(f"{_plural(recap['due_now'], 'Fehler', 'Fehler')} zum Wiederholen fällig · 5-Minuten-Challenge?")
    elif recap["next_focus"]:
        lines.append(f"{'Keine Fehler' if words_due else 'Nichts'} fällig. Gerade am schwächsten: {recap['next_focus']['label']}")
    if words_due:
        lines.append(f"{_plural(words_due, 'Wort', 'Wörter')} aus deinen Szenen zum Wiederholen fällig")
    return "\n".join(lines)


def _fit(value: str, width: int) -> str:
    return value if len(value) <= width else value[: width - 1] + "…"


def _ladder(step: int) -> str:
    filled = max(0, min(step, len(REVIEW_INTERVALS)))
    return "▰" * filled + "▱" * (len(REVIEW_INTERVALS) - filled)


def _when_due(row: dict[str, Any], now_local: datetime) -> str:
    if row.get("due"):
        return "jetzt fällig"
    stamp = row.get("next_review_local")
    if not stamp:
        return "-"
    moment = datetime.fromisoformat(stamp)
    days = (moment.date() - now_local.date()).days
    if days <= 0:
        return f"heute {moment:%H:%M}"
    if days == 1:
        return f"morgen {moment:%H:%M}"
    if days < 7:
        return f"{WEEKDAYS_DE[moment.weekday()]} {moment:%H:%M}"
    return f"{moment:%d.%m.}"


def render_recap_card(recap: dict[str, Any]) -> str:
    """The session header and a board of the patterns in progress. Every value comes from the recap."""
    head = _heading(recap["profile"])
    if recap.get("last_activity_at") is None:
        return " · ".join(head) + "\nNoch keine Einträge. Schreib ein paar Sätze auf Deutsch, dann entsteht deine FehlerDNA."
    return "\n".join(_recap_card_lines(recap, head) + _vocabulary_lines(recap))


def _vocabulary_lines(result: dict[str, Any]) -> list[str]:
    """One line about the word deck under a card, or nothing while the deck is empty."""
    overview = result.get("vocabulary") or {}
    if not overview.get("total"):
        return []
    parts = [f"Wortschatz: {_plural(overview['total'], 'Wort', 'Wörter')}"]
    if overview["due_now"]:
        parts.append(f"{overview['due_now']} fällig")
    elif overview.get("next_local"):
        now_local = to_local(parse_moment(result["as_of"]))
        parts.append(f"nächste Wiederholung {_when_due({'next_review_local': overview['next_local']}, now_local)}")
    if overview["mastered"]:
        parts.append(f"{overview['mastered']} gemeistert")
    return ["", " · ".join(parts)]


def _recap_card_lines(recap: dict[str, Any], head: list[str]) -> list[str]:
    streak = recap["streak_days"]
    if streak:
        head.append(_in_a_row(streak))
    else:
        head.append(f"zuletzt vor {recap['days_since_last_activity']} Tagen")
    total = recap["active_patterns"] + recap["mastered_total"]
    head.append(f"{recap['mastered_total']} von {total} gemeistert")
    lines = [" · ".join(head)]
    board = recap.get("board") or []
    if board:
        now_local = to_local(parse_moment(recap["as_of"]))
        width = min(LABEL_WIDTH, max(len(row["label"]) for row in board))
        lines.append("")
        for row in board:
            wrong = f"{row['occurrences']}× falsch" + (" ↺" if row.get("came_back") else "")
            lines.append(
                f"{_fit(row['label'], width):<{width}}  {_ladder(row['review_step'])} "
                f"{row['review_step']}/{row['review_steps_total']}   {wrong:<11}   {_when_due(row, now_local)}"
            )
        if recap.get("board_more"):
            lines.append(f"+{recap['board_more']} weitere")
    elif recap["mastered_total"]:
        lines.append("")
        lines.append("Alles gemeistert ★ Schreib etwas Neues, dann suche ich die nächste Baustelle.")
    return lines


def render_due_text(result: dict[str, Any]) -> str:
    if not result["mistakes"]:
        return "Gerade ist nichts fällig."
    lines = [f"Jetzt fällig: {result['count']}"]
    for index, mistake in enumerate(result["mistakes"], start=1):
        # Accepts both full records (--verbose) and the compact rows agents get by default.
        row = compact(mistake) if "examples" in mistake else mistake
        lines.append(f"{index}. {row['label']}  [{_label(row['category'])}]  {row['id']}")
        lines.append(f"   Regel: {row['rule']}")
        example = row["last_example"]
        if example and example.get("original"):
            lines.append(f"   Zuletzt: {example['original']} → {example.get('corrected') or '?'}")
        lines.append(
            f"   {row['occurrences']}× falsch · {row['right']}× richtig · Stufe {row['review_step']}/{row['review_steps_total']}"
        )
    return "\n".join(lines)


def render_list_text(result: dict[str, Any]) -> str:
    rows = result["mistakes"]
    if not rows:
        return "No patterns match."
    header = f"{'ID':<15}{'STATUS':<10}{'CATEGORY':<13}{'PATTERN':<42}{'WRONG':>6}{'RIGHT':>6}  {'STEP':<5} {'NEXT':<10}"
    lines = [header]
    for row in rows:
        pattern = row["pattern"] if len(row["pattern"]) <= 40 else row["pattern"][:39] + "…"
        next_review = (row.get("next_review_local") or "")[:10] or "-"
        lines.append(
            f"{row['id']:<15}{row['status']:<10}{row['category']:<13}{pattern:<42}"
            f"{row['occurrences']:>6}{row['right']:>6}  {row['review_step']}/{row['review_steps_total']:<3} {next_review:<10}"
        )
    return "\n".join(lines)


def _event(marker: str, word: str, text: str = "") -> str:
    return f"{marker} {word:<14} {text}".rstrip()


def render_show_text(result: dict[str, Any]) -> str:
    """The journey of one pattern: first mistake, every review, real-life use, mastery.

    Learner-facing, so every line is German; the stored English rule stays in the JSON.
    """
    mistake = result["mistake"]
    row = compact(mistake)
    mastered = mistake.get("status") == "mastered"
    lines = [f"{row['label']} · {_label(mistake['category'])} · {'gemeistert' if mastered else 'wird geübt'}", ""]
    first = mistake.get("first_example")
    if first:
        label = "Erster Fehler" if first.get("seen_at") == mistake.get("first_seen") else "Frühester erhaltener Fehler"
        lines.append(f"{label} · {(local_iso(first.get('seen_at')) or '')[:10]}: {first.get('original')}")
        lines.append("")
    events: list[tuple[str, int, str]] = []
    failed_review_stamps = set()
    for example in mistake.get("examples", []):
        stamp = example.get("seen_at") or ""
        original, corrected = example.get("original"), example.get("corrected")
        pair = f"{original} → {corrected or '?'}" if original else ""
        if example.get("context") == REVIEW_CONTEXT:
            failed_review_stamps.add(stamp)
            events.append((stamp, 0, _event("✗", "Wiederholung", pair)))
        else:
            events.append((stamp, 0, _event("✗", "Fehler", pair)))
    for entry in mistake.get("review_history", []):
        if entry.get("source", "review") != "review":
            continue
        stamp = entry.get("reviewed_at") or ""
        answer = entry.get("answer") or ""
        outcome = entry.get("result")
        if outcome == "pass":
            events.append((stamp, 1, _event("✓", "Wiederholung", answer or "bestanden")))
        elif outcome == "hard":
            support_label = "nach einem Hinweis" if entry.get("hint") else "mit Zögern"
            events.append((stamp, 1, _event("~", "Wiederholung", f"{answer + ' ' if answer else ''}({support_label})")))
        elif outcome == "fail" and stamp not in failed_review_stamps:
            events.append((stamp, 1, _event("✗", "Wiederholung", "nicht bestanden")))
    for entry in mistake.get("correct_use_history", []):
        events.append((entry.get("observed_at") or "", 2, _event("✓", "frei benutzt", entry.get("context") or "")))
    supported_reviews = {
        (entry.get("reviewed_at"), entry.get("prompt"))
        for entry in mistake.get("review_history", []) if entry.get("hint")
    }
    practice_labels = {
        "independent": ("✓", "ohne Hilfe"), "assisted": ("~", "mit Hinweis"),
        "shown": ("→", "Lösung gezeigt"), "miss": ("~", "noch offen"),
    }
    for entry in mistake.get("coaching_history", []):
        if (entry.get("at"), entry.get("prompt")) not in supported_reviews:
            events.append((entry.get("at") or "", 2, _event(*practice_labels[entry["outcome"]], entry["answer"])))
    for field, marker in (
        ("previously_mastered_at", "★ gemeistert"),
        ("mastered_at", "★ gemeistert"),
        ("reactivated_at", "↺ nach dem Meistern zurück"),
    ):
        if mistake.get(field):
            events.append((mistake[field], 3, marker))
    events.sort(key=lambda item: (item[0], item[1]))
    hidden = max(0, len(events) - TIMELINE_LIMIT)
    if hidden:
        lines.append(f"… {_plural(hidden, 'früheres Ereignis', 'frühere Ereignisse')}")
    for stamp, _, text in events[hidden:]:
        lines.append(f"{(local_iso(stamp) or stamp)[:10]}  {text}")
    support = mistake.get("helpful_hint")
    if support:
        lines.extend(["", f"Hilfreicher Hinweis ({support['strategy']}): {support['hint']}"])
    proof = learning_proof_view(mistake.get("learning_proof"))
    if proof:
        before, after = proof["with_help"], proof["independent"]
        source = "frei geschrieben" if after["source"] == "spontaneous" else "neue Aufgabe"
        lines.extend([
            f"Mit Hilfe · {before['at_local'][:10]}: {before['answer']}",
            f"Ohne Hilfe · {after['at_local'][:10]} ({source}): {after['answer']}",
        ])
    progress = "gemeistert" if mastered else f"Stufe {row['review_step']}/{row['review_steps_total']}"
    score = "neu" if row["new"] else f"{render_bar(row['accuracy_percent'])} {row['accuracy_percent']}%"
    lines.append("")
    lines.append(f"{score} · {row['occurrences']}× falsch · {row['right']}× richtig · {progress}")
    return "\n".join(lines)


def render_roleplay_text(result: dict[str, Any]) -> str:
    debrief = result.get("debrief")
    if not debrief:
        if result.get("session", {}).get("status") == "debriefing":
            return "Die Szene ist beendet. Die Auswertung wird vorbereitet."
        return "Die Szene läuft noch. Sag Bescheid, wenn du aufhören möchtest."
    seconds = debrief["duration_seconds"]
    duration = f"{seconds // 60}m {seconds % 60:02d}s" if seconds is not None else "unbekannt"
    timing_label = "Dauer der Szene" if debrief["duration_source"] == "elapsed" else "Angegebene Dauer"
    lines = ["AUSWERTUNG DER SZENE", f"{debrief['scenario'].capitalize()} · {timing_label}: {duration}",
             f"Deine Antworten: {debrief['learner_turns']}", "", f"Wichtige Korrekturen: {len(debrief['corrections'])}"]
    for index, item in enumerate(debrief["corrections"], 1):
        example = item["example"]
        lines.extend([f"{index}. {item['label']}", f"   {example['original']}", f"   → {example['corrected']}"])
    if not debrief["corrections"]:
        lines.append("Keine bestätigten Fehler für diese Szene gespeichert.")
    if debrief["vocabulary"]:
        lines.extend(["", "Wortschatz aus dieser Szene"])
        lines.extend(f"{item['term']} — {item['meaning']}" + (" · schon gemeistert" if item.get("review") == "mastered" else "")
                     for item in debrief["vocabulary"])
        reviewed = [item for item in debrief["vocabulary"] if item.get("review") == "active"]
        if reviewed:
            everyone = len(reviewed) == len(debrief["vocabulary"])
            lines.append(f"{'Diese' if everyone else 'Die übrigen'} Wörter kommen in deiner Wiederholung in neuen Sätzen zurück.")
    if debrief["recurring"]:
        lines.extend(["", "Wiederkehrende Muster"])
        for item in debrief["recurring"]:
            count = item["session_occurrences"]
            prior = " · aus früheren Übungen bekannt" if item["previously_tracked"] else ""
            lines.append(f"{item['label']} {'█' * min(count, 10)} {count}× in dieser Szene{prior}")
    return "\n".join(lines)


def _word_when(word: dict[str, Any], now_local: datetime) -> str:
    return "★ gemeistert" if word.get("status") == "mastered" else _when_due(word, now_local)


def render_vocab_list_text(result: dict[str, Any]) -> str:
    """The word deck: each word with its meaning, ladder, and next review."""
    overview = result["overview"]
    if not overview["total"]:
        return "Noch keine Wörter im Wortschatz. Die Wörter aus deinen Rollenspielen landen hier."
    head = [f"Wortschatz · {_plural(overview['total'], 'Wort', 'Wörter')}", f"{overview['due_now']} fällig"]
    if overview["mastered"]:
        head.append(f"{overview['mastered']} gemeistert")
    lines = [" · ".join(head)]
    words = result["words"]
    if words:
        now_local = to_local(parse_moment(result["as_of"]))
        term_width = min(LABEL_WIDTH, max(len(word["term"]) for word in words))
        meaning_width = min(LABEL_WIDTH, max(len(word["meaning"]) for word in words))
        lines.append("")
        for word in words:
            step = int(word.get("review_step", 0))
            lines.append(
                f"{_fit(word['term'], term_width):<{term_width}}  {_fit(word['meaning'], meaning_width):<{meaning_width}}  "
                f"{_ladder(step)} {step}/{len(REVIEW_INTERVALS)}   {_word_when(word, now_local)}"
            )
    return "\n".join(lines)


def render_vocab_due_text(result: dict[str, Any]) -> str:
    if not result["words"]:
        return "Gerade sind keine Wörter fällig."
    lines = [f"Fällige Wörter: {result['count']}"]
    for index, word in enumerate(result["words"], start=1):
        lines.append(f"{index}. {word['term']} — {word['meaning']}  {word['id']}")
        source = word.get("source") or ((word.get("sources") or [None])[-1])
        if source and source.get("example"):
            scenario = (source.get("scenario") or "").capitalize()
            lines.append(f"   Aus der Szene{f' ({scenario})' if scenario else ''}: „{source['example']}“")
        lines.append(f"   Stufe {int(word.get('review_step', 0))}/{len(REVIEW_INTERVALS)} · {int(word.get('wrong', 0))}× falsch")
    return "\n".join(lines)


TEXT_RENDERERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "summary": render_summary_text,
    "recap": render_recap_text,
    "due": render_due_text,
    "list": render_list_text,
    "show": render_show_text,
    "roleplay-show": render_roleplay_text,
    "roleplay-finish": render_roleplay_text,
    "vocab-list": render_vocab_list_text,
    "vocab-due": render_vocab_due_text,
}
CARD_RENDERERS: dict[str, Callable[[dict[str, Any]], str]] = {"recap": render_recap_card}


# --------------------------------------------------------------------------- portable learning dashboard


def dashboard_snapshot(store: StateStore, *, at: datetime | None = None) -> dict[str, Any]:
    """Project saved evidence without initializing, migrating on disk, or grading anything."""
    moment = at or utc_now()
    profile = _read_json(store.profile_path, {})
    document = _read_json(store.mistakes_path, {"schema_version": SCHEMA_VERSION, "mistakes": []})
    if not isinstance(document.get("mistakes"), list):
        raise DeutschLoopError(f"Expected a mistakes list in {store.mistakes_path}")
    mistakes = _migrate_mistakes(drop_legacy_fields(document))["mistakes"]
    patterns = []
    for mistake in mistakes:
        row = compact(mistake)
        events: list[dict[str, Any]] = []
        known: set[tuple[str, str, str]] = set()

        def add(kind: str, stamp: str | None, sentence: str | None, **details: Any) -> None:
            if not stamp or not _safe_moment(stamp):
                return
            key = (kind, stamp, sentence or "")
            if key in known:
                return
            known.add(key)
            events.append({"kind": kind, "at": stamp, "at_local": local_iso(stamp),
                           "sentence": sentence, **details})

        first = mistake.get("first_example")
        for example in ([first] if first else []) + list(mistake.get("examples") or []):
            add("error", example.get("seen_at"), example.get("original"), corrected=example.get("corrected"))
        for entry in list(mistake.get("coaching_history") or []) + ([mistake["helpful_hint"]] if mistake.get("helpful_hint") else []):
            kind = {"independent": "practice", "assisted": "assisted", "shown": "shown", "miss": "miss"}[entry["outcome"]]
            add(kind, entry.get("at"), entry.get("answer"), hint=entry.get("hint"),
                strategy=entry.get("strategy"), prompt=entry.get("prompt"))
        for entry in mistake.get("correct_use_history") or []:
            add("spontaneous", entry.get("observed_at"), entry.get("context"))
        for entry in mistake.get("review_history") or []:
            if entry.get("source", "review") != "review":
                continue  # A spontaneous use already has its own evidence above.
            kind = {"pass": "review", "hard": "assisted" if entry.get("hint") else "hesitant", "fail": "error"}[entry["result"]]
            add(kind, entry.get("reviewed_at"), entry.get("answer"), hint=entry.get("hint"),
                strategy=entry.get("strategy"), prompt=entry.get("prompt"), corrected=entry.get("correction"))
        proof = row["coaching"]["learning_proof"]
        if proof:
            supported, independent = proof["with_help"], proof["independent"]
            add("assisted", supported.get("at"), supported.get("answer"), hint=supported.get("hint"),
                strategy=supported.get("strategy"), prompt=supported.get("prompt"))
            add({"spontaneous": "spontaneous", "review": "review", "practice": "practice"}[independent["source"]],
                independent.get("at"), independent.get("answer"), prompt=independent.get("prompt"))
        for field, kind in (("mastered_at", "mastered"), ("previously_mastered_at", "mastered"), ("reactivated_at", "returned")):
            add(kind, mistake.get(field), None)
        events.sort(key=lambda event: (parse_moment(event["at"]), event["kind"]))
        row.update({"category_label": CATEGORY_LABELS.get(row["category"], row["category"]),
                    "due": _is_due(mistake, moment), "events": events,
                    "first_example_is_original": bool(first and first.get("seen_at") == mistake.get("first_seen")),
                    "proof_has_later_error": bool(proof and _safe_moment(mistake.get("last_seen"))
                                                  and parse_moment(mistake["last_seen"]) > parse_moment(proof["independent"]["at"]))})
        patterns.append(row)
    patterns.sort(key=lambda row: (not bool(row["coaching"]["learning_proof"]), not row["due"],
                                   category_rank(row["category"]), row["label"]))
    missions = store._mission_document()["missions"]
    sessions = _read_json(store.sessions_path, {"sessions": []})["sessions"] if missions else []
    return {"as_of": iso(moment), "as_of_local": local_iso(iso(moment)),
            "profile": {"name": profile.get("name"), "level": profile.get("level")},
            "counts": {"patterns": len(patterns), "due": sum(row["due"] for row in patterns),
                       "mastered": sum(row["status"] == "mastered" for row in patterns),
                       "milestones": sum(bool(row["coaching"]["learning_proof"]) for row in patterns)},
            "patterns": patterns,
            "missions": [mission_view(item, moment, sessions) for item in missions if item["status"] != "cancelled"],
            "scenarios": scenario_examples()}


def render_dashboard(payload: dict[str, Any]) -> str:
    """Keep learner text inert, including a literal closing script tag or HTML markup."""
    template = Path(__file__).with_name("dashboard.html").read_text(encoding="utf-8")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    for original, escaped in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"),
                              ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        data = data.replace(original, escaped)
    return template.replace("__DEUTSCHLOOP_DATA__", data)


def write_dashboard(payload: dict[str, Any], output: Path, *, force: bool = False) -> dict[str, Any]:
    output = output.expanduser().resolve()
    if output.suffix.lower() not in {".html", ".htm"}:
        raise DeutschLoopError("Dashboard output must end in .html or .htm")
    if output == Path(__file__).with_name("dashboard.html").resolve():
        raise DeutschLoopError("Choose an output outside the dashboard source template")
    if output.exists() and not force:
        raise DeutschLoopError(f"{output} already exists; choose another file or use --force")
    temporary = output.parent / f".{output.name}.{uuid.uuid4().hex}.tmp"
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        html = render_dashboard(payload)
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(html)
        if force:
            _replace_file(temporary, output)
        else:
            # An exclusive create also protects against another export arriving after exists().
            with output.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(html)
    except OSError as exc:
        raise DeutschLoopError(f"Could not export dashboard to {output}: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return {"status": "exported", "path": str(output), "frames": len(payload["frames"]),
            "patterns": payload["frames"][-1]["counts"]["patterns"], "demo": payload.get("demo", False)}


# --------------------------------------------------------------------------- CLI


def _configure_streams() -> None:
    """Force UTF-8 output so JSON never crashes on legacy Windows console code pages."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def _print_json(value: Any, *, stream: Any = None) -> None:
    """Indented in a terminal; compact when piped to an agent, where whitespace only costs tokens."""
    target = stream or sys.stdout
    isatty = getattr(target, "isatty", None)
    if isatty is not None and isatty():
        text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    print(text, file=target)


def _add_format(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=("json", "text"), default="json", help="json for agents, text for humans")


def _add_verbose(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--verbose", action="store_true",
                        help="Full pattern records and detailed rows instead of the compact agent view")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DeutschLoop local mistake memory and review engine")
    parser.add_argument("--home", help="State directory; overrides DEUTSCHLOOP_HOME")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create or update the learner profile")
    init_parser.add_argument("--name")
    init_parser.add_argument("--native-language")
    init_parser.add_argument("--level")
    init_parser.add_argument("--goal", help="The learner's stated real-life goal; empty string clears it")
    init_parser.add_argument("--explanation-language", help="Language for onboarding and explanations, independent of native language")
    init_parser.add_argument("--starting-point", choices=sorted(STARTING_POINTS), help="Learner's starting preference; never sets a CEFR level")
    init_parser.add_argument("--welcome-shown", action="store_true", help="Remember that the short introduction was shown")
    init_parser.add_argument("--onboarding-complete", action="store_true", help="Mark the first actual German practice as completed, even without errors")
    init_parser.add_argument("--at", help="ISO-8601 time, primarily for deterministic integrations")

    record_parser = subparsers.add_parser("record", help="Record or recur a root-cause mistake pattern")
    record_parser.add_argument("--original", required=True)
    record_parser.add_argument("--corrected", required=True)
    record_parser.add_argument("--mistake-id", help="Recur an existing pattern by ID instead of naming it")
    record_parser.add_argument("--category", choices=CATEGORY_ORDER)
    record_parser.add_argument("--pattern", help="Stable root-cause key, e.g. 'mit + dative'")
    record_parser.add_argument("--rule", help="One-line rule the learner should remember")
    record_parser.add_argument("--label", help="Short German name shown to the learner, e.g. 'hätte gern (höflich)'")
    record_parser.add_argument("--context")
    record_parser.add_argument("--event-id", help="Idempotency key; identical calls without one are deduplicated for 30 minutes")
    record_parser.add_argument("--session-id", help="Scene stopped for debrief; requires --turn-id")
    record_parser.add_argument("--turn-id", help="Actual learner turn containing the original sentence")
    record_parser.add_argument("--at", help="ISO-8601 event time")
    _add_verbose(record_parser)

    observe_parser = subparsers.add_parser("observe", help="Log a correct, unprompted use of tracked patterns")
    observe_parser.add_argument("mistake_ids", nargs="+")
    observe_parser.add_argument("--context", help="The learner's phrase; also used to deduplicate retries")
    observe_parser.add_argument("--at", help="ISO-8601 event time")

    coach_parser = subparsers.add_parser("coach", help="Remember guided or independent practice without changing the review schedule")
    coach_parser.add_argument("mistake_id")
    coach_parser.add_argument("--outcome", required=True, choices=("independent", "assisted", "shown", "miss"))
    coach_parser.add_argument("--prompt", required=True)
    coach_parser.add_argument("--answer", required=True)
    coach_parser.add_argument("--strategy", help="The teaching approach actually used")
    coach_parser.add_argument("--hint", help="The exact help given, including the answer if it was shown")
    coach_parser.add_argument("--at", help="ISO-8601 event time")
    _add_verbose(coach_parser)

    due_parser = subparsers.add_parser("due", help="List mistake patterns due for review")
    due_parser.add_argument("--limit", type=int, default=5)
    due_parser.add_argument("--at", help="ISO-8601 comparison time")
    _add_format(due_parser)
    _add_verbose(due_parser)

    grade_parser = subparsers.add_parser("grade", help="Grade a mistake review")
    grade_parser.add_argument("mistake_id")
    grade_parser.add_argument("--result", required=True, choices=("pass", "hard", "fail"))
    grade_parser.add_argument("--answer", help="The learner's answer; kept in the pattern's timeline")
    grade_parser.add_argument("--correction", help="Minimal correction of a failed answer")
    grade_parser.add_argument("--prompt", help="The actual new situation used for this review (required)")
    grade_parser.add_argument("--strategy", help="Teaching approach used for a hard or failed review")
    grade_parser.add_argument("--hint", help="The exact help given; hinted answers cannot pass")
    grade_parser.add_argument("--at", help="ISO-8601 review time")
    _add_verbose(grade_parser)

    list_parser = subparsers.add_parser("list", help="List tracked patterns compactly")
    list_parser.add_argument("--status", choices=("active", "mastered", "all"), default="active")
    list_parser.add_argument("--category", choices=CATEGORY_ORDER)
    _add_format(list_parser)
    _add_verbose(list_parser)

    show_parser = subparsers.add_parser("show", help="Show one pattern with its full history")
    show_parser.add_argument("mistake_id")
    _add_format(show_parser)

    forget_parser = subparsers.add_parser("forget", help="Delete a wrongly recorded pattern")
    forget_parser.add_argument("mistake_id")
    _add_verbose(forget_parser)

    undo_parser = subparsers.add_parser("undo", help="Revert the latest record, grade, observe, coach, or merge on one pattern")
    undo_parser.add_argument("mistake_id")
    _add_verbose(undo_parser)

    merge_parser = subparsers.add_parser("merge", help="Fold one pattern into another (source into target); undo on the target reverts it")
    merge_parser.add_argument("source_id")
    merge_parser.add_argument("target_id")
    merge_parser.add_argument("--at", help="ISO-8601 merge time")
    _add_verbose(merge_parser)

    rename_parser = subparsers.add_parser("rename", help="Rename or recategorize a pattern")
    rename_parser.add_argument("mistake_id")
    rename_parser.add_argument("--pattern")
    rename_parser.add_argument("--category", choices=CATEGORY_ORDER)
    rename_parser.add_argument("--rule")
    rename_parser.add_argument("--label", help="Short German name shown to the learner")
    _add_verbose(rename_parser)

    summary_parser = subparsers.add_parser("summary", help="Show the learner's FehlerDNA profile")
    summary_parser.add_argument("--at", help="ISO-8601 summary time")
    _add_format(summary_parser)
    _add_verbose(summary_parser)

    dashboard_parser = subparsers.add_parser("dashboard", help="Export a self-contained, offline learning dashboard")
    dashboard_parser.add_argument("--output", default="deutschloop-dashboard.html", help="HTML file to create")
    dashboard_parser.add_argument("--force", action="store_true", help="Replace an existing HTML export")
    dashboard_parser.add_argument("--at", help="Clock for due dates; does not reconstruct historical state")

    subparsers.add_parser("scenarios", help="List roleplay frames, opening lines, and example situations")
    mission_create_parser = subparsers.add_parser("mission-create", help="Plan continuing preparation for a learner-stated real-life goal")
    mission_create_parser.add_argument("--goal", required=True)
    mission_create_parser.add_argument("--scenario", required=True, choices=sorted(set(SCENARIOS) | set(SCENARIO_ALIASES)))
    mission_create_parser.add_argument("--deadline", help="YYYY-MM-DD, today/tomorrow, or a weekday in English/German/Turkish")
    mission_create_parser.add_argument("--at")
    mission_list_parser = subparsers.add_parser("mission-list", help="List continuing preparation goals")
    mission_list_parser.add_argument("--status", choices=("active", "completed", "cancelled", "all"), default="active")
    mission_list_parser.add_argument("--at")
    for name, help_text in (("mission-show", "Show saved preparation, the current step, and evidence"),
                            ("mission-start", "Start or resume the next adaptive preparation scene"),
                            ("mission-assess", "Assess a completed preparation scene using actual learner turns"),
                            ("mission-undo", "Undo the latest preparation assessment"),
                            ("mission-update", "Update a goal/deadline or cancel preparation")):
        mission_parser = subparsers.add_parser(name, help=help_text)
        mission_parser.add_argument("mission_id")
        mission_parser.add_argument("--at")
        if name == "mission-start":
            mission_parser.add_argument("--minutes", type=int, default=5)
            mission_parser.add_argument("--input-mode", choices=("text", "transcript"), default="text")
        elif name == "mission-assess":
            mission_parser.add_argument("--session-id", required=True)
            mission_parser.add_argument("--result", choices=("achieved", "practice"), required=True)
            mission_parser.add_argument("--support", choices=("none", "hint", "shown"), required=True)
            mission_parser.add_argument("--evidence-turn-id", action="append", required=True)
            mission_parser.add_argument("--note", required=True, help="Grounded judgment of the communication goal, not a proficiency score")
        elif name == "mission-update":
            mission_parser.add_argument("--goal")
            mission_parser.add_argument("--deadline", help="Empty string clears the deadline")
            mission_parser.add_argument("--cancel", action="store_true")

    recap_parser = subparsers.add_parser("recap", help="Summarize recent activity for a session opener")
    recap_parser.add_argument("--days", type=int, default=RECENT_DAYS)
    recap_parser.add_argument("--at", help="ISO-8601 recap time")
    _add_verbose(recap_parser)
    recap_parser.add_argument(
        "--format",
        choices=("json", "text", "card"),
        default="json",
        help="json for agents, text for a summary, card for the two-line German session header",
    )

    roleplay_start_parser = subparsers.add_parser("roleplay-start", help="Start a delayed-feedback roleplay session")
    roleplay_start_parser.add_argument("--scenario", required=True, choices=sorted(SCENARIOS))
    roleplay_start_parser.add_argument("--focus")
    roleplay_start_parser.add_argument("--minutes", type=int, default=5, help="Target scene duration, checked at the next turn")
    roleplay_start_parser.add_argument("--input-mode", choices=("text", "transcript"), default="text")
    roleplay_start_parser.add_argument("--at", help="ISO-8601 start time")

    speak_parser = subparsers.add_parser("speak", help="Start a scene with feedback after the conversation")
    speak_parser.add_argument("scenario", choices=sorted(set(SCENARIOS) | set(SCENARIO_ALIASES)))
    speak_parser.add_argument("--focus")
    speak_parser.add_argument("--minutes", type=int, default=5)
    speak_parser.add_argument("--input-mode", choices=("text", "transcript"), default="text")
    speak_parser.add_argument("--at", help="ISO-8601 start time")

    turn_parser = subparsers.add_parser("roleplay-turn", help="Log an actual utterance and get a natural wrap-up cue")
    turn_parser.add_argument("session_id")
    turn_parser.add_argument("--speaker", choices=("learner", "partner"), required=True)
    turn_parser.add_argument("--text", required=True)
    turn_parser.add_argument("--event-id", help="Stable message ID; repeat it only when retrying that message")
    turn_parser.add_argument("--support", choices=("none", "hint", "shown"), default="none", help="Mark actual help on a partner turn")
    turn_parser.add_argument("--at")

    stop_parser = subparsers.add_parser("roleplay-stop", help="End the scene and freeze duration before preparing feedback")
    stop_parser.add_argument("session_id")
    stop_parser.add_argument("--at")

    vocab_parser = subparsers.add_parser("roleplay-vocab", help="Save a scene word to the debrief and the word deck")
    vocab_parser.add_argument("session_id")
    vocab_parser.add_argument("--term", required=True)
    vocab_parser.add_argument("--meaning", required=True)
    vocab_parser.add_argument("--turn-id", required=True)
    vocab_parser.add_argument("--surface", help="Actual form in the turn when the term is a dictionary form")

    vocab_due_parser = subparsers.add_parser("vocab-due", help="Words from scenes that are due for review")
    vocab_due_parser.add_argument("--limit", type=int, default=5)
    vocab_due_parser.add_argument("--at", help="ISO-8601 comparison time")
    _add_format(vocab_due_parser)
    _add_verbose(vocab_due_parser)

    vocab_grade_parser = subparsers.add_parser("vocab-grade", help="Grade a due word the learner used in a new sentence")
    vocab_grade_parser.add_argument("word_id")
    vocab_grade_parser.add_argument("--result", required=True, choices=("pass", "hard", "fail"))
    vocab_grade_parser.add_argument("--prompt", required=True, help="The new situation and meaning cue that was actually asked")
    vocab_grade_parser.add_argument("--answer", required=True, help="The learner's actual sentence")
    vocab_grade_parser.add_argument("--correction", help="Minimal correction of a failed answer")
    vocab_grade_parser.add_argument("--at", help="ISO-8601 review time")
    _add_verbose(vocab_grade_parser)

    vocab_list_parser = subparsers.add_parser("vocab-list", help="The learner's word deck")
    vocab_list_parser.add_argument("--status", choices=("active", "mastered", "all"), default="all")
    vocab_list_parser.add_argument("--at", help="ISO-8601 time for due markers")
    _add_format(vocab_list_parser)
    _add_verbose(vocab_list_parser)

    vocab_undo_parser = subparsers.add_parser("vocab-undo", help="Revert the latest grade or scene addition of one word")
    vocab_undo_parser.add_argument("word_id")

    vocab_forget_parser = subparsers.add_parser("vocab-forget", help="Remove a wrongly saved word, also from its scene reports")
    vocab_forget_parser.add_argument("word_id")

    scene_parser = subparsers.add_parser("roleplay-show", help="Inspect a scene or its completed debrief")
    scene_parser.add_argument("session_id")
    scene_parser.add_argument("--at")
    _add_format(scene_parser)

    roleplay_finish_parser = subparsers.add_parser("roleplay-finish", help="Finish a roleplay session")
    roleplay_finish_parser.add_argument("session_id")
    roleplay_finish_parser.add_argument("--turns", type=int, help="Legacy scenes only; recorded turns are counted automatically")
    roleplay_finish_parser.add_argument("--duration-seconds", type=int, help="Override the timestamp-derived duration")
    roleplay_finish_parser.add_argument(
        "--mistake-id", "--mistake-ids", dest="mistake_id", action="extend", nargs="+", default=[],
        help="IDs recorded in this session; repeat the flag or list several",
    )
    roleplay_finish_parser.add_argument("--notes")
    roleplay_finish_parser.add_argument("--at", help="ISO-8601 finish time")
    _add_format(roleplay_finish_parser)
    return parser


def mistake_view(mistake: dict[str, Any], verbose: bool) -> dict[str, Any]:
    """Agents get the compact pattern; `--verbose` and `show` return the full record with its histories."""
    return public(mistake) if verbose else compact(mistake)


def run(arguments: argparse.Namespace) -> dict[str, Any]:
    store = StateStore(default_home(arguments.home))
    if arguments.command == "scenarios":
        return {"count": len(SCENARIOS), "scenarios": scenario_examples(), "aliases": SCENARIO_ALIASES}
    if arguments.command == "dashboard" and not store.home.exists():
        return _run_locked(store, arguments)  # An empty export must not create learner memory.
    with state_lock(store.home):
        return _run_locked(store, arguments)


def _run_locked(store: StateStore, arguments: argparse.Namespace) -> dict[str, Any]:
    command = arguments.command
    verbose = getattr(arguments, "verbose", False)
    if command == "dashboard":
        snapshot = dashboard_snapshot(store, at=parse_moment(arguments.at))
        return write_dashboard({"version": 1, "demo": False, "frames": [snapshot]},
                               Path(arguments.output), force=arguments.force)
    if command == "mission-create":
        return store.mission_create(goal=arguments.goal, scenario=arguments.scenario, deadline=arguments.deadline, at=parse_moment(arguments.at))
    if command == "mission-list":
        rows = store.mission_list(status=arguments.status, at=parse_moment(arguments.at))
        return {"count": len(rows), "missions": rows}
    if command == "mission-show":
        return {"mission": store.mission_show(arguments.mission_id, at=parse_moment(arguments.at))}
    if command == "mission-start":
        return store.mission_start(arguments.mission_id, minutes=arguments.minutes, input_mode=arguments.input_mode, at=parse_moment(arguments.at))
    if command == "mission-assess":
        return store.mission_assess(arguments.mission_id, session_id=arguments.session_id, result=arguments.result,
                                    support=arguments.support, evidence_turn_ids=arguments.evidence_turn_id,
                                    note=arguments.note, at=parse_moment(arguments.at))
    if command == "mission-undo":
        return store.mission_undo(arguments.mission_id, at=parse_moment(arguments.at))
    if command == "mission-update":
        return store.mission_update(arguments.mission_id, goal=arguments.goal, deadline=arguments.deadline,
                                    cancel=arguments.cancel, at=parse_moment(arguments.at))
    if command == "init":
        profile = store.init_profile(
            name=arguments.name,
            native_language=arguments.native_language,
            level=arguments.level,
            goal=arguments.goal,
            explanation_language=arguments.explanation_language,
            starting_point=arguments.starting_point,
            welcome_shown=arguments.welcome_shown,
            onboarding_complete=arguments.onboarding_complete,
            at=parse_moment(arguments.at),
        )
        return {"status": "ready", "home": str(store.home.resolve()), "profile": profile}
    if command == "record":
        mistake, status, extra = store.record(
            original=arguments.original,
            corrected=arguments.corrected,
            category=arguments.category,
            pattern=arguments.pattern,
            rule=arguments.rule,
            mistake_id=arguments.mistake_id,
            context=arguments.context,
            event_id=arguments.event_id,
            label=arguments.label,
            session_id=arguments.session_id,
            turn_id=arguments.turn_id,
            at=parse_moment(arguments.at),
        )
        result: dict[str, Any] = {
            "status": status,
            "mistake": mistake_view(mistake, verbose),
            "resolved_by": extra.get("resolved_by"),
            "recent": {"days": RECENT_DAYS, "occurrences": extra.get("recent_occurrences", 0)},
            "minimality": minimality_view(arguments.original, arguments.corrected),
        }
        if extra.get("previous"):
            result["previous"] = extra["previous"]
        if extra.get("onboarding_completed"):
            result["onboarding"] = "completed"
        similar = extra.get("similar_patterns") or []
        if similar:
            result["similar_patterns"] = similar
            result["hint"] = (
                f"A similar key exists. Merge only if both name the same root cause, not merely the same rule "
                f"template: merge {mistake['id']} {similar[0]['id']} (undo {similar[0]['id']} reverts it)"
            )
        return result
    if command == "observe":
        results = store.observe(arguments.mistake_ids, context=arguments.context, at=parse_moment(arguments.at))
        return {"status": "observed", "results": results}
    if command == "coach":
        variety = None
        if arguments.outcome == "independent":
            variety = variety_note(store.show(arguments.mistake_id), prompt=arguments.prompt, answer=arguments.answer)
        outcome = store.coach(arguments.mistake_id, outcome=arguments.outcome, prompt=arguments.prompt,
                              answer=arguments.answer, strategy=arguments.strategy, hint=arguments.hint,
                              at=parse_moment(arguments.at))
        return {**outcome, "mistake": mistake_view(outcome["mistake"], verbose),
                "variety": variety if outcome["status"] == "coached" else None}
    if command == "due":
        moment = parse_moment(arguments.at)
        items = store.due(at=moment, limit=arguments.limit)
        return {"as_of": iso(moment), "count": len(items), "mistakes": [mistake_view(item, verbose) for item in items]}
    if command == "grade":
        moment = parse_moment(arguments.at)
        variety = variety_note(store.show(arguments.mistake_id), prompt=arguments.prompt or "", answer=arguments.answer or "")
        mistake, status = store.grade(
            arguments.mistake_id,
            result=arguments.result,
            answer=arguments.answer,
            correction=arguments.correction,
            prompt=arguments.prompt,
            strategy=arguments.strategy,
            hint=arguments.hint,
            at=moment,
        )
        proof = mistake.get("learning_proof")
        new_proof = proof if status == "graded" and proof and proof["independent"]["at"] == iso(moment) else None
        return {"status": status, "mistake": mistake_view(mistake, verbose), "learning_proof": learning_proof_view(new_proof),
                "variety": variety if status == "graded" else None}
    if command == "list":
        rows = store.list(status=arguments.status, category=arguments.category, verbose=verbose)
        return {"count": len(rows), "status_filter": arguments.status, "mistakes": rows}
    if command == "show":
        return {"mistake": public(store.show(arguments.mistake_id))}
    if command == "forget":
        return {"status": "forgotten", "mistake": mistake_view(store.forget(arguments.mistake_id), verbose)}
    if command == "undo":
        outcome = store.undo(arguments.mistake_id)
        for field in ("mistake", "restored"):
            if field in outcome:
                outcome[field] = mistake_view(outcome[field], verbose)
        return outcome
    if command == "merge":
        merged = store.merge(arguments.source_id, arguments.target_id, at=parse_moment(arguments.at))
        return {"status": "merged", "mistake": mistake_view(merged, verbose),
                "undo_available": {"action": "merge", "at": merged["undo"]["at"]}}
    if command == "rename":
        outcome = store.rename(
            arguments.mistake_id,
            pattern=arguments.pattern,
            category=arguments.category,
            rule=arguments.rule,
            label=arguments.label,
        )
        return {"status": "renamed", "previous_id": outcome["previous_id"], "mistake": mistake_view(outcome["mistake"], verbose)}
    if command == "summary":
        moment = parse_moment(arguments.at)
        result = store.summary(at=moment, verbose=verbose)
        if arguments.format == "text":
            store.mark_profile_shown(at=moment)
        return result
    if command == "recap":
        return store.recap(days=arguments.days, at=parse_moment(arguments.at), verbose=verbose)
    if command in {"roleplay-start", "speak"}:
        return store.roleplay_start(arguments.scenario, focus=arguments.focus, minutes=arguments.minutes,
                                    input_mode=arguments.input_mode, at=parse_moment(arguments.at))
    if command == "roleplay-turn":
        return store.roleplay_turn(arguments.session_id, speaker=arguments.speaker, text=arguments.text,
                                   event_id=arguments.event_id, support=arguments.support, at=parse_moment(arguments.at))
    if command == "roleplay-stop":
        moment = parse_moment(arguments.at)
        store.roleplay_stop(arguments.session_id, at=moment)
        return store.roleplay_show(arguments.session_id, at=moment)
    if command == "roleplay-vocab":
        return store.roleplay_vocab(arguments.session_id, term=arguments.term, meaning=arguments.meaning,
                                   surface=arguments.surface, turn_id=arguments.turn_id)
    if command == "vocab-due":
        moment = parse_moment(arguments.at)
        words = store.vocab_due(at=moment, limit=arguments.limit)
        return {"as_of": iso(moment), "count": len(words), "words": [word_output(word, moment, verbose) for word in words]}
    if command == "vocab-grade":
        moment = parse_moment(arguments.at)
        word, status = store.vocab_grade(arguments.word_id, result=arguments.result, prompt=arguments.prompt,
                                         answer=arguments.answer, correction=arguments.correction, at=moment)
        return {"status": status, "word": word_output(word, moment, verbose)}
    if command == "vocab-list":
        moment = parse_moment(arguments.at)
        words = store.vocab_list(status=arguments.status)
        return {"as_of": iso(moment), "count": len(words), "status_filter": arguments.status,
                "overview": vocabulary_overview(store.vocab_list(status="all"), moment),
                "words": [word_output(word, moment, True) if verbose else word_row(word, moment) for word in words]}
    if command == "vocab-undo":
        outcome = store.vocab_undo(arguments.word_id)
        return {**outcome, "word": word_output(outcome["word"], utc_now(), False)}
    if command == "vocab-forget":
        return {"status": "forgotten", "word": word_output(store.vocab_forget(arguments.word_id), utc_now(), False)}
    if command == "roleplay-show":
        return store.roleplay_show(arguments.session_id, at=parse_moment(arguments.at))
    if command == "roleplay-finish":
        session = store.roleplay_finish(
            arguments.session_id,
            turns=arguments.turns,
            duration_seconds=arguments.duration_seconds,
            mistake_ids=arguments.mistake_id,
            notes=arguments.notes,
            at=parse_moment(arguments.at),
        )
        return {"status": "finished", **store.roleplay_show(session["id"])}
    raise DeutschLoopError(f"Unsupported command: {command}")


def main(argv: list[str] | None = None) -> int:
    _configure_streams()
    parser = build_parser()
    try:
        arguments = parser.parse_args(argv)
        result = run(arguments)
        output_format = getattr(arguments, "format", "json")
        renderers = {"text": TEXT_RENDERERS, "card": CARD_RENDERERS}.get(output_format, {})
        renderer = renderers.get(arguments.command)
        if renderer:
            print(renderer(result))
        else:
            _print_json(result)
        return 0
    except DeutschLoopError as exc:
        _print_json({"error": str(exc), **({"code": exc.code} if exc.code else {})}, stream=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
