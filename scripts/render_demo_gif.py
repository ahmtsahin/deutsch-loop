#!/usr/bin/env python3
"""Render readable README stories from engine records or a captured conversation.

Pillow is only needed for this contributor tool. The learning and history stories
use scripted learner inputs; the conversation and session stories replay real host replies.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import tempfile

try:
    from PIL import Image, ImageDraw, ImageFont
except ModuleNotFoundError as exc:
    raise SystemExit("Install the renderer dependency: python -m pip install pillow") from exc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import demo  # noqa: E402
import deutsch_loop as dna  # noqa: E402

WIDTH, HEIGHT = 720, 800
QUOTE_SIZE = 42  # 18 CSS px when GitHub displays this image at 309 px wide.
QUOTATION_MARKS = "„“”\"‚‘’'«»"
COLORS = {
    "page": "#11111b", "panel": "#1b1b2b", "border": "#45475a",
    "text": "#e4e7f5", "muted": "#b2b8ce", "accent": "#d9ff45",
    "blue": "#9ac6ff", "green": "#b5edb0", "red": "#ff97b4",
}
FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/consola.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
    Path("/usr/share/fonts/truetype/liberation2/LiberationMono-Regular.ttf"),
    Path("/System/Library/Fonts/SFNSMono.ttf"),
)


def find_font(explicit: str | None) -> Path:
    for path in (Path(explicit).expanduser(),) if explicit else FONT_CANDIDATES:
        if path.is_file():
            return path
    raise ValueError("No monospaced font found; pass --font PATH")


def row(label: str, text: str, color: str = "text", *highlight: str) -> dict:
    return {"label": label, "text": text, "color": color, "highlight": highlight}


def collect_learning_screens() -> list[dict]:
    with tempfile.TemporaryDirectory(prefix="deutschloop-learning-gif-") as directory:
        demo.seed_learning_loop(Path(directory))
        mistake = dna.StateStore(Path(directory)).show(dna.mistake_id("case", "mit + dative"))
    proof = dna.learning_proof_view(mistake["learning_proof"])
    if not proof or proof["independent"]["source"] != "spontaneous":
        raise ValueError("The opening frame requires recorded later, unaided use")
    support, independent = proof["with_help"], proof["independent"]
    practice = next(item for item in mistake["coaching_history"] if item["outcome"] == "independent")
    return [
        {"stage": "THE NEXT DAY", "title": "You did it yourself.", "duration": 4200,
         "rows": [row("YESTERDAY / WITH A HINT", support["answer"], "text", "meinem"),
                  row("TODAY / WITHOUT HELP", independent["answer"], "green", "unseren")],
         "footer": "Same pattern. A new sentence."},
        {"stage": "HOW IT STARTED", "title": "A hint. Your turn.", "duration": 3400,
         "rows": [row("YOU WROTE", mistake["first_example"]["original"], "red", "mein"),
                  row("YOUR TUTOR", support["hint"], "blue", "wem")],
         "footer": "You get room to find the fix."},
        {"stage": "YOU FOUND THE FIX", "title": "Now try it again.", "duration": 3400,
         "rows": [row("YOUR REPAIR", support["answer"], "green", "meinem"),
                  row("NEW PRACTICE / NO HINT", practice["answer"], "green", "dem")],
         "footer": "Your tutor remembers what helped."},
    ]


def collect_history_screens() -> list[dict]:
    with tempfile.TemporaryDirectory(prefix="deutschloop-history-gif-") as directory:
        demo.seed(Path(directory))
        mistake = dna.StateStore(Path(directory)).show(dna.mistake_id("preposition", "warten auf + accusative"))
    wrong = sorted(mistake["examples"], key=lambda item: dna.parse_moment(item["seen_at"]))
    gap = (dna.parse_moment(wrong[-1]["seen_at"]) - dna.parse_moment(wrong[-2]["seen_at"])).days
    original = mistake["first_example"]
    hint = mistake["helpful_hint"]
    return [
        {"stage": "AN OLD MISTAKE RETURNS", "title": f"{gap} days later.", "duration": 4500,
         "rows": [row("YOUR FIRST MISTAKE", original["original"], "red", "warte"),
                  row("IT COMES BACK", wrong[-1]["original"], "red", "warte")],
         "footer": "The first sentence is still saved."},
        {"stage": "YOUR TUTOR REMEMBERS", "title": "Pick up from here.", "duration": 4500,
         "rows": [row("THE ORIGINAL CORRECTION", original["corrected"], "green", "auf"),
                  row("THE HINT THAT HELPED", hint["hint"], "blue", "auf")],
         "footer": "Back in practice, with your history."},
    ]


def collect_board() -> tuple[str, str]:
    """The session board of the four-month demo learner, exactly as `recap --format card` prints it."""
    with tempfile.TemporaryDirectory(prefix="deutschloop-board-") as directory:
        demo.seed(Path(directory))
        recap = dna.StateStore(Path(directory)).recap()
    return recap["profile"]["name"], dna.render_recap_card(recap)


def draw_comeback(draw: ImageDraw.ImageDraw, x: float, y: int, cell: float, color: str, scale: float = 1) -> None:
    """Draw ↺ inside one character cell; common monospaced fonts such as Consolas lack the glyph."""
    size = min(cell, 20 * scale)
    left, top = x + (cell - size) / 2, y + 12 * scale
    # Open at the upper right, like the font glyph; the arrowhead sits on the top end.
    draw.arc((left, top, left + size, top + size), start=315, end=270, fill=COLORS[color], width=round(3 * scale))
    middle = left + size / 2
    draw.polygon([(middle + 7 * scale, top + scale), (middle - 2 * scale, top - 5 * scale),
                  (middle - 2 * scale, top + 7 * scale)], fill=COLORS[color])


def draw_header(draw: ImageDraw.ImageDraw, width: int, stage: str, heading: str,
                label: ImageFont.FreeTypeFont, title: ImageFont.FreeTypeFont) -> None:
    draw.text((64, 44), "DeutschLoop", font=label, fill=COLORS["accent"])
    link = "github.com/ahmtsahin/deutsch-loop"
    draw.text((width - 64 - label.getlength(link), 44), link, font=label, fill=COLORS["muted"])
    draw.text((64, 112), stage, font=label, fill=COLORS["accent"])
    draw.text((64, 156), heading, font=title, fill=COLORS["text"])


def draw_card(draw: ImageDraw.ImageDraw, lines: list[str], left: int, top: int,
              mono: ImageFont.FreeTypeFont, line_height: int, scale: float = 1) -> None:
    """Draw the board as the engine prints it, with the ladders and comeback markers as shapes.

    The shapes are sized for 34 px type; `scale` adapts them to another size.
    """
    cell = mono.getlength(" ")

    def paint(x: float, y: int, text: str, color: str) -> float:
        draw.text((x, y), text, font=mono, fill=COLORS[color])
        return x + mono.getlength(text)

    for index, line in enumerate(lines):
        x, y = left, top + index * line_height
        ladder = re.search(r"[▰▱]+", line)
        if index == 0:
            head, _, rest = line.partition(" · ")
            paint(paint(x, y, head, "accent"), y, f" · {rest}", "text")
        elif not ladder:
            paint(x, y, line, "muted")
        else:
            # Label, review ladder drawn as boxes, then counts, the comeback marker, and the due time.
            x = paint(x, y, line[: ladder.start()], "text")
            steps = ladder.group(0)
            gap = 4 * scale
            box = (cell * len(steps) - 2 * gap) / len(steps) - gap
            for number, step in enumerate(steps):
                start = x + gap + number * (box + gap)
                shape = (start, y + 12 * scale, start + box, y + 32 * scale)
                if step == "▰":
                    draw.rounded_rectangle(shape, radius=3, fill=COLORS["accent"])
                else:
                    draw.rounded_rectangle(shape, radius=3, outline=COLORS["border"], width=2)
            x += cell * len(steps)
            for part in re.findall(r"↺|jetzt fällig|[^↺]+?(?=↺|jetzt fällig|$)", line[ladder.end():]):
                if part == "↺":
                    draw_comeback(draw, x, y, cell, "red", scale)
                    x += cell
                else:
                    x = paint(x, y, part, "accent" if part == "jetzt fällig" else "muted")


def render_board(name: str, card: str, font_path: Path) -> Image.Image:
    width, height = 1600, 900
    label = ImageFont.truetype(str(font_path), 30)
    title = ImageFont.truetype(str(font_path), 64)
    mono = ImageFont.truetype(str(font_path), 34)
    lines = card.splitlines()
    image = Image.new("RGB", (width, height), COLORS["page"])
    draw = ImageDraw.Draw(image)
    draw_header(draw, width, "HOW EVERY SESSION STARTS", f"Hallo {name}!", label, title)

    top, line_height, pad = 262, 50, 48
    bottom = top + 80 + line_height * len(lines) - 14
    if max(mono.getlength(line) for line in lines) > width - 128 - 2 * pad or bottom > height - 110:
        raise ValueError("The board does not fit the image; shorten the demo board")
    draw.rounded_rectangle((64, top, width - 64, bottom), radius=24, fill=COLORS["panel"], outline=COLORS["border"], width=2)
    draw_card(draw, lines, 64 + pad, top + 40, mono, line_height)
    draw.text((64, bottom + 34), "Your own mistakes, ordered by what is due today.", font=label, fill=COLORS["text"])
    draw.text((64, bottom + 78), "Scripted learner / real engine output", font=label, fill=COLORS["muted"])
    return image


def render_social(card: str, font_path: Path) -> Image.Image:
    """The board at GitHub's social preview size, 1280 × 640."""
    width, height = 1280, 640
    label = ImageFont.truetype(str(font_path), 24)
    title = ImageFont.truetype(str(font_path), 54)
    mono = ImageFont.truetype(str(font_path), 26)
    lines = card.splitlines()
    image = Image.new("RGB", (width, height), COLORS["page"])
    draw = ImageDraw.Draw(image)
    draw.text((56, 34), "DeutschLoop", font=label, fill=COLORS["accent"])
    hosts = "for Claude Code and Codex"
    draw.text((width - 56 - label.getlength(hosts), 34), hosts, font=label, fill=COLORS["muted"])
    draw.text((56, 78), "A German tutor that", font=title, fill=COLORS["text"])
    draw.text((56, 140), "remembers your mistakes.", font=title, fill=COLORS["text"])

    top, line_height, pad = 232, 36, 40
    bottom = top + 2 * 30 + line_height * len(lines) - 8
    if max(mono.getlength(line) for line in lines) > width - 112 - 2 * pad or bottom > height - 56:
        raise ValueError("The board does not fit the social preview; shorten the demo board")
    draw.rounded_rectangle((56, top, width - 56, bottom), radius=20, fill=COLORS["panel"], outline=COLORS["border"], width=2)
    draw_card(draw, lines, 56 + pad, top + 30, mono, line_height, scale=26 / 34)
    draw.text((56, bottom + 16), "Local memory. No API key. Scripted learner, real engine output.",
              font=label, fill=COLORS["muted"])
    return image


