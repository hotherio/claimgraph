#!/usr/bin/env python3
"""gen_og.py: render branded 1200x630 social cards for the claimgraph site pages.

The YASSG approach, on the shared CKC brand: warm paper, orange accent bar, the
{C logo, the page title in the monospace brand font, a project byline. Fonts are
bundled under scripts/fonts/ (DejaVu Sans Mono, freely redistributable) so the
build is reproducible. Run after editing the docs pages:

    .venv/bin/python scripts/gen_og.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
FONTS = os.path.join(ROOT, "scripts", "fonts")
LOGO = os.path.join(DOCS, "assets", "logo.png")

OG_W, OG_H = 1200, 630
PAPER = (247, 244, 238)
INK = (26, 26, 26)
ACCENT = (231, 82, 5)
EYEBROW = "Conventional Knowledge Commits"

# page slug -> (output card name, title)
PAGES = {
    "home": "The ClaimGraph",
    "graph": "The ClaimGraph, live",
    "how-it-works": "How the ClaimGraph works",
    "blueprint": "The cross-history honesty layer",
}


def _wrap(draw, text, font, max_width):
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def card(title, out_path):
    img = Image.new("RGB", (OG_W, OG_H), PAPER)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 14, OG_H], fill=ACCENT)

    margin = 84
    logo_h = 90
    lg = Image.open(LOGO).convert("RGBA")
    lg = lg.resize((round(lg.width * logo_h / lg.height), logo_h), Image.LANCZOS)
    img.paste(lg, (margin, 58), lg)

    tfont = ImageFont.truetype(os.path.join(FONTS, "DejaVuSansMono-Bold.ttf"), 64)
    lines = _wrap(draw, title, tfont, OG_W - margin - 70)[:4]
    line_h = int(tfont.size * 1.16)
    block_h = line_h * len(lines)
    top, bottom = 58 + logo_h, OG_H - 112
    y = top + (bottom - top - block_h) // 2
    for line in lines:
        draw.text((margin, y), line, font=tfont, fill=INK)
        y += line_h

    bfont = ImageFont.truetype(os.path.join(FONTS, "DejaVuSansMono.ttf"), 27)
    draw.text((margin, OG_H - 78), EYEBROW.upper(), font=bfont, fill=ACCENT)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, "PNG")
    print("  wrote", os.path.relpath(out_path, ROOT))


if __name__ == "__main__":
    for slug, title in PAGES.items():
        card(title, os.path.join(DOCS, "assets", "og", slug + ".png"))
    print("done.")
