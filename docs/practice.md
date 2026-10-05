# Practise with DeutschLoop

[Back to the README](../README.md)


Invoke it with `/deutsch-loop` in Claude Code or `$deutsch-loop` in Codex, or write German and ask for feedback. No profile form or commands to memorize: the skill introduces itself in a few lines and gives you one small German task right away. If you already sent a text or requested a scene, it helps with that immediately.

### Your first minute

The welcome is brief. It uses your language when it knows it; after a bare `/deutsch-loop`, it starts in English and switches to the language you answer in:

```text
Hi! I'm DeutschLoop, your German practice partner. I correct what you write,
practise everyday situations with you, and remember the mistakes you repeat
and the hints that helped.

Let's start: what did you do today? Write one sentence in German.
Just starting? Complete: Ich heiße … (My name is …)

You can answer in your own language; I'll explain things in it.
```

There is no level test first. If your sentence has a mistake, you get a small hint instead of the answer, fix it yourself, and then use the same structure in a new situation. A correct first sentence gets a small step up instead, without a fake mistake or score. Your name and goals are optional. If you pause, the next session resumes where you left off. The full progress profile comes when you ask or at a later weekly review.

### Ask naturally

- **Correct my German.** Minimal correction, the reason, and the recurrence callback when a mistake comes back.
- **Let's review.** One due mistake at a time, each in a new situation, then the words due from your scenes.
- **Give me a hint.** Room to repair the sentence yourself; the help and outcome are remembered.
- **I have a job interview on Friday.** Start a saved preparation plan across scenes and chats, using your actual answers and recorded mistakes. [How preparation continues](missions.md).
- **Continue my interview preparation.** Resume its scene or next step, with the original goal and date preserved.
- **Roleplay Restaurant.** Fifteen frames with optional complications. No ordinary correction interruptions; at most three corrections in the debrief.
- **Let's practise words.** Words from your scenes come back after 1, 3, 7, 14, 30, and 60 days, each time in a new sentence you write yourself.
- **How am I doing?** The FehlerDNA profile, the root cause behind your weakest area, and a family drill for it.
- **That wasn't a mistake.** The agent reverts just that correction with `undo`, schedule included, or fixes the entry with `merge`, `rename`, or `forget`. A wrong merge can be undone too.

## Keep talking. Corrections come after.

Start with “Restoranda konuşalım” or `speak restaurant`. With the installed skill, you can use `/deutsch-loop speak restaurant` in Claude Code or `$deutsch-loop speak restaurant` in Codex.

```text
Kellner: Guten Abend. Haben Sie reserviert?
You:     Ja wir haben eine reservierung für zwei person.
Kellner: Auf welchen Namen?
```

The tutor stays in character and waits for your actual answers. Ordinary mistakes do not interrupt the scene. After roughly five minutes, or when you say “bitir”, it leaves the character and puts a short debrief in its reply: scene duration, up to three important corrections, useful vocabulary from the conversation, and any recurring patterns with counts from that scene. Saving the report is not the final step; the reply must show it. New words from the scene go into your word deck and come back in spaced reviews from the next day, each time in a new situation. If a report did not appear, “Son konuşmanın değerlendirmesini göster” retrieves the saved result without counting your mistakes again.

Try the complete scripted example through the real engine:

```bash
python scripts/demo.py --speak
```

The demo produces a 6m 42s scene from recorded timestamps, including four separate occurrences of the `Person → Personen` pattern. That is elapsed scene time, including both participants and pauses. The skill does not measure how long your microphone was active. Text works directly; host-provided speech transcripts can use the same flow, with spelling and punctuation excluded from speech feedback. Audio capture and pronunciation scoring are not included.

## More roleplay situations

The opening and partner role are prepared; the conversation continues from your answers. You can choose a complication, ask for simpler language, or use your own real details. These requests are examples, not facts saved about you:

| Frame | Example request |
| --- | --- |
| `alltag` | “Komşumla konuşalım. Hafta sonu için plan yapalım ama saatlerimiz uyuşmasın.” |
| `arbeit` | “İş arkadaşına geciken bir işi anlatıp yeni bir teslim tarihi konuşalım.” |
| `arzt` | “Kurgusal bir doktor randevusunda şikâyetimi anlatayım; bir soruyu anlamayıp tekrar isteyeyim.” |
| `wohnung` | “Ev bakmaya gidelim. Gürültü ve taşınma tarihi hakkında soru sorayım.” |
| `restaurant` | “Restoranda rezervasyonum bulunamasın; birlikte bir çözüm bulalım.” |
| `bewerbung` | “İş görüşmesi yapalım. Bir proje anlatayım, ardından zor bir takip sorusu sor.” |
| `praesentation` | “Projemi sunayım. Dinleyici bütçeyi sorgulasın ve daha basit açıklama istesin.” |
| `behoerde` | “Kurgusal bir Bürgeramt randevusunda eksik evrakı ve sonraki adımı sorayım.” |
| `bahnhof` | “Trenim geciksin ve aktarmayı kaçırma ihtimalim olsun. Alternatif bağlantı sorayım.” |
| `einkaufen` | “Yanlış beden bir ceketi değiştirmek isteyeyim; istediğim beden bulunmasın.” |
| `apotheke` | “Eczanede kurgusal bir konuşma yapalım. Bir ambalajdaki Almanca kelimenin anlamını sorayım.” |
| `telefon` | “Telefonda randevumu değiştireyim. İlk önerilen saat bana uymasın.” |
| `schule` | “Öğretmenle kurgusal bir ödev sorununu konuşup küçük bir sonraki adım belirleyelim.” |
| `hotel` | “Otele giriş yapayım. Odam rezervasyondaki özelliklerle uyuşmasın.” |
| `kundenservice` | “Teslim edilmeyen siparişi müşteri hizmetlerine anlatıp çözüm isteyeyim.” |

The CLI catalog includes an opening and two variations per frame:

```bash
python scripts/deutsch_loop.py scenarios
python scripts/deutsch_loop.py speak interview
python scripts/deutsch_loop.py speak train
python scripts/deutsch_loop.py speak phone
```

For an actual upcoming event, ask for [continuing preparation](missions.md) so that the next scene uses the previous one's evidence instead of starting a separate roleplay.