def collect_session(source: Path) -> dict:
    """The opening reply of a recorded chat: greeting, engine board, quoted sentence, and new task."""
    recording = json.loads(source.read_text(encoding="utf-8"))
    reply, card, quoted = recording["exchanges"][0]["tutor"], recording["card"], recording["evidence"]["quoted"]
    if card not in reply:
        raise ValueError("The recorded reply does not show the engine's board")
    before, _, after = reply.partition(card)
    # plain() removes the code fence, which leaves its paragraph empty.
    paragraphs = [text for text in map(plain, after.split("\n\n")) if text]
    if len(paragraphs) < 2 or quoted["original"] not in paragraphs[0]:
        raise ValueError("The recorded reply does not quote the stored sentence before its task")
    lead, sentence, rest = paragraphs[0].partition(quoted["original"])
    lead, rest = lead.rstrip(), rest.strip()
    if lead[-1:] in QUOTATION_MARKS and rest[:1] in QUOTATION_MARKS:
        # The quotation marks around the sentence stay with it.
        lead, sentence = lead[:-1].rstrip(), f"{lead[-1]}{sentence}{rest[0]}"
    changed = [word for word in quoted["original"].rstrip(".").split()
               if word not in quoted["corrected"].rstrip(".").split()]
    return {"greeting": plain(before.replace("```text", "")), "card": card.splitlines(),
            "lead": lead, "sentence": sentence, "changed": changed, "task": paragraphs[1]}


