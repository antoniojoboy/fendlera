#!/usr/bin/env python3
"""
screenread.py - capture the screen and read each window separately.

    python3 screenread.py            # survey + per-window text
    python3 screenread.py --spec     # label/value pairs only

Per-window OCR, one single-threaded tesseract process per window in parallel
(tesseract's own guidance: OMP_THREAD_LIMIT=1 and parallelise outside).
Text never smears across applications, and every line knows which app it
came from.

Exclusion is per window, by title. A banking tab that is open but not
focused is still on screen; checking only the focused window (the earlier
design) would have read it anyway.

Requires: tesseract-ocr, python packages mss and pillow.
"""

from __future__ import annotations

import argparse
import collections
import os
import re
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from windows import Win, list_windows

PRICE = re.compile(r"[\$£€]\s?(\d[\d,]*(?:\.\d{1,2})?)")
NOISE_LINE = re.compile(r"^[\W_]{0,3}$")
MIN_CONF = 45.0

EXCLUDE_DEFAULT = ["password", "passwd", "keepass", "bitwarden", "1password",
                   "lastpass", "private browsing", "incognito", "bank",
                   "netbank", "commbank", "westpac", "anz ", "nab ", "signal",
                   "whatsapp", "authenticator", "credential", "secret", ".env"]


# ------------------------------------------------------------------ capture
def grab():
    """Full-screen PIL image of monitor 1."""
    import mss
    import mss.tools
    from PIL import Image
    path = tempfile.mktemp(suffix=".png")
    with (getattr(mss, "MSS", mss.mss)()) as sct:
        shot = sct.grab(sct.monitors[1])
        mss.tools.to_png(shot.rgb, shot.size, output=path)
    img = Image.open(path).convert("RGB")
    os.unlink(path)
    return img


# ------------------------------------------------------------------ model
@dataclass
class Block:
    """A tesseract block. On a spec sheet: one labelled row. On a listings
    grid: one card."""
    lines: list
    top: int

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.lines)).strip()

    @property
    def prices(self) -> list[float]:
        return [float(p.replace(",", "")) for p in PRICE.findall(self.text)]

    def spec_pair(self) -> tuple[str, str] | None:
        """Short first line, longer remainder, no price: label + value."""
        if self.prices or len(self.lines) < 2:
            return None
        label = self.lines[0].strip()
        value = " ".join(l.strip() for l in self.lines[1:]).strip()
        if 2 < len(label) <= 28 and len(value) >= 8 and not PRICE.search(label):
            return label, value[:160]
        return None


@dataclass
class WindowText:
    win: Win
    text: str = ""
    blocks: list = field(default_factory=list)
    seconds: float = 0.0
    excluded: bool = False
    hidden: bool = False

    def spec_pairs(self) -> list[tuple[str, str]]:
        return [p for p in (b.spec_pair() for b in self.blocks) if p]


# ------------------------------------------------------------------ occlusion
def occluders(win: Win, front: list[Win]) -> list[tuple[int, int, int, int]]:
    """Rects (in the window's own crop coordinates) covered by windows in
    front of it. A window 90% behind another passed the old 'fully covered'
    test, and its crop returned the front window's pixels - LibreOffice
    'said' VS Code's terminal."""
    ax, ay, ax2, ay2 = win.rect
    out = []
    for f in front:
        bx, by, bx2, by2 = f.rect
        ix, iy, ix2, iy2 = max(ax, bx), max(ay, by), min(ax2, bx2), min(ay2, by2)
        if ix2 > ix and iy2 > iy:
            out.append((ix - ax, iy - ay, ix2 - ax, iy2 - ay))
    return out


def visible_fraction(win: Win, covered: list[tuple[int, int, int, int]]) -> float:
    """Approximate: sums covered rects, so overlapping occluders can
    over-count and make a window look MORE hidden. Safe direction."""
    if win.area <= 0:
        return 0.0
    hidden = sum((x2 - x1) * (y2 - y1) for x1, y1, x2, y2 in covered)
    return max(0.0, 1.0 - hidden / win.area)


MIN_VISIBLE = 0.15
STRIP_W = 1200


# ------------------------------------------------------------------ layout
# Tesseract's word boxes are reliable; its page segmentation on a screenshot
# is not. Default mode (psm 3) treats a window as a page of prose, so a
# terminal panel and an editor at the same height become one line, and a grid
# of spec cards becomes one block. So: psm 11 (sparse - words only), then
# lines and blocks are grouped here, from geometry.

