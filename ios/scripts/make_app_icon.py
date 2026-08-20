#!/usr/bin/env python3
"""Generate the app icon.

Drawn programmatically so the artwork is original to this project — no
third-party or licensed assets are used. Re-run after changing the design:

    ./.venv/bin/python ios/scripts/make_app_icon.py

The mark is a page turning into a reflowed column of text: the left half keeps
the fixed, ruled look of a PDF page, the right half becomes loose flowing lines,
which is exactly what the app does.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz

SIZE = 1024
# Matches Theme.swift's navy accent so the icon, tint and UI agree.
INK = (0.10, 0.16, 0.31)
PAPER = (0.99, 0.99, 0.98)
ACCENT = (0.85, 0.88, 0.94)

OUTPUT = (
    Path(__file__).resolve().parent.parent
    / "PDFtoEPUB/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon.png"
)


def build() -> Path:
    doc = fitz.open()
    page = doc.new_page(width=SIZE, height=SIZE)

    # Background: the deep navy the app uses as its accent.
    page.draw_rect(fitz.Rect(0, 0, SIZE, SIZE), color=None, fill=INK)

    # The page: a rounded sheet, inset from the icon edges so it still reads
    # after iOS applies its own corner mask.
    sheet = fitz.Rect(232, 168, 792, 856)
    page.draw_rect(sheet, color=None, fill=PAPER, radius=0.06)

    # Left half: rigid, justified rules — a fixed PDF page.
    left_x0, left_x1 = 300, 494
    y = 268
    while y < 780:
        page.draw_line(
            fitz.Point(left_x0, y), fitz.Point(left_x1, y), color=INK, width=14
        )
        y += 46

    # Divider marking the transformation.
    page.draw_line(
        fitz.Point(512, 250), fitz.Point(512, 790), color=ACCENT, width=6
    )

    # Right half: the same text reflowed — ragged, breathing, resizable.
    right_x0 = 536
    widths = [188, 150, 178, 132, 190, 162, 120, 184, 144, 176, 110]
    y = 268
    for index, width in enumerate(widths):
        if y >= 780:
            break
        page.draw_line(
            fitz.Point(right_x0, y),
            fitz.Point(right_x0 + width, y),
            color=INK,
            width=12,
        )
        # Uneven leading, the way reflowed text actually sits.
        y += 44 + (6 if index % 3 == 0 else 0)

    # The page is already SIZE points square, so render 1:1 at 72 dpi.
    pixmap = page.get_pixmap(matrix=fitz.Identity, alpha=False)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(str(OUTPUT))
    doc.close()
    return OUTPUT


if __name__ == "__main__":
    path = build()
    print(f"wrote {path} ({path.stat().st_size // 1024} KB)")
    sys.exit(0)