def render_session(session: dict, font_path: Path) -> Image.Image:
    width = 1600
    label = ImageFont.truetype(str(font_path), 30)
    title = ImageFont.truetype(str(font_path), 64)
    mono = ImageFont.truetype(str(font_path), 34)
    top, line_height, pad = 262, 50, 48
    inner = width - 128 - 2 * pad
    task = wrap_text(session["task"], mono, inner)
    card = session["card"]
    if max(mono.getlength(line) for line in card + [session["lead"], session["sentence"]]) > inner:
        raise ValueError("The recorded opening does not fit the image")
    # Greeting, board, quoted sentence, and task, separated by one empty line each.
    rows = 1 + 1 + len(card) + 1 + 2 + 1 + len(task)
    bottom = top + 80 + line_height * rows - 14
    image = Image.new("RGB", (width, bottom + 140), COLORS["page"])
    draw = ImageDraw.Draw(image)
    draw_header(draw, width, "A NEW CHAT / FOUR MONTHS IN", "It starts with your own sentence.", label, title)
    draw.rounded_rectangle((64, top, width - 64, bottom), radius=24, fill=COLORS["panel"], outline=COLORS["border"], width=2)

    left, y = 64 + pad, top + 40
    draw.text((left, y), session["greeting"], font=mono, fill=COLORS["text"])
    y += 2 * line_height
    draw_card(draw, card, left, y, mono, line_height)
    y += (len(card) + 1) * line_height
    draw.text((left, y), session["lead"], font=mono, fill=COLORS["muted"])
    y += line_height
    x = left
    for part in re.findall(r"\s+|\S+", session["sentence"]):
        marked = part.strip(".,?!:;" + QUOTATION_MARKS) in session["changed"]
        draw.text((x, y), part, font=mono, fill=COLORS["red"])
        if marked:
            draw.line((x, y + 40, x + mono.getlength(part), y + 40), fill=COLORS["red"], width=3)
        x += mono.getlength(part)
    y += 2 * line_height
    for line in task:
        draw.text((left, y), line, font=mono, fill=COLORS["text"])
        y += line_height
    draw.text((64, bottom + 34), "Your patterns, a sentence you got wrong, and a new situation for it.",
              font=label, fill=COLORS["text"])
    draw.text((64, bottom + 78), "Actual Claude Code reply / scripted learner history", font=label, fill=COLORS["muted"])
    return image