@dataclass
class Word:
    text: str
    left: int
    top: int
    width: int
    height: int


def words_from_tsv(raw: str) -> list[Word]:
    out = []
    for row in raw.splitlines()[1:]:
        f = row.split("\t")
        if len(f) < 12 or not f[11].strip():
            continue
        try:
            conf = float(f[10])
            l, t, w, h = int(f[6]), int(f[7]), int(f[8]), int(f[9])
        except ValueError:
            continue
        if conf < MIN_CONF or h <= 0:
            continue
        out.append(Word(f[11].strip(), l, t, w, h))
    return out


def group_lines(words: list[Word]) -> list[dict]:
    """Words on one visual row, not separated by a wide gap. A gap wider than
    ~2.5 character widths is a column boundary, not a space."""
    if not words:
        return []
    words = sorted(words, key=lambda w: (w.top + w.height / 2, w.left))
    rows: list[list[Word]] = []
    row_cy: list[float] = []                 # running mean centre of each row
    for w in words:
        cy = w.top + w.height / 2
        # Compare against the row's MEAN, not its last word: comparing to the
        # last word lets rows 10px apart chain into one.
        if rows and abs(cy - row_cy[-1]) <= 0.5 * w.height:
            rows[-1].append(w)
            row_cy[-1] += (cy - row_cy[-1]) / len(rows[-1])
        else:
            rows.append([w]); row_cy.append(cy)
    lines = []
    for row in rows:
        row.sort(key=lambda w: w.left)
        seg = [row[0]]
        for prev, w in zip(row, row[1:]):
            char_w = max(4.0, prev.width / max(1, len(prev.text)))
            if w.left - (prev.left + prev.width) > 2.5 * char_w + 0.6 * prev.height:
                lines.append(seg); seg = [w]
            else:
                seg.append(w)
        lines.append(seg)
    out = []
    for seg in lines:
        text = " ".join(w.text for w in seg)
        if NOISE_LINE.match(text):
            continue
        out.append({"text": text, "left": seg[0].left,
                    "top": min(w.top for w in seg),
                    "bottom": max(w.top + w.height for w in seg),
                    "height": max(w.height for w in seg)})
    out.sort(key=lambda l: (l["top"], l["left"]))
    return out


def group_blocks(lines: list[dict]) -> list[Block]:
    """Consecutive lines with aligned left edges and a small vertical gap form
    one block - a card, a labelled row, a paragraph."""
    blocks: list[list[dict]] = []
    for l in lines:
        placed = False
        for b in blocks:
            last = b[-1]
            gap = l["top"] - last["bottom"]
            aligned = abs(l["left"] - b[0]["left"]) <= max(40, 1.5 * last["height"])
            if aligned and -0.3 * last["height"] <= gap <= 1.4 * last["height"]:
                b.append(l); placed = True; break
        if not placed:
            blocks.append([l])
    out = []
    for b in blocks:
        ls = [l["text"] for l in b]
        if sum(len(x) for x in ls) >= 4:
            out.append(Block(lines=ls, top=b[0]["top"]))
    out.sort(key=lambda bl: bl.top)
    return out


def parse_tsv(raw: str) -> tuple[str, list[Block]]:
    """Pure: tesseract TSV -> (reading-order text, geometry-grouped blocks)."""
    lines = group_lines(words_from_tsv(raw))
    return "\n".join(l["text"] for l in lines), group_blocks(lines)


