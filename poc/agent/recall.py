#!/usr/bin/env python3
"""
recall.py - what she saw, as data.

    python3 recall.py search "pink graphics card"
    python3 recall.py timeline
    python3 recall.py interests

Two stores, both plain JSONL/JSON under memory/screen/:

  EPISODES   one per stretch of looking at roughly the same thing. Consecutive
             similar screens merge, so scrolling a page for two minutes is ONE
             memory with a duration, not forty. Each carries a timestamp,
             screen count, generic salient entities, and the OCR text.

  INTERESTS  standing wants, filed by the `remember` tool when the user says
             they are looking out for something. Plain phrases. Checked
             deterministically against every new episode by word-boundary
             match - substring matching made 'car' fire on 'Cart'.

Her prose is never stored here and never comes back as evidence (ADR-0002).
Recall returns confidence and age so a weak match can be reported as one.

This module has no OCR and no model calls. Feed it text; ask it questions.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, asdict, field

BASE = os.environ.get("OBS_DIR", "memory/screen")

STOP = set("""the and for with from this that your you are was were will has have
had not but all can any out how why when what who which there their they them
been more most some such only other into over than then also our its his her
new use used using get got page home menu search click here view show more
about after before again""".split())

SALIENT = [
    re.compile(r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){0,3})\b"),       # Names
    re.compile(r"\b([A-Z]{2,}[\w-]*\s?\d{2,}[\w-]*)\b"),                 # RTX 5080
    re.compile(r"([\$£€]\s?\d[\d,]*(?:\.\d{2})?)"),                      # money
    re.compile(r"\b(\d[\d,.]*\s?(?:GB|TB|MHz|GHz|Hz|W|°C|km|kg|mm|ms|%|MiB))\b", re.I),
    re.compile(r"\b([a-z0-9-]+\.(?:com|com\.au|org|net|io|dev))\b", re.I),  # sites
]


# ------------------------------------------------------------------ helpers
def tokens_of(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9.]{2,}", text.lower())
            if w not in STOP}


def terms_of(phrase: str) -> list[str]:
    ts = [t for t in re.findall(r"[a-z0-9.]{3,}", phrase.lower()) if t not in STOP]
    return ts if any(len(t) >= 4 for t in ts) else []


def has_terms(blob: str, terms: list[str]) -> list[str]:
    """Word-boundary match only."""
    return [t for t in terms if re.search(r"\b" + re.escape(t) + r"\b", blob)]


def salient(text: str, cap: int = 40) -> list[str]:
    found, seen = [], set()
    for rx in SALIENT:
        for m in rx.findall(text):
            s = re.sub(r"\s+", " ", m).strip()
            k = s.lower()
            if len(s) < 3 or k in seen or k in STOP:
                continue
            seen.add(k)
            found.append(s)
            if len(found) >= cap:
                return found
    return found


def ago(ts: float, now: float | None = None) -> str:
    m = ((now or time.time()) - ts) / 60
    if m < 1:
        return "just now"
    if m < 60:
        return f"about {m:.0f} minutes ago"
    if m < 24 * 60:
        return f"about {m/60:.0f} hours ago"
    return dt.datetime.fromtimestamp(ts).strftime("on %a %d %b")


# ------------------------------------------------------------------ episodes
@dataclass
class Episode:
    id: str
    started: float
    ended: float
    screens: int = 1
    entities: list = field(default_factory=list)
    text: str = ""
    tokens: list = field(default_factory=list)


class Memory:
    MERGE_SIMILARITY = 0.55        # containment of the smaller token set
    MERGE_GAP_S = 180
    KEEP = 500

    def __init__(self, base: str = BASE):
        os.makedirs(base, exist_ok=True)
        self.path = os.path.join(base, "episodes.jsonl")
        self.episodes: list[dict] = []
        if os.path.exists(self.path):
            for line in open(self.path, encoding="utf-8"):
                try:
                    self.episodes.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    def _flush(self):
        with open(self.path, "w", encoding="utf-8") as f:
            for e in self.episodes:
                f.write(json.dumps(e) + "\n")

    def see(self, text: str, now: float | None = None) -> tuple[dict, bool]:
        """Record a screen. Returns (episode, is_new)."""
        now = now or time.time()
        toks = tokens_of(text)
        last = self.episodes[-1] if self.episodes else None

        if last and (now - last["ended"]) < self.MERGE_GAP_S and toks:
            prev = set(last["tokens"])
            if prev:
                overlap = len(prev & toks) / max(1, min(len(prev), len(toks)))
                if overlap >= self.MERGE_SIMILARITY:
                    last["ended"] = now
                    last["screens"] += 1
                    last["tokens"] = sorted(prev | toks)[:400]
                    for s in salient(text):
                        if s not in last["entities"] and len(last["entities"]) < 40:
                            last["entities"].append(s)
                    if len(text) > len(last["text"]):
                        last["text"] = text[:3000]
                    self._flush()
                    return last, False

        ep = Episode(id=hashlib.md5(f"{now}{text[:64]}".encode()).hexdigest()[:10],
                     started=now, ended=now, entities=salient(text),
                     text=text[:3000], tokens=sorted(toks)[:400])
        self.episodes.append(asdict(ep))
        del self.episodes[:-self.KEEP]
        self._flush()
        return self.episodes[-1], True

    def search(self, cue: str, n: int = 5, now: float | None = None) -> list[dict]:
        terms = terms_of(cue)
        if not terms:
            return []
        now = now or time.time()
        out = []
        for e in self.episodes:
            blob = (" ".join(e["entities"]) + " " + e["text"]).lower()
            hits = has_terms(blob, terms)
            if not hits:
                continue
            coverage = len(hits) / len(terms)
            age_h = (now - e["ended"]) / 3600
            if age_h > 48 and coverage < 0.75:
                continue                       # old memories need a specific cue
            out.append({**e, "coverage": round(coverage, 2),
                        "matched": hits,
                        "score": round(coverage / (1 + age_h * 0.3), 3)})
        out.sort(key=lambda d: d["score"], reverse=True)
        return out[:n]

    def phrase(self, cue: str, n: int = 3, now: float | None = None) -> str:
        """Recall as data for a prompt: when, how long, what, how sure."""
        hits = self.search(cue, n, now)
        if not hits:
            return ""
        lines = []
        for h in hits:
            mins = (h["ended"] - h["started"]) / 60
            dur = f", for about {mins:.0f} min" if h["screens"] > 2 and mins >= 1 else ""
            conf = ("clearly" if h["coverage"] >= 0.99 else
                    "fairly sure" if h["coverage"] >= 0.6 else "vaguely")
            what = ", ".join(h["entities"][:6]) or "something"
            lines.append(f"- {ago(h['ended'], now)}{dur}: {what} "
                         f"(matched {', '.join(h['matched'][:4])}; {conf})")
        return "\n".join(lines)

    def timeline(self, n: int = 15) -> list[dict]:
        return self.episodes[-n:][::-1]

    def forget_since(self, minutes: float) -> int:
        cut = time.time() - minutes * 60
        before = len(self.episodes)
        self.episodes = [e for e in self.episodes if e["ended"] < cut]
        self._flush()
        return before - len(self.episodes)

    def prune(self, days: int) -> int:
        cut = time.time() - days * 86400
        before = len(self.episodes)
        self.episodes = [e for e in self.episodes if e["ended"] >= cut]
        if len(self.episodes) != before:
            self._flush()
        return before - len(self.episodes)


# ------------------------------------------------------------------ interests
CEILING = re.compile(r"\b(?:under|below|less than|max|up to|cheaper than|no more than)"
                     r"\s*\$?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|grand)?\b", re.I)
MONEY = re.compile(r"[\$£€]\s?(\d[\d,]*(?:\.\d{2})?)")


def split_want(phrase: str) -> tuple[list[str], float | None]:
    """'rtx 5080 under 1500' -> (['rtx','5080'], 1500.0).
    A price ceiling is a constraint on the page's prices, not words to find on
    the page. Left in the phrase it could never match - no listing says
    'under 1500'."""
    ceiling = None
    m = CEILING.search(phrase)
    if m:
        ceiling = float(m.group(1).replace(",", ""))
        if m.group(2):
            ceiling *= 1000
        phrase = phrase[:m.start()] + phrase[m.end():]
    return terms_of(phrase), ceiling


def prices_per_match(text: str, term: str, radius: int = 200) -> list[float]:
    """For EACH occurrence of the term, the single nearest price within radius.
    Not one global nearest (a second occurrence would shadow the first), and
    not every price in a window (that reaches the next card on a dense grid)."""
    low = text.lower()
    prices = [(p.start(), p.end(), float(p.group(1).replace(",", "")))
              for p in MONEY.finditer(text)]
    out = []
    for m in re.finditer(r"\b" + re.escape(term.lower()) + r"\b", low):
        best, best_d = None, radius + 1
        for ps, pe, val in prices:
            d = min(abs(ps - m.end()), abs(m.start() - pe))
            if d < best_d:
                best, best_d = val, d
        if best is not None:
            out.append(best)
    return out


class Interests:
    def __init__(self, base: str = BASE):
        os.makedirs(base, exist_ok=True)
        self.path = os.path.join(base, "interests.json")

    def all(self) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        try:
            return json.load(open(self.path))
        except Exception:
            return []

    def _save(self, xs: list[dict]):
        json.dump(xs, open(self.path, "w"), indent=2)

    def add(self, phrase: str) -> dict | None:
        """Refuses a phrase too thin to match on. 'car' fired on every
        shopping page; 'rtx 5080 under 1500' is a want."""
        phrase = re.sub(r"\s+", " ", phrase).strip()
        terms, ceiling = split_want(phrase)
        if not terms or (len(terms) < 2 and ceiling is None):
            return None
        xs = self.all()
        key = hashlib.md5(phrase.lower().encode()).hexdigest()[:8]
        if any(x["id"] == key for x in xs):
            return None
        x = {"id": key, "phrase": phrase, "terms": terms, "ceiling": ceiling,
             "created": time.time(), "fired": []}
        xs.append(x)
        self._save(xs)
        return x

    def forget(self, phrase_or_id: str) -> bool:
        xs = self.all()
        k = phrase_or_id.lower()
        keep = [x for x in xs if x["id"] != k and k not in x["phrase"].lower()]
        if len(keep) == len(xs):
            return False
        self._save(keep)
        return True

    def check(self, episode: dict) -> list[str]:
        """Every interest against one new episode. Fires once per episode."""
        xs = self.all()
        if not xs:
            return []
        blob = (" ".join(episode["entities"]) + " " + episode["text"]).lower()
        msgs, changed = [], False
        for x in xs:
            terms = x.get("terms") or split_want(x["phrase"])[0]
            if not terms or len(has_terms(blob, terms)) < len(terms):
                continue
            ceiling = x.get("ceiling")
            if ceiling is not None:
                # all terms present near each other is what has_terms proved;
                # now the price must sit next to the LAST term (the model
                # number, usually), not anywhere on the page.
                if not any(p <= ceiling for p in prices_per_match(episode["text"], terms[-1])):
                    continue
            if episode["id"] in x["fired"]:
                continue
            x["fired"].append(episode["id"])
            changed = True
            ctx = ", ".join(episode["entities"][:6])
            msgs.append(f"'{x['phrase']}' matched on screen"
                        + (f": {ctx}" if ctx else ""))
        if changed:
            self._save(xs)
        return msgs


# ------------------------------------------------------------------ cli
def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search"); s.add_argument("cue")
    t = sub.add_parser("timeline"); t.add_argument("n", type=int, nargs="?", default=15)
    sub.add_parser("interests")
    f = sub.add_parser("forget"); f.add_argument("minutes", type=float)
    a = ap.parse_args()
    mem, ints = Memory(), Interests()

    if a.cmd == "search":
        print(mem.phrase(a.cue, 5) or "  no memory of that")
    elif a.cmd == "timeline":
        for e in mem.timeline(a.n):
            mins = (e["ended"] - e["started"]) / 60
            print(f"  {dt.datetime.fromtimestamp(e['started']):%H:%M}  "
                  f"{mins:>4.0f}m  {e['screens']:>3} screens  "
                  f"{', '.join(e['entities'][:6])[:70]}")
    elif a.cmd == "interests":
        xs = ints.all()
        print("  nothing being watched for" if not xs else "")
        for x in xs:
            print(f"  [{x['id']}] {x['phrase']}  (fired {len(x['fired'])}x)")
    elif a.cmd == "forget":
        print(f"  forgot {mem.forget_since(a.minutes)} episodes")


if __name__ == "__main__":
    main()