def plain(text: str) -> str:
    """Remove emphasis markers for the visual replay, preserving the actual words."""
    return re.sub(r"[*_`]", "", text).strip()


def checked_excerpt(text: str, excerpt: str) -> str:
    if excerpt not in plain(text):
        raise ValueError(f"The recording does not contain this excerpt: {excerpt!r}")
    return excerpt


def collect_conversation_screens(source: Path) -> list[dict]:
    recording = json.loads(source.read_text(encoding="utf-8"))
    first, repair, fresh = recording["exchanges"]
    # Excerpts are checked against the captured replies, never invented by the renderer.
    return [
        {"stage": "CLAUDE CODE / CHAT 1", "title": "A real exchange.", "duration": 5000,
         "rows": [row("SCRIPTED LEARNER", checked_excerpt(first["learner"], "Ich spreche mit mein Chef."), "red", "mein"),
                  row("TUTOR / EXCERPT", checked_excerpt(first["tutor"], "Which case does mit take?"), "blue", "mit")],
         "footer": "Actual reply. Time compressed."},
        {"stage": "CLAUDE CODE / CHAT 1", "title": "You make the repair.", "duration": 4500,
         "rows": [row("SCRIPTED LEARNER", checked_excerpt(repair["learner"], "Ich spreche mit meinem Chef."), "green", "meinem"),
                  row("TUTOR / EXCERPT", checked_excerpt(repair["tutor"], "mein becomes meinem"), "blue", "meinem")],
         "footer": "The hint and repair are saved."},
        {"stage": "CLAUDE CODE / A NEW CHAT", "title": "The memory carries on.", "duration": 6500,
         "rows": [row("SCRIPTED LEARNER", checked_excerpt(fresh["learner"], "Heute habe ich mit unseren Kunden gesprochen."), "green", "unseren"),
                  row("IT RECALLS THE SAME HINT", checked_excerpt(fresh["tutor"], recording["evidence"]["coaching_history"][0]["hint"]), "blue")],
         "footer": "New chat. Same day. Shared memory."},
    ]