def _tesseract_tsv(img) -> str:
    path = tempfile.mktemp(suffix=".png")
    img.save(path)
    try:
        return subprocess.run(["tesseract", path, "stdout", "--psm", "11", "tsv"],
                              capture_output=True, text=True, timeout=120,
                              env={**os.environ, "OMP_THREAD_LIMIT": "1"}).stdout
    except Exception:
        return ""
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _strips(img):
    """Wide windows OCR'd as overlapping vertical strips in parallel. This is
    parallelism inside one window, not region semantics - the window is
    still the unit of meaning."""
    W, H = img.size
    n = max(1, -(-W // STRIP_W))
    if n == 1:
        return [(0, img)]
    step, ov = W // n, 60
    return [(max(0, i * step - ov),
             img.crop((max(0, i * step - ov), 0, min(W, (i + 1) * step + ov), H)))
            for i in range(n)]


def _read_one(job) -> WindowText:
    win, img, covered = job
    t0 = time.perf_counter()
    if covered:
        from PIL import ImageDraw
        img = img.copy()
        d = ImageDraw.Draw(img)
        for r in covered:
            d.rectangle(r, fill=(255, 255, 255))     # blank what is not visible

    strips = _strips(img)
    if len(strips) == 1:
        raw_parts = [(0, _tesseract_tsv(strips[0][1]))]
    else:
        with ThreadPoolExecutor(max_workers=len(strips)) as pool:
            raw_parts = list(pool.map(lambda s: (s[0], _tesseract_tsv(s[1])), strips))

    # merge TSVs: shift each strip's `left` by its offset so ordering holds
    merged, header_done = [], False
    for off, raw in raw_parts:
        rows = raw.splitlines()
        if not rows:
            continue
        if not header_done:
            merged.append(rows[0]); header_done = True
        for r in rows[1:]:
            f = r.split("\t")
            if len(f) >= 12:
                try:
                    f[6] = str(int(f[6]) + off)
                except ValueError:
                    pass
                merged.append("\t".join(f))
    text, blocks = parse_tsv("\n".join(merged))
    return WindowText(win=win, text=text, blocks=blocks,
                      seconds=time.perf_counter() - t0)


def excluded(win: Win, patterns: list[str]) -> bool:
    t = win.title.lower()
    return any(p in t for p in patterns)


def read_all(screenshot, wins: list[Win], workers: int = 6,
             exclude: list[str] | None = None) -> list[WindowText]:
    """OCR every visible window in parallel. Excluded windows return a stub
    with excluded=True and no text - the caller can say 'there is a window I
    am not reading' without having read it."""
    exclude = EXCLUDE_DEFAULT if exclude is None else exclude
    jobs, results = [], []
    for i, w in enumerate(wins):                     # wins are back to front
        if excluded(w, exclude):
            results.append(WindowText(win=w, excluded=True))
            continue
        covered = occluders(w, wins[i + 1:])
        vis = visible_fraction(w, covered)
        if vis < MIN_VISIBLE:
            results.append(WindowText(win=w, hidden=True))
            continue
        x1, y1, x2, y2 = w.rect
        cx1, cy1 = max(0, x1), max(0, y1)
        cx2, cy2 = min(x2, screenshot.width), min(y2, screenshot.height)
        if cx2 - cx1 < 100 or cy2 - cy1 < 100:
            continue
        # covered rects are in window coords; shift if the crop was clamped
        dx, dy = cx1 - x1, cy1 - y1
        covered = [(a - dx, b - dy, c - dx, d - dy) for a, b, c, d in covered]
        jobs.append((w, screenshot.crop((cx1, cy1, cx2, cy2)), covered))
    if jobs:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results.extend(pool.map(_read_one, jobs))
    return sorted(results, key=lambda r: -r.win.area)


# ------------------------------------------------------------------ views
def survey(reads: list[WindowText], first_chars: int = 110) -> str:
    """One line per window from titles and first content line. No model."""
    out = []
    for r in reads:
        mark = " (focused)" if r.win.active else ""
        if r.excluded:
            out.append(f"- {r.win.app}{mark}: [not read - excluded window]")
            continue
        if r.hidden:
            out.append(f"- {r.win.app}{mark}: {r.win.title[:70]} [mostly behind other windows]")
            continue
        first = next((l for l in r.text.splitlines() if len(l) > 12), "")
        out.append(f"- {r.win.app}{mark}: {r.win.title[:70]}"
                   + (f" | {first[:first_chars]}" if first else ""))
    return "\n".join(out)


def read_screen() -> tuple[list[WindowText], str]:
    img = grab()
    wins = list_windows(img.width, img.height)
    reads = read_all(img, wins)
    return reads, survey(reads)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", action="store_true", help="label/value pairs only")
    a = ap.parse_args()
    t0 = time.perf_counter()
    reads, s = read_screen()
    if not reads:
        raise SystemExit("no windows read - check: python3 windows.py")
    print(s + "\n")
    for r in reads:
        if r.excluded or r.hidden:
            continue
        print(f"=== {r.win.label()}  ({len(r.text)} chars, {len(r.blocks)} "
              f"blocks, {r.seconds:.1f}s)")
        if a.spec:
            for lab, val in r.spec_pairs()[:20]:
                print(f"    {lab:<20} {val[:80]}")
        else:
            for line in r.text.splitlines()[:12]:
                print(f"    {line[:100]}")
        print()
    print(f"total {time.perf_counter() - t0:.1f}s")