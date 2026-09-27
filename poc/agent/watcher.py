#!/usr/bin/env python3
"""
watcher.py - always-on screen awareness. Step 4 of the build order.

    python3 watcher.py                 # run standalone, prints what it sees
    python3 watcher.py --pause
    python3 watcher.py --resume
    python3 watcher.py --status

CHEAP BY DESIGN
    every tick (1s)      64x32 greyscale diff of the screen       ~10 ms
    screen moving        wait; do not OCR mid-scroll
    settled (2 quiet ticks)   per-window OCR, CPU only            ~1-3 s
So scrolling for thirty seconds costs one OCR pass, and a static screen
costs none. Nothing here touches the GPU.

BOUNDARIES, all on by default
    EXCLUDE   per WINDOW, by title, from memory/screen/watch-exclude.txt -
              an excluded window is never OCR'd even if it is not focused
    REDACT    card numbers, keys, tokens, emails, password: lines replaced
              before storage
    RETAIN    episodes older than --retain-days deleted hourly
    PAUSE     touch memory/screen/PAUSED, or --pause; stops within a tick

Events are only two kinds and both are deterministic: a standing interest
matched, or (later) a tracked number crossed a threshold. Novelty alone is
never an event - "you opened a tab" is not worth saying.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import threading
import time

import numpy as np

from recall import Memory, Interests
from screenread import grab, read_all, EXCLUDE_DEFAULT
from windows import list_windows

BASE = os.environ.get("OBS_DIR", "memory/screen")
PAUSE_FILE = os.path.join(BASE, "PAUSED")
EXCLUDE_FILE = os.path.join(BASE, "watch-exclude.txt")

REDACTIONS = [
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[card]"),
    (re.compile(r"\b(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{12,}|"
                r"xox[baprs]-[A-Za-z0-9-]{10,})\b"), "[key]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[email]"),
    (re.compile(r"(?i)\b(password|passwd|secret|token|api[_ ]?key)\s*[:=]\s*\S+"),
     r"\1: [redacted]"),
    (re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"), "[blob]"),
]


def redact(text: str) -> str:
    for rx, rep in REDACTIONS:
        text = rx.sub(rep, text)
    return text


def load_exclusions() -> list[str]:
    os.makedirs(BASE, exist_ok=True)
    if not os.path.exists(EXCLUDE_FILE):
        with open(EXCLUDE_FILE, "w") as f:
            f.write("# one pattern per line; case-insensitive substring of the "
                    "window title\n" + "\n".join(EXCLUDE_DEFAULT) + "\n")
    out = []
    for line in open(EXCLUDE_FILE, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line.lower())
    return out


def thumb(img):
    return np.asarray(img.convert("L").resize((64, 32)), dtype=np.float32)


def changed(a, b, tol: float = 6.0) -> bool:
    return a is None or b is None or float(np.abs(a - b).mean()) > tol


class Watcher:
    def __init__(self, tick: float = 1.0, settle_ticks: int = 2,
                 retain_days: int = 7, on_event=None, verbose: bool = False):
        self.tick, self.settle_ticks = tick, settle_ticks
        self.retain_days, self.on_event, self.verbose = retain_days, on_event, verbose
        self.mem, self.ints = Memory(), Interests()
        self.exclusions = load_exclusions()
        self._stop = threading.Event()
        self.last_thumb, self.quiet, self.pending = None, 0, False
        self.stats = {"ticks": 0, "ocr": 0, "excluded": 0, "episodes": 0,
                      "events": 0, "started": time.time()}

    @staticmethod
    def paused() -> bool:
        return os.path.exists(PAUSE_FILE)

    @staticmethod
    def pause():
        os.makedirs(BASE, exist_ok=True)
        open(PAUSE_FILE, "w").write(str(time.time()))

    @staticmethod
    def resume():
        try:
            os.unlink(PAUSE_FILE)
        except OSError:
            pass

    def start(self):
        self.mem.prune(self.retain_days)
        threading.Thread(target=self._loop, daemon=True).start()
        return self

    def stop(self):
        self._stop.set()

    def _loop(self):
        last_prune = time.time()
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                if self.verbose:
                    print(f"  [watcher] {type(e).__name__}: {e}")
            if time.time() - last_prune > 3600:
                self.mem.prune(self.retain_days)
                last_prune = time.time()
            self._stop.wait(self.tick)

    def _tick(self):
        self.stats["ticks"] += 1
        if self.paused():
            return
        img = grab()
        th = thumb(img)
        if changed(self.last_thumb, th):
            self.last_thumb, self.quiet, self.pending = th, 0, True
            return
        self.quiet += 1
        if not self.pending or self.quiet < self.settle_ticks:
            return

        self.pending = False
        t0 = time.perf_counter()
        wins = list_windows(img.width, img.height)
        reads = read_all(img, wins, exclude=self.exclusions)
        self.stats["ocr"] += 1
        self.stats["excluded"] += sum(1 for r in reads if r.excluded)

        parts = [f"[{r.win.app}] {r.win.title}\n{r.text}"
                 for r in reads if not r.excluded and len(r.text) > 40]
        if not parts:
            return
        text = redact("\n\n".join(parts))
        ep, is_new = self.mem.see(text)
        if is_new:
            self.stats["episodes"] += 1
        events = self.ints.check(ep)
        if events:
            self.stats["events"] += len(events)
            if self.on_event:
                self.on_event(events)
        if self.verbose:
            tag = "NEW" if is_new else f"same({ep['screens']}x)"
            print(f"  [watch {dt.datetime.now():%H:%M:%S}] {tag:<10} "
                  f"{len(reads)} windows  {', '.join(ep['entities'][:4])[:60]}  "
                  f"[{time.perf_counter() - t0:.1f}s]")
            for e in events:
                print(f"  ** {e}")

    def summary(self) -> str:
        up = (time.time() - self.stats["started"]) / 60
        return (f"{up:.0f} min | {self.stats['ticks']} ticks | "
                f"{self.stats['ocr']} OCR | {self.stats['episodes']} episodes | "
                f"{self.stats['excluded']} excluded | {self.stats['events']} events"
                + ("  [PAUSED]" if self.paused() else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tick", type=float, default=1.0)
    ap.add_argument("--settle", type=int, default=2)
    ap.add_argument("--retain-days", type=int, default=7)
    ap.add_argument("--pause", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()

    if a.pause:
        Watcher.pause(); return print("paused")
    if a.resume:
        Watcher.resume(); return print("watching")
    if a.status:
        m = Memory()
        print(f"episodes {len(m.episodes)} | paused {Watcher.paused()} | "
              f"exclusions {len(load_exclusions())} in {EXCLUDE_FILE}")
        return

    w = Watcher(a.tick, a.settle, a.retain_days, verbose=True).start()
    print(f"watching. OCR only when the screen settles. exclusions: {EXCLUDE_FILE}\n")
    try:
        while True:
            time.sleep(30)
            print(f"  [watcher] {w.summary()}")
    except KeyboardInterrupt:
        w.stop()
        print(f"\n{w.summary()}")


if __name__ == "__main__":
    main()