def wrap_text(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        if font.getlength(word) > width:
            raise ValueError(f"A word does not fit: {word!r}")
        candidate = f"{current} {word}".strip()
        if current and font.getlength(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    return lines + ([current] if current else [])


def draw_quote(draw: ImageDraw.ImageDraw, text: str, position: tuple[int, int],
               font: ImageFont.FreeTypeFont, color: str, highlights: tuple[str, ...]) -> None:
    lines = wrap_text(text, font, WIDTH - 112)
    if len(lines) > 3:
        raise ValueError(f"Quote exceeds three readable lines; shorten the excerpt: {text!r}")
    left, top = position
    for index, line in enumerate(lines):
        x, y = left, top + index * 50
        for part in re.findall(r"\s+|\S+", line):
            marked = part.strip(".,?!:;„“\"'").casefold() in {word.casefold() for word in highlights}
            draw.text((x, y), part, font=font, fill=COLORS[color] if marked or not highlights else COLORS["text"])
            width = font.getlength(part)
            if marked:
                draw.line((x, y + 44, x + width, y + 44), fill=COLORS[color], width=3)
            x += width


def render_frame(screen: dict, index: int, count: int, font_path: Path, *,
                 second_row: bool = True, conversation: bool = False) -> Image.Image:
    heading = ImageFont.truetype(str(font_path), 50)
    quote = ImageFont.truetype(str(font_path), QUOTE_SIZE)
    label = ImageFont.truetype(str(font_path), 28)
    image = Image.new("RGB", (WIDTH, HEIGHT), COLORS["page"])
    draw = ImageDraw.Draw(image)
    draw.text((32, 22), "DeutschLoop", font=label, fill=COLORS["accent"])
    step = f"{index + 1} / {count}"
    draw.text((WIDTH - 32 - label.getlength(step), 22), step, font=label, fill=COLORS["muted"])
    for text, font, y, color in ((screen["stage"], label, 76, "accent"),
                               (screen["title"], heading, 115, "text")):
        if font.getlength(text) > WIDTH - 64:
            raise ValueError(f"Heading is too wide: {text!r}")
        draw.text((32, y), text, font=font, fill=COLORS[color])

    for number, item in enumerate(screen["rows"]):
        if number == 1 and not second_row:
            continue
        top = 195 + number * 240
        draw.rounded_rectangle((32, top, WIDTH - 32, top + 222), radius=20,
                               fill=COLORS["panel"], outline=COLORS["border"], width=2)
        if conversation:
            draw.line((33, top + 22, 33, top + 200), fill=COLORS[item["color"]], width=4)
        if label.getlength(item["label"]) > WIDTH - 112:
            raise ValueError(f"Row label is too wide: {item['label']!r}")
        draw.text((56, top + 16), item["label"], font=label, fill=COLORS["muted"])
        draw_quote(draw, item["text"], (56, top + 66), quote, item["color"], item["highlight"])

    if label.getlength(screen["footer"]) > WIDTH - 64:
        raise ValueError(f"Footer is too wide: {screen['footer']!r}")
    draw.text((32, 692), screen["footer"], font=label, fill=COLORS["text"])
    disclosure = "Recorded chat / excerpt replay" if conversation else "Scripted learner / real engine"
    draw.text((32, 731), disclosure, font=label, fill=COLORS["muted"])
    track = (WIDTH - 64 - (count - 1) * 10) / count
    for step_index in range(count):
        x = 32 + step_index * (track + 10)
        draw.rounded_rectangle((x, 777, x + track, 781), radius=2,
                               fill=COLORS["accent"] if step_index == index else COLORS["border"])
    return image


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--story", choices=("history", "learning-loop", "conversation", "board", "session", "social"),
                        default="learning-loop")
    parser.add_argument("--output", type=Path,
                        help="Output GIF; a static PNG is saved beside it (board, session, social: the PNG itself)")
    parser.add_argument("--font", help="Path to a monospaced TrueType font")
    parser.add_argument("--frames-dir", type=Path, help="Save full-size and 309 px wide PNGs for review")
    parser.add_argument("--transcript", type=Path,
                        help="Recording to replay (default: demo/conversation.json, or demo/session.json for session)")
    arguments = parser.parse_args(argv)
    font = find_font(arguments.font)
    if arguments.story in ("board", "session", "social"):
        output = arguments.output or ROOT / "demo" / f"{arguments.story}.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        if arguments.story == "board":
            image, name = render_board(*collect_board(), font), "session board"
        elif arguments.story == "social":
            image, name = render_social(collect_board()[1], font), "social preview"
        else:
            source = arguments.transcript or ROOT / "demo" / "session.json"
            image, name = render_session(collect_session(source), font), "recorded opening"
        image.save(output)
        print(f"Rendered the {name} to {output}")
        return 0
    if arguments.story == "learning-loop":
        screens, filename = collect_learning_screens(), "learning-loop"
    elif arguments.story == "history":
        screens, filename = collect_history_screens(), "history"
    else:
        screens, filename = collect_conversation_screens(arguments.transcript or ROOT / "demo" / "conversation.json"), "conversation"
    frames, durations, complete = [], [], []
    for index, screen in enumerate(screens):
        conversation = arguments.story == "conversation"
        full = render_frame(screen, index, len(screens), font, conversation=conversation)
        complete.append(full)
        # Let the learner message arrive before the recorded tutor reply.
        if conversation:
            frames.append(render_frame(screen, index, len(screens), font, second_row=False, conversation=True))
            durations.append(600)
        frames.append(full)
        durations.append(screen["duration"] - (600 if conversation else 0))
    output = arguments.output or ROOT / "demo" / f"{filename}.gif"
    output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(output, save_all=True, append_images=frames[1:], duration=durations,
                   loop=0, optimize=True, disposal=2)
    # The first complete frame is also the opening result, so no waiting is needed.
    complete[0].save(output.with_suffix(".png"))
    if arguments.frames_dir:
        arguments.frames_dir.mkdir(parents=True, exist_ok=True)
        for index, frame in enumerate(complete, 1):
            frame.save(arguments.frames_dir / f"{filename}-{index}.png")
            frame.resize((309, round(HEIGHT * 309 / WIDTH)), Image.Resampling.LANCZOS).save(
                arguments.frames_dir / f"{filename}-{index}-mobile.png")
    print(f"Rendered {len(screens)} scenes / {sum(durations) / 1000:g}s to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
