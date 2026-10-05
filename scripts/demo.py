#!/usr/bin/env python3
"""Replay a four-month learner story through the real DeutschLoop engine.

The story only scripts what the learner wrote and how each review went. When a
review happens is decided by the engine's own schedule, and every number in the
output is computed from the stored events. Nothing on screen is hard-coded.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deutsch_loop as dna  # noqa: E402


STORY_DAYS = 120
TICK = timedelta(minutes=3)

PATTERNS = {
    "mit": ("case", "mit + dative", "mit always governs the dative"),
    "warten": ("preposition", "warten auf + accusative", "warten takes auf + accusative"),
    "ung": ("article", "-ung nouns are feminine", "Nouns ending in -ung are feminine"),
    "interessieren": ("preposition", "sich interessieren für + accusative", "sich interessieren takes für + accusative"),
    "obwohl": ("word-order", "obwohl sends finite verb to end", "In an obwohl clause the finite verb goes last"),
    "helfen": ("case", "helfen + dative", "helfen takes a dative object"),
    "hund": ("case", "masculine accusative -en", "A masculine direct object needs -en: einen, keinen, meinen, den"),
    "freuen": ("preposition", "sich freuen auf + accusative", "sich freuen auf for something ahead, über for something here"),
    "adj": ("agreement", "adjective ending after ein-word", "After ein, kein, mein the adjective shows the gender: ein wichtiger Termin"),
    "personen": ("plural", "Person plural is Personen", "die Person, die Personen"),
    "anrufen": ("case", "anrufen + accusative", "anrufen takes an accusative object: Ich rufe dich an"),
    "adjdef": ("agreement", "adjective ending after der-word", "After der, die, das the adjective ends in -e or -en: den neuen Film"),
    "angst": ("preposition", "Angst haben vor + dative", "Angst haben takes vor + dative"),
    "weil": ("word-order", "weil sends finite verb to end", "In a weil clause the finite verb goes last"),
}

# What the learner wrote and its minimal correction: (days ago, pattern, sentence, correction).
WRITING = [
    (120, "mit", "Ich spreche mit mein Chef.", "Ich spreche mit meinem Chef."),
    (120, "warten", "Ich warte dich.", "Ich warte auf dich."),
    (118, "ung", "Ich habe ein Reservierung für zwei Personen.", "Ich habe eine Reservierung für zwei Personen."),
    (100, "interessieren", "Ich interessiere mich an Fußball.", "Ich interessiere mich für Fußball."),
    (80, "obwohl", "Obwohl ich bin müde, arbeite ich weiter.", "Obwohl ich müde bin, arbeite ich weiter."),
    (80, "helfen", "Ich helfe meinen Bruder.", "Ich helfe meinem Bruder."),
    (45, "hund", "Ich habe ein Hund.", "Ich habe einen Hund."),
    (45, "freuen", "Ich freue mich über das Wochenende.", "Ich freue mich auf das Wochenende."),
    (45, "adj", "Ich habe einen neue Job.", "Ich habe einen neuen Job."),
    (20, "interessieren", "Ich interessiere mich an Geschichte.", "Ich interessiere mich für Geschichte."),
    (15, "anrufen", "Ich rufe dir morgen an.", "Ich rufe dich morgen an."),
    (14, "personen", "Wir sind vier Person.", "Wir sind vier Personen."),
    (12, "freuen", "Ich freue mich über meinen Urlaub nächste Woche.", "Ich freue mich auf meinen Urlaub nächste Woche."),
    (10, "adjdef", "Ich mag den neue Film.", "Ich mag den neuen Film."),
    (4, "angst", "Ich habe Angst von Hunden.", "Ich habe Angst vor Hunden."),
    (2, "weil", "Ich bleibe zu Hause, weil ich bin krank.", "Ich bleibe zu Hause, weil ich krank bin."),
    (0, "warten", "Ich warte meine Freundin.", "Ich warte auf meine Freundin."),
    (0, "weil", "Ich nehme den Bus, weil es regnet stark.", "Ich nehme den Bus, weil es stark regnet."),
]

# How each review went, in order: ("pass", answer), ("hard", answer), ("fail", answer, correction).
# Reviews beyond the end of a list pass. Every review uses a new sentence.
REVIEWS = {
    "mit": [
        ("pass", "Ich arbeite mit meinem Kollegen."),
        ("pass", "Ich fahre mit dem Bus zur Arbeit."),
        ("pass", "Ich telefoniere mit meiner Mutter."),
        ("pass", "Wir essen mit unseren Nachbarn."),
        ("pass", "Ich spreche mit einem Kunden."),
        ("pass", "Ich bin mit dem Projekt zufrieden."),
    ],
    "warten": [
        ("pass", "Ich warte auf meinen Bruder."),
        ("fail", "Ich warte den Zug.", "Ich warte auf den Zug."),
        ("pass", "Wir warten auf das Paket."),
        ("hard", "Ich warte auf deine Antwort."),
        ("pass", "Sie wartet auf ihren Termin."),
        ("fail", "Wir warten den Bus.", "Wir warten auf den Bus."),
        ("pass", "Ich warte auf eine E-Mail."),
        ("pass", "Warte bitte auf mich!"),
        ("pass", "Er wartet auf den Arzt."),
        ("pass", "Wie lange wartest du schon auf mich?"),
        ("pass", "Wir warten auf besseres Wetter."),
    ],
    "helfen": [("pass", None), ("fail", "Ich helfe dich gern.", "Ich helfe dir gern.")],
    "freuen": [("pass", None)] * 5
    + [("fail", "Ich freue mich über die Party am Samstag.", "Ich freue mich auf die Party am Samstag.")],
    "adj": [
        ("pass", None),
        ("fail", "mit meinem neue Kollegen", "mit meinem neuen Kollegen"),
        ("pass", None),
        ("fail", "ein interessante Buch", "ein interessantes Buch"),
        ("pass", None),
        ("pass", None),
        ("fail", "Ich trinke einen kalte Kaffee.", "Ich trinke einen kalten Kaffee."),
        ("pass", None),
        ("pass", None),
        ("pass", None),
        ("fail", "Das ist ein wichtige Termin.", "Das ist ein wichtiger Termin."),
    ],
    "adjdef": [
        ("fail", "die neue Filme", "die neuen Filme"),
        ("pass", None),
        ("fail", "mit dem neue Auto", "mit dem neuen Auto"),
    ],
    "anrufen": [("pass", None), ("fail", "Ruf mir bitte an.", "Ruf mich bitte an.")],
}

# Correct, unprompted uses of tracked patterns in later writing.
OBSERVATIONS = [
    (6, "hund", "Wir haben einen Hund und eine Katze."),
    (4, "helfen", "Ich helfe dir gern beim Umzug."),
    (1, "mit", "mit unseren Kunden"),
]
ROLEPLAYS = [(2, "restaurant", 8, timedelta(minutes=6, seconds=42))]

# These tasks are story inputs, just like the learner's answers. The engine still
# decides when each may be graded and refuses copied prompts or answers.
REVIEW_PROMPTS = {
    "Ich arbeite mit meinem Kollegen.": "Dein Kollege und du erledigen das Projekt gemeinsam. Mit wem arbeitest du?",
    "Ich fahre mit dem Bus zur Arbeit.": "Dein Verkehrsmittel zur Arbeit ist der Bus. Wie kommst du hin?",
    "Ich telefoniere mit meiner Mutter.": "Deine Mutter ist am Telefon. Mit wem telefonierst du?",
    "Wir essen mit unseren Nachbarn.": "Eure Nachbarn kommen zum Abendessen. Mit wem esst ihr?",
    "Ich spreche mit einem Kunden.": "Ein Kunde ist bei dir im Büro. Mit wem sprichst du?",
    "Ich bin mit dem Projekt zufrieden.": "Das Projekt ist gut gelungen. Womit bist du zufrieden?",
    "Ich warte auf meinen Bruder.": "Dein Bruder verspätet sich. Auf wen wartest du?",
    "Ich warte den Zug.": "Der Zug kommt erst später. Sage mit warten, warum du noch am Bahnhof bist.",
    "Wir warten auf das Paket.": "Das Paket ist noch nicht da. Worauf wartet ihr?",
    "Ich warte auf deine Antwort.": "Deine Freundin hat noch nicht geantwortet. Worauf wartest du?",
    "Sie wartet auf ihren Termin.": "Eine Frau sitzt vor dem Sprechzimmer. Ihr Termin beginnt später. Was macht sie?",
    "Wir warten den Bus.": "Euer Bus verspätet sich. Sagt mit warten, was ihr gerade macht.",
    "Ich warte auf eine E-Mail.": "Du erwartest eine E-Mail. Worauf wartest du gerade?",
    "Warte bitte auf mich!": "Dein Freund läuft zu schnell. Bitte ihn mit warten, bei dir zu bleiben.",
    "Er wartet auf den Arzt.": "Der Arzt fehlt noch. Was macht der Patient im Wartezimmer?",
    "Wie lange wartest du schon auf mich?": "Du kommst zu spät. Frage, seit wann dein Freund auf dich wartet.",
    "Wir warten auf besseres Wetter.": "Ihr wollt erst bei besserem Wetter losfahren. Worauf wartet ihr?",
    "Ich helfe dich gern.": "Dein Freund bittet dich um Hilfe. Biete ihm mit helfen deine Unterstützung an.",
    "Ich freue mich über die Party am Samstag.": "Die Party findet erst am Samstag statt. Drücke deine Vorfreude aus.",
    "mit meinem neue Kollegen": "Du triffst einen neuen Kollegen. Mit wem sprichst du?",
    "ein interessante Buch": "Du liest ein Buch und findest es interessant. Beschreibe das Buch mit ein.",
    "Ich trinke einen kalte Kaffee.": "Dein Kaffee ist kalt. Beschreibe mit trinken, was du trinkst.",
    "Das ist ein wichtige Termin.": "Du zeigst auf einen Termin im Kalender. Sage, dass er wichtig ist.",
    "die neue Filme": "Im Kino laufen mehrere neue Filme. Benenne sie mit dem bestimmten Artikel.",
    "mit dem neue Auto": "Das Auto ist neu. Sage, womit du heute fährst.",
    "Ruf mir bitte an.": "Du möchtest später einen Anruf erhalten. Bitte deinen Freund darum.",
}

# Reviews without a scripted answer take the next task here. Each one is a different
# situation and sentence frame, the way the skill asks for reviews: swapping one noun
# in the same sentence would test recall of that sentence, not transfer.
FRESH_TASKS = {
    "mit": [
        ("Du fährst in den Urlaub. Wer kommt mit?", "Ich fahre mit meiner Familie in den Urlaub."),
        ("Womit schreibst du deine Notizen?", "Meine Notizen schreibe ich mit einem Bleistift."),
        ("Wie bezahlst du im Restaurant?", "Im Restaurant bezahle ich meistens mit der Karte."),
        ("Mit wem gehst du am Samstag ins Kino?", "Am Samstag gehe ich mit zwei Kolleginnen ins Kino."),
        ("Womit kommst du bei Schnee zur Arbeit?", "Bei Schnee komme ich mit der Straßenbahn."),
        ("Mit wem hast du über die Gehaltserhöhung gesprochen?", "Darüber habe ich mit der Personalabteilung gesprochen."),
        ("Womit putzt du die Fenster?", "Die Fenster putze ich mit einem alten Tuch."),
        ("Mit wem feierst du Silvester?", "Silvester feiern wir mit unseren Freunden aus Köln."),
    ],
    "warten": [
        ("Die Ampel ist rot. Was machen die Fußgänger?", "Die Fußgänger warten auf das grüne Licht."),
        ("Du hast eine Bewerbung geschickt. Worauf wartest du jetzt?", "Jetzt warte ich auf eine Antwort der Firma."),
        ("Im Restaurant ist es voll. Was macht ihr?", "Wir warten an der Bar auf einen freien Tisch."),
        ("Deine Tochter hat gleich Schulschluss. Wo bist du?", "Ich stehe vor der Schule und warte auf meine Tochter."),
        ("Warum stehst du am Fenster?", "Ich schaue raus, weil ich auf den Postboten warte."),
        ("Das Paket kommt heute. Was fragst du deinen Mitbewohner?", "Kannst du heute auf das Paket warten?"),
        ("Der Film beginnt erst um acht. Was macht ihr im Kino?", "Im Foyer warten wir auf den Beginn des Films."),
        ("Wann kommt endlich der Techniker?", "Wir warten schon seit Montag auf den Techniker."),
    ],
    "ung": [
        ("Du hast eine Wohnung gefunden. Wie ist sie?", "Die Wohnung ist hell und ruhig."),
        ("Was lag heute in deinem Briefkasten?", "Heute lag eine Einladung zur Hochzeit im Briefkasten."),
        ("Wie war das Meeting?", "Die Besprechung hat viel zu lange gedauert."),
        ("Warum bist du so nervös?", "Morgen schreibe ich eine wichtige Prüfung."),
        ("Was fehlt noch für die Reise?", "Für die Reise brauche ich noch eine Versicherung."),
        ("Was sagt dein Chef zu deinem Vorschlag?", "Er findet, dass die Lösung zu teuer ist."),
        ("Wo genau liegt das Hotel?", "Das Hotel liegt direkt an der Kreuzung."),
        ("Was hat die Ärztin dir gegeben?", "Sie hat mir eine Überweisung zum Facharzt gegeben."),
    ],
    "interessieren": [
        ("Was liest du in der Zeitung zuerst?", "Ich interessiere mich vor allem für den Sportteil."),
        ("Deine Schwester studiert Biologie. Warum?", "Sie interessiert sich schon lange für Tiere."),
        ("Frag deinen neuen Kollegen nach seinen Hobbys.", "Wofür interessierst du dich in deiner Freizeit?"),
        ("Warum hast du den Vortrag besucht?", "Weil ich mich für künstliche Intelligenz interessiere."),
        ("Was fragt die Personalerin im Gespräch?", "Sie fragt, ob ich mich für eine Stelle im Vertrieb interessiere."),
        ("Deine Kinder schauen jeden Abend Nachrichten. Warum?", "Meine Kinder interessieren sich sehr für Politik."),
        ("Warum wart ihr auf der Automesse?", "Mein Mann und ich interessieren uns für ein neues Auto."),
        ("Spielst du Tennis?", "Nein, für Tennis interessiere ich mich überhaupt nicht."),
    ],
    "obwohl": [
        ("Es regnet, aber du gehst joggen. Sag es mit obwohl.", "Obwohl es regnet, gehe ich joggen."),
        ("Dein Kollege ist krank und kommt trotzdem ins Büro.", "Er kommt ins Büro, obwohl er krank ist."),
        ("Du hast wenig Geld und kaufst doch ein Konzertticket.", "Obwohl ich wenig Geld habe, kaufe ich das Ticket."),
        ("Die Wohnung ist teuer. Ihr nehmt sie trotzdem.", "Wir nehmen die Wohnung, obwohl sie teuer ist."),
        ("Du hast lange gelernt und die Prüfung trotzdem nicht bestanden.", "Obwohl ich lange gelernt habe, habe ich nicht bestanden."),
        ("Es wird dunkel, aber deine Tochter spielt draußen weiter.", "Sie spielt draußen weiter, obwohl es schon dunkel wird."),
        ("Der Zug hatte Verspätung, aber du warst pünktlich.", "Obwohl der Zug Verspätung hatte, war ich pünktlich."),
        ("Du verstehst den Film nicht ganz, aber er gefällt dir.", "Der Film gefällt mir, obwohl ich nicht alles verstehe."),
    ],
    "helfen": [
        ("Deine Nachbarin trägt schwere Einkaufstüten. Was fragst du sie?", "Darf ich Ihnen mit den Tüten helfen?"),
        ("Dein Kollege versteht das neue Programm nicht. Was machst du?", "Ich zeige es ihm und helfe ihm bei den ersten Schritten."),
        ("Deine kleine Schwester hat Hausaufgaben. Wer unterstützt sie?", "Mein Vater hilft ihr jeden Abend dabei."),
        ("Ein Tourist sucht den Bahnhof. Wie reagierst du?", "Ich helfe dem Touristen und zeige ihm den Weg."),
        ("Deine Freunde ziehen um. Was machst du am Samstag?", "Am Samstag helfen wir unseren Freunden beim Umzug."),
        ("Deine Oma kommt mit dem Handy nicht klar. Was sagst du?", "Oma, soll ich dir mit dem Handy helfen?"),
        ("Wer hat dir bei der Bewerbung geholfen?", "Meine Lehrerin hat mir bei der Bewerbung sehr geholfen."),
        ("Der Ball der Kinder hängt im Baum. Was tust du?", "Ich helfe den Kindern und hole den Ball herunter."),
    ],
    "hund": [
        ("Was hast du zum Geburtstag bekommen?", "Ich habe einen neuen Rucksack bekommen."),
        ("Was brauchst du noch für die Suppe?", "Ich brauche noch einen großen Topf."),
        ("Was siehst du im Garten?", "Im Baum sehe ich einen kleinen Vogel."),
        ("Wen triffst du heute Abend?", "Heute Abend treffe ich meinen Bruder zum Essen."),
        ("Was bestellst du im Café?", "Für mich einen Cappuccino, bitte."),
        ("Fährst du selbst zur Arbeit?", "Nein, ich habe keinen Führerschein."),
        ("Was sucht ihr im Möbelhaus?", "Wir suchen einen Esstisch für sechs Leute."),
        ("Wen hast du auf der Party kennengelernt?", "Auf der Party habe ich einen Kollegen von Anna kennengelernt."),
    ],
    "freuen": [
        ("Nächste Woche beginnt dein Urlaub. Wie fühlst du dich?", "Ich freue mich schon sehr auf die freien Tage."),
        ("Deine Freundin kommt am Freitag zu Besuch. Was schreibst du ihr?", "Ich freue mich auf deinen Besuch!"),
        ("Die Kinder haben bald Ferien. Wie sind sie?", "Die Kinder freuen sich riesig auf die Ferien."),
        ("Worauf freust du dich am Wochenende?", "Am Wochenende freue ich mich aufs Ausschlafen."),
        ("Nächsten Monat fängt ein neuer Kollege an. Was sagt das Team?", "Wir freuen uns auf die Zusammenarbeit."),
        ("Morgen spielt deine Lieblingsband in der Stadt.", "Morgen ist das Konzert, darauf freue ich mich total."),
        ("Frag deine Nachbarin nach ihren Plänen für den Sommer.", "Worauf freuen Sie sich im Sommer am meisten?"),
        ("Bald ist Weihnachten. Was ist mit deinem Sohn?", "Er freut sich schon wochenlang auf die Geschenke."),
    ],
    "adj": [
        ("Beschreibe dein neues Handy.", "Es ist ein neues Modell mit einer guten Kamera."),
        ("Wie ist das Wetter heute?", "Heute ist ein schöner, sonniger Tag."),
        ("Was suchst du auf dem Wohnungsmarkt?", "Ich suche eine kleine Wohnung mit einem großen Balkon."),
        ("Wie findest du den neuen Kollegen?", "Er ist ein sehr freundlicher Mensch."),
        ("Was hast du deiner Mutter geschenkt?", "Ich habe ihr einen warmen Schal geschenkt."),
        ("Was für ein Auto fährst du?", "Ich fahre einen alten roten Golf."),
        ("Was trinkst du am Morgen?", "Morgens brauche ich einen starken Tee."),
        ("In was für einer Gegend wohnst du?", "Ich wohne in einem ruhigen Viertel am Stadtrand."),
    ],
    "personen": [
        ("Du reservierst einen Tisch. Für wie viele?", "Für vier Personen, bitte."),
        ("Wie viele Leute passen in den Aufzug?", "In den Aufzug passen höchstens acht Personen."),
        ("Wie viele Gäste kommen zur Feier?", "Zur Feier kommen ungefähr zwanzig Personen."),
        ("Wer war beim Meeting?", "Beim Meeting waren nur drei Personen."),
        ("Wie groß ist das Ferienhaus?", "Das Ferienhaus hat Platz für sechs Personen."),
        ("Ist die Schlange an der Kasse lang?", "Nein, vor mir stehen nur zwei Personen."),
        ("Wie groß ist dein Team?", "In meinem Team arbeiten zehn Personen."),
        ("Wie viele Tickets kaufst du?", "Ich kaufe Tickets für fünf Personen."),
    ],
    "anrufen": [
        ("Deine Mutter hat heute Geburtstag.", "Ich rufe meine Mutter gleich nach dem Frühstück an."),
        ("Die Praxis hat angerufen, als du nicht da warst.", "Ich rufe die Praxis morgen früh an."),
        ("Dein Freund wartet auf deinen Anruf. Was versprichst du?", "Ich rufe dich heute Abend an."),
        ("Die Heizung ist kaputt. Wen kontaktierst du?", "Ich rufe sofort den Vermieter an."),
        ("Ruft dein Chef dich oft an?", "Ja, er ruft mich fast jeden Tag an."),
        ("Du bist krank und kannst nicht arbeiten.", "Zuerst rufe ich meine Chefin an."),
        ("Deine Kollegin hat eine Frage zum Projekt.", "Ruf mich doch kurz an, dann erkläre ich es dir."),
        ("Wen hast du gestern angerufen?", "Gestern habe ich meine Großeltern angerufen."),
    ],
    "adjdef": [
        ("Welche Jacke nimmst du, die blaue oder die schwarze?", "Ich nehme die blaue Jacke."),
        ("Welchen Film habt ihr gestern gesehen?", "Wir haben den französischen Film im Kino gesehen."),
        ("Wem gehört das rote Fahrrad?", "Das rote Fahrrad gehört meinem Bruder."),
        ("In welchem Hotel übernachtet ihr?", "Wir übernachten in dem kleinen Hotel am See."),
        ("Mit welchem Zug fährst du?", "Ich fahre mit dem frühen Zug um sechs."),
        ("Welche Schuhe passen zum Anzug?", "Die schwarzen Schuhe passen am besten."),
        ("Welcher Vorschlag gefällt dir?", "Der letzte Vorschlag gefällt mir besser."),
        ("Wo steht die Vase?", "Die Vase steht auf dem alten Tisch im Flur."),
    ],
    "angst": [
        ("Warum fliegst du nicht gern?", "Beim Fliegen habe ich immer Angst vor Turbulenzen."),
        ("Warum ist dein Sohn nachts wach?", "Er hat Angst vor der Dunkelheit."),
        ("Warum bist du vor der Präsentation nervös?", "Ich habe ein bisschen Angst vor dem Publikum."),
        ("Warum tragen Wanderer im Sommer lange Hosen?", "Viele Wanderer haben Angst vor Zecken."),
        ("Was macht dir an der neuen Stelle Sorgen?", "Ehrlich gesagt habe ich Angst vor den vielen Überstunden."),
        ("Warum geht deine Oma im Winter nicht allein raus?", "Sie hat Angst vor dem Glatteis."),
        ("Warum sagst du deinem Chef nichts?", "Ich habe Angst vor seiner Reaktion."),
        ("Wovor hat deine Katze Angst?", "Meine Katze hat Angst vor dem Staubsauger."),
    ],
    "weil": [
        ("Warum trinkst du so viel Kaffee?", "Ich trinke viel Kaffee, weil ich nachts schlecht schlafe."),
        ("Warum lernst du Deutsch?", "Weil ich in Deutschland arbeiten möchte."),
        ("Warum kommst du heute später?", "Ich komme später, weil mein Zug ausgefallen ist."),
        ("Warum ist das Restaurant geschlossen?", "Es ist geschlossen, weil heute Feiertag ist."),
        ("Warum nimmst du einen Regenschirm mit?", "Weil es am Nachmittag regnen soll."),
        ("Warum sucht ihr eine neue Wohnung?", "Wir ziehen um, weil unsere Wohnung zu klein ist."),
        ("Warum rufst du den Vermieter an?", "Ich rufe ihn an, weil die Heizung nicht funktioniert."),
        ("Warum bist du so gut gelaunt?", "Ich bin gut gelaunt, weil ich die Prüfung bestanden habe."),
    ],
}


def fallback_tasks(key: str) -> list[tuple[str, str]]:
    if key not in FRESH_TASKS:
        raise ValueError(f"No demo exercises for {key}")
    return FRESH_TASKS[key]


class Clock:
    """Hands out increasing moments inside one story day."""

    def __init__(self, day_start: datetime):
        self.moment = day_start

    def next(self) -> datetime:
        current = self.moment
        self.moment += TICK
        return current


def seed_learning_loop(home: Path) -> None:
    """A scripted first win and next-day transfer, with all evidence stored by the CLI engine."""
    store = dna.StateStore(home)
    today = dna.utc_now() - timedelta(minutes=1)
    # Keep every first-session attempt on the previous local day, even when
    # this demo is rendered just before midnight.
    yesterday = dna.to_local(today).replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=1)
    store.init_profile(name="Alex", level="B2", native_language="tr",
                       goal="Im Gespräch mit Kunden sicherer werden", at=yesterday)
    mistake, _, _ = store.record(original="Ich spreche mit mein Chef.", corrected="Ich spreche mit meinem Chef.",
                                 category="case", pattern="mit + dative", rule="mit verlangt den Dativ", at=yesterday)
    store.coach(mistake["id"], outcome="assisted", prompt="Schau noch einmal auf mit mein Chef.",
                answer="Ich spreche mit meinem Chef.", strategy="Kasusfrage", hint="Frage dich: mit wem?",
                at=yesterday + timedelta(minutes=5))
    store.coach(mistake["id"], outcome="independent", prompt="Dein Verkehrsmittel ist der Bus. Wie kommst du zur Arbeit?",
                answer="Ich fahre mit dem Bus.", at=yesterday + timedelta(minutes=8))
    store.observe([mistake["id"]], context="Wir haben mit unseren Kunden gesprochen.", at=today)


def seed(home: Path) -> None:
    store = dna.StateStore(home)
    anchor = dna.utc_now() - timedelta(hours=1)
    ids: dict[str, str] = {}
    keys_by_id: dict[str, str] = {}
    queues = {key: list(outcomes) for key, outcomes in REVIEWS.items()}
    tasks = {key: iter(fallback_tasks(key)) for key in PATTERNS}
    store.init_profile(name="Alex", level="B2", native_language="tr", at=anchor - timedelta(days=STORY_DAYS, minutes=10))

    for days_ago in range(STORY_DAYS, -1, -1):
        day_start = anchor - timedelta(days=days_ago)
        clock = Clock(day_start)
        # Morning: whatever the engine says is due. Nothing is reviewed on the last day,
        # so the demo ends with reviews waiting, exactly as a learner would find it.
        if days_ago > 0:
            for mistake in store.due(at=day_start + timedelta(hours=1), limit=100):
                key = keys_by_id[mistake["id"]]
                outcome = queues[key].pop(0) if queues.get(key) else ("pass", None)
                answer = outcome[1]
                if answer is None:
                    prompt, answer = next(tasks[key])
                else:
                    prompt = REVIEW_PROMPTS[answer]
                review_at = max(clock.next(), dna.parse_moment(mistake["next_review"]))
                clock.moment = review_at + TICK
                if outcome[0] == "fail":
                    store.grade(mistake["id"], result="fail", prompt=prompt, answer=answer, correction=outcome[2], at=review_at)
                else:
                    help_used = {"strategy": "Verb mit Präposition", "hint": "Das Verb heißt warten auf."} if outcome[0] == "hard" else {}
                    store.grade(mistake["id"], result=outcome[0], prompt=prompt, answer=answer, at=review_at, **help_used)
        for day, key, original, corrected in WRITING:
            if day != days_ago:
                continue
            category, pattern, rule = PATTERNS[key]
            mistake, _, _ = store.record(
                original=original,
                corrected=corrected,
                category=category,
                pattern=pattern,
                rule=rule,
                at=clock.next(),
            )
            ids[key] = mistake["id"]
            keys_by_id[mistake["id"]] = key
        for day, key, context in OBSERVATIONS:
            if day == days_ago:
                store.observe([ids[key]], context=context, at=clock.next())
        for day, scenario, turns, duration in ROLEPLAYS:
            if day == days_ago:
                started_at = clock.next()
                started = store.roleplay_start(scenario, at=started_at)
                store.roleplay_finish(
                    started["session"]["id"],
                    turns=turns,
                    notes="Reservation, order, one complaint, payment.",
                    at=started_at + duration,
                )


def seed_speaking_scene(home: Path) -> str:
    """Scripted restaurant exchange; duration, corrections and recurrence counts come from stored events."""
    store = dna.StateStore(home)
    started_at = dna.utc_now() - timedelta(minutes=10)
    store.init_profile(name="Alex", level="B2", explanation_language="tr", at=started_at)
    identifier = store.roleplay_start("restaurant", at=started_at)["session"]["id"]
    dialogue = [
        (0, "partner", "Guten Abend. Haben Sie reserviert?"),
        (30, "learner", "Ja, wir haben eine reservierung für zwei Person."),
        (60, "partner", "Auf welchen Namen?"),
        (85, "learner", "Die Reservierung ist auf dem Namen Sahin."),
        (120, "partner", "Ich habe die Reservierung auf den Namen Sahin gefunden. Kommen später noch Gäste dazu?"),
        (150, "learner", "Ja, noch zwei Person kommen später."),
        (180, "partner", "Möchten Sie schon Getränke bestellen?"),
        (210, "learner", "Für drei Person bitte Wasser."),
        (245, "partner", "Wie viele Personen möchten eine Vorspeise?"),
        (280, "learner", "Vier Person möchten eine Suppe."),
        (310, "partner", "Alles klar. Möchten Sie sonst noch etwas?"),
        (355, "learner", "Nein, danke. Das ist alles."),
        (402, "partner", "Sehr gern. Ich bringe gleich die Getränke."),
    ]
    turns = []
    for index, (seconds, speaker, text) in enumerate(dialogue):
        turn = store.roleplay_turn(identifier, speaker=speaker, text=text, event_id=f"demo-message-{index}",
                                    at=started_at + timedelta(seconds=seconds))["utterance"]
        turns.append(turn)
    store.roleplay_stop(identifier, at=started_at + timedelta(seconds=402))
    for turn in turns:
        if turn["speaker"] != "learner":
            continue
        original = turn["text"]
        corrected = re.sub(r"\bPerson\b", "Personen", original.replace("reservierung", "Reservierung").replace("auf dem Namen", "auf den Namen"))
        patterns = []
        if re.search(r"\bPerson\b", original):
            patterns.append(("plural", "Person plural is Personen", "Der Plural von Person ist Personen.", None))
        if "reservierung" in original:
            patterns.append(("spelling", "German nouns are capitalized", "Nomen schreibt man groß.", None))
        if "auf dem Namen" in original:
            patterns.append(("preposition", "auf den Namen for reservations", "Eine Reservierung ist auf den Namen einer Person.", "auf den Namen"))
        for category, pattern, rule, label in patterns:
            store.record(original=original, corrected=corrected, category=category, pattern=pattern, rule=rule, label=label,
                         session_id=identifier, turn_id=turn["id"])
    for term, surface, meaning, index in [
        ("reservieren", "reserviert", "rezervasyon yapmak", 0),
        ("die Reservierung", "die Reservierung", "rezervasyon", 4),
        ("auf den Namen", "auf den Namen", "… adına", 4),
    ]:
        store.roleplay_vocab(identifier, term=term, surface=surface, meaning=meaning, turn_id=turns[index]["id"])
    store.roleplay_finish(identifier, at=started_at + timedelta(minutes=8))
    return identifier


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed and show a DeutschLoop demo profile")
    parser.add_argument("--home", help="State directory to seed (default: a fresh temporary directory)")
    parser.add_argument("--quiet", action="store_true", help="Only seed; print nothing but the state path")
    story = parser.add_mutually_exclusive_group()
    story.add_argument("--learning-loop", action="store_true", help="Show self-repair, remembered help, and next-day unaided use")
    story.add_argument("--speak", action="store_true", help="Show an uninterrupted restaurant scene and its recorded debrief")
    arguments = parser.parse_args(argv)
    dna._configure_streams()

    home = Path(arguments.home).expanduser() if arguments.home else Path(tempfile.mkdtemp(prefix="deutschloop-demo-"))
    if any(home.glob("*.json")):
        print(f"Refusing to seed a non-empty state directory: {home}", file=sys.stderr)
        return 2
    if arguments.speak:
        scene_id = seed_speaking_scene(home)
    else:
        (seed_learning_loop if arguments.learning_loop else seed)(home)
    if arguments.quiet:
        print(str(home))
        return 0

    if arguments.speak:
        result = dna.StateStore(home).roleplay_show(scene_id)
        print("DeutschLoop speaking demo: scripted dialogue, real engine evidence.")
        print(f"State directory: {home}")
        for turn in result["session"]["utterances"]:
            speaker = "Kellner" if turn["speaker"] == "partner" else "Alex"
            print(f"{speaker}: {turn['text']}")
        print()
        print(dna.render_roleplay_text(result))
        # The scene's words now wait in the deck for their first review tomorrow.
        print()
        print("$ python scripts/deutsch_loop.py vocab-list --format text")
        dna.main(["--home", str(home), "vocab-list", "--format", "text"])
        return 0

    mit_id = dna.mistake_id("case", "mit + dative")
    warten_id = dna.mistake_id("preposition", "warten auf + accusative")
    print("DeutschLoop demo: scripted learner, real engine — "
          + ("self-repair and next-day transfer." if arguments.learning_loop else "four months of learning."))
    print(f"State directory: {home}")
    screens = (
        ["recap", "--format", "card"],
        ["summary", "--format", "text"],
        ["show", mit_id, "--format", "text"],
        ["show", warten_id, "--format", "text"],
        ["due", "--format", "text"],
    )
    if arguments.learning_loop:
        screens = (["recap", "--format", "card"], ["show", mit_id, "--format", "text"])
    for command in screens:
        print()
        print(f"$ python scripts/deutsch_loop.py {' '.join(command)}")
        dna.main(["--home", str(home), *command])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
