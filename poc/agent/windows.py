#!/usr/bin/env python3
"""
windows.py - what is on the screen, according to the window manager.

    python3 windows.py

Regions are windows, not thirds of the screen. X11 knows every window's
class, title, position and size; asking it is exact and instant, and it does
not break when a window moves.

Requires: wmctrl, xprop, xwininfo, xdotool
    sudo apt install wmctrl x11-utils xdotool

WHAT IS FILTERED OUT, AND WHY
  - other virtual desktops       not on screen
  - sticky/dock windows (-1)     panels, not content
  - minimised (_NET_WM_STATE_HIDDEN)   has geometry, is not visible
  - tiny windows                 tooltips, popups
  - wholly covered by a window in front   would OCR the front window twice

GEOMETRY comes from xwininfo, not wmctrl. wmctrl -lG reports client
coordinates that on GNOME are offset by the frame; xwininfo's absolute
upper-left is what matches the screenshot.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

ROLES = {
    "browser": ["firefox", "chromium", "chrome", "brave", "vivaldi", "epiphany"],
    "terminal": ["gnome-terminal", "konsole", "alacritty", "kitty", "xterm",
                 "terminator", "tilix", "wezterm"],
    "editor": ["code", "vscodium", "jetbrains", "sublime", "gedit", "kate",
               "pycharm", "intellij"],
    "files": ["nautilus", "dolphin", "thunar", "nemo"],
    "chat": ["slack", "discord", "signal", "telegram", "element"],
    "media": ["vlc", "mpv", "spotify", "rhythmbox"],
    "document": ["evince", "okular", "libreoffice", "soffice", "atril"],
}
SKIP_CLASSES = {"gnome-shell", "plasmashell", "xfdesktop", "desktop_window",
                "conky", "polybar", "waybar"}
MIN_W, MIN_H = 240, 180


@dataclass
class Win:
    wid: str
    x: int
    y: int
    w: int
    h: int
    wm_class: str
    title: str
    stack: int = 0
    active: bool = False

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.x + self.w, self.y + self.h)

    @property
    def area(self) -> int:
        return self.w * self.h

    @property
    def app(self) -> str:
        """wmctrl gives 'instance.Class'. The class is the second part:
        'Navigator.firefox' -> firefox. Reverse-DNS classes like
        'org.gnome.Nautilus.Org.gnome.Nautilus' resolve to the last segment."""
        parts = [p for p in self.wm_class.split(".") if p]
        if not parts:
            return "unknown"
        cls = parts[-1] if len(parts) > 2 else parts[-1]
        return cls.lower()

    @property
    def role(self) -> str:
        c = self.wm_class.lower()
        for role, keys in ROLES.items():
            if any(k in c for k in keys):
                return role
        return "other"

    def covers(self, other: "Win") -> bool:
        ax, ay, ax2, ay2 = self.rect
        bx, by, bx2, by2 = other.rect
        return ax <= bx and ay <= by and ax2 >= bx2 and ay2 >= by2

    def label(self) -> str:
        t = re.sub(r"\s+", " ", self.title).strip()
        return f"{self.app} - {t[:70]}" if t else self.app


# ------------------------------------------------------------------ shell
def _run(cmd: list[str]) -> str:
    if not shutil.which(cmd[0]):
        return ""
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=5).stdout
    except Exception:
        return ""


def _norm_id(wid: str) -> str:
    try:
        return hex(int(wid, 16)).lower()
    except ValueError:
        return wid.lower()


def _current_desktop() -> str:
    for line in _run(["wmctrl", "-d"]).splitlines():
        parts = line.split()
        if len(parts) > 1 and parts[1] == "*":
            return parts[0]
    return ""


def _stacking() -> list[str]:
    out = _run(["xprop", "-root", "_NET_CLIENT_LIST_STACKING"])
    return [_norm_id(i) for i in re.findall(r"0x[0-9a-fA-F]+", out)]


def _active() -> str:
    out = _run(["xdotool", "getactivewindow"]).strip()
    return hex(int(out)).lower() if out.isdigit() else ""


def _hidden(wid: str) -> bool:
    return "_NET_WM_STATE_HIDDEN" in _run(["xprop", "-id", wid, "_NET_WM_STATE"])


def _frame_extents(wid: str) -> tuple[int, int, int, int]:
    """GNOME client-side decorations carry invisible shadow borders that
    xwininfo counts as part of the window. _GTK_FRAME_EXTENTS = left, right,
    top, bottom to subtract. Zero when absent."""
    out = _run(["xprop", "-id", wid, "_GTK_FRAME_EXTENTS"])
    m = re.search(r"=\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)", out)
    return tuple(int(v) for v in m.groups()) if m else (0, 0, 0, 0)


def _geometry(wid: str) -> tuple[int, int, int, int] | None:
    """Absolute VISIBLE rect: xwininfo minus the CSD shadow."""
    out = _run(["xwininfo", "-id", wid])
    vals = {}
    for key, pat in (("x", r"Absolute upper-left X:\s+(-?\d+)"),
                     ("y", r"Absolute upper-left Y:\s+(-?\d+)"),
                     ("w", r"Width:\s+(\d+)"), ("h", r"Height:\s+(\d+)")):
        m = re.search(pat, out)
        if not m:
            return None
        vals[key] = int(m.group(1))
    l, r, t, b = _frame_extents(wid)
    return (vals["x"] + l, vals["y"] + t,
            max(1, vals["w"] - l - r), max(1, vals["h"] - t - b))


# ------------------------------------------------------------------ parse
def parse_wmctrl(text: str, desktop: str = "") -> list[dict]:
    """Pure function over `wmctrl -lGx` output, so it can be tested without X."""
    rows = []
    for line in text.splitlines():
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        wid, desk, x, y, w, h, cls, _host, title = parts
        try:
            x, y, w, h = int(x), int(y), int(w), int(h)
        except ValueError:
            continue
        if desk == "-1":
            continue
        if desktop and desk != desktop:
            continue
        if any(s in cls.lower() for s in SKIP_CLASSES):
            continue
        rows.append({"wid": _norm_id(wid), "x": x, "y": y, "w": w, "h": h,
                     "cls": cls, "title": title})
    return rows


def resolve(rows: list[dict], stack: list[str], active: str,
            screen_w: int = 0, screen_h: int = 0) -> list[Win]:
    """Pure: apply size, on-screen and occlusion rules. Testable."""
    wins = []
    for r in rows:
        if r["w"] < MIN_W or r["h"] < MIN_H:
            continue
        if screen_w and (r["x"] >= screen_w or r["y"] >= screen_h
                         or r["x"] + r["w"] <= 0 or r["y"] + r["h"] <= 0):
            continue
        wins.append(Win(wid=r["wid"], x=r["x"], y=r["y"], w=r["w"], h=r["h"],
                        wm_class=r["cls"], title=r["title"],
                        stack=stack.index(r["wid"]) if r["wid"] in stack else 0,
                        active=(r["wid"] == active)))
    wins.sort(key=lambda v: v.stack)                 # back to front
    visible = [v for i, v in enumerate(wins)
               if not any(o.covers(v) for o in wins[i + 1:])]
    return visible


def list_windows(screen_w: int = 0, screen_h: int = 0) -> list[Win]:
    if not shutil.which("wmctrl"):
        return []
    rows = parse_wmctrl(_run(["wmctrl", "-lGx"]), _current_desktop())
    for r in rows:
        g = _geometry(r["wid"])
        if g:
            r["x"], r["y"], r["w"], r["h"] = g
    rows = [r for r in rows if not _hidden(r["wid"])]
    return resolve(rows, _stacking(), _active(), screen_w, screen_h)


def pick(wins: list[Win], phrase: str) -> Win | None:
    """Resolve a reference like 'the browser' or 'firefox' to one window.
    Deterministic, strongest evidence first."""
    p = phrase.lower().strip()
    if not wins:
        return None
    for v in wins:                                   # exact app name
        if v.app and v.app in p:
            return v
    role_words = {
        "browser": ["browser", "web", "page", "tab", "site", "listing", "shop"],
        "terminal": ["terminal", "console", "shell", "bash", "command"],
        "editor": ["editor", "code", "script", "ide"],
        "files": ["file manager", "files", "folder"],
        "document": ["pdf", "document"],
        "chat": ["chat", "messages"],
        "media": ["video", "music", "player"],
    }
    for role, words in role_words.items():
        if role in p or any(re.search(r"\b" + re.escape(w) + r"\b", p) for w in words):
            cands = [v for v in wins if v.role == role]
            if cands:
                return max(cands, key=lambda v: (v.active, v.area))
    pw = set(re.findall(r"[a-z]{4,}", p))
    best, score = None, 0
    for v in wins:                                   # words from the title
        hit = len(set(re.findall(r"[a-z]{4,}", v.title.lower())) & pw)
        if hit > score:
            best, score = v, hit
    if best:
        return best
    if re.search(r"\b(this|here|current|focused|active)\b", p):
        return next((v for v in wins if v.active), None)
    return None


if __name__ == "__main__":
    missing = [t for t in ("wmctrl", "xprop", "xwininfo", "xdotool")
               if not shutil.which(t)]
    if missing:
        raise SystemExit(f"missing: {' '.join(missing)}  "
                         f"->  sudo apt install wmctrl x11-utils xdotool")
    ws = list_windows()
    if not ws:
        print("no visible windows found")
    for v in ws:
        print(f"  {'*' if v.active else ' '} {v.app:<15} {v.role:<9} "
              f"{v.w:>5}x{v.h:<5} at {v.x:>5},{v.y:<5}  {v.title[:55]}")