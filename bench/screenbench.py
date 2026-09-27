#!/usr/bin/env python3
"""
screenbench.py - a repeatable benchmark for reading text off a screen with a
local VLM.

Four phases, deliberately separate processes:

    capture   record frames while you browse. Nothing else runs.
    build     offline: OCR, ground truth, frozen question set.
    eval      run one configuration against that frozen set.
    report    compare configurations on identical questions.

WHY FOUR PHASES
---------------
Earlier versions captured, asked and scored in one loop, with the harness's own
output on screen. The model kept correctly reading the test's own parameters
("width" -> 99999) and being marked wrong. Every result was contaminated and
none was reproducible.

Freezing the question set fixes three things at once:
  * the terminal is only on screen during capture, and build rejects any frame
    that contains this harness's output anyway;
  * every configuration answers IDENTICAL questions on IDENTICAL frames, so
    whole-vs-tiled is a paired comparison rather than two separate samples;
  * a disputed verdict can be re-checked later against the saved frame.

SCORING - two metrics, on purpose
---------------------------------
EXACT     character-for-character, symbols and separators included. "$7,499"
          must come back as "$7,499". This is the bar that matters for a price.

ANLS      Average Normalized Levenshtein Similarity with threshold 0.5, the
          standard metric for ST-VQA / DocVQA / InfographicVQA. Below the
          threshold the score is zeroed, on the reasoning that an edit distance
          that large is unlikely to be an OCR artefact.
              s = 1 - NL   if NL < 0.5   else   0

          The gap between EXACT and ANLS is the diagnosis. High ANLS with low
          EXACT means it is reading correctly and rendering badly. Low both
          means it is inventing.

QUESTION TYPES
--------------
  adjacent   value immediately right of a UNIQUE high-confidence anchor word.
             One correct answer by construction.
  absent     anchor word that is not on the frame at all. Correct answer NONE.
  novalue    anchor word that IS present but has nothing to its right. Correct
             answer NONE. Harder than 'absent' - the word is really there, so
             only the value is missing.

GROUND TRUTH
------------
Tesseract TSV, gated at --min-conf (default 85). If OCR is not confident, no
question is generated. Ground truth is never a guess, and every question keeps
the confidences so you can audit it.

BARS - set before running:
    exact on adjacent      >= 90%
    hallucination on absent+novalue == 0%     (the disqualifying one)
    ANLS on adjacent       >= 0.95

USAGE - read this
-----------------
1.  python3 screenbench.py capture --frames 40 --delay 10 --interval 3
    Press enter, then IMMEDIATELY alt-tab to a maximised browser and browse
    normally for two minutes: PLE listings, JB product pages, a cart, a spec
    table. Scroll freely. Do not return to the terminal until it finishes.

2.  python3 screenbench.py build --min-conf 85
    Offline. Safe to run with the terminal visible - the frames are frozen.
    Reports how many questions it could construct and rejects contaminated
    frames.

3.  python3 screenbench.py eval --tag whole  --mode whole --width 1280
    python3 screenbench.py eval --tag tiled  --mode tiled --width 1280
    python3 screenbench.py eval --tag native --mode tiled --width 2048
    Each runs the same questions. Terminal visibility is irrelevant now.

4.  python3 screenbench.py report
    Paired comparison of every tag, plus the failure list with frame paths.
"""

from __future__ import annotations

import argparse
import base64
import collections
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import requests

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
RUN = os.environ.get("SCREENBENCH_DIR", "screenbench")
FRAMES = f"{RUN}/frames"
QFILE = f"{RUN}/questions.json"
MAX_PAYLOAD = 3_500_000          # ollama rejects very large image payloads

# Words that belong to this harness or the shell. Never anchor on them - that
# is how the earlier runs ended up reading their own parameters.
BLOCKLIST = {
    "width", "conf", "mode", "exact", "format", "wrong", "abstain", "frames",
    "model", "latency", "median", "worst", "positives", "negatives", "tiled",
    "whole", "native", "fabricated", "evidence", "screenbench", "ollama",
    "qwen", "python", "venv", "anchor", "expected", "verdict", "truth",
    "said", "probe", "tesseract", "vlm", "ocr", "anls",
}

# If a frame's text contains several of these, the harness was on screen.
CONTAMINATION = ["min OCR conf", "OCR conf", "screenbench", "adjacent",
                 "FABRICATED", "ANLS", "-> PASS", "-> FAIL"]

ABSENT_WORDS = ["Walrus", "Trombone", "Casserole", "Marzipan", "Harpoon",
                "Tapioca", "Bellhop", "Quarry", "Cobbler", "Meadow",
                "Zeppelin", "Custard", "Piccolo", "Lagoon", "Thimble"]

Word = collections.namedtuple("Word", "text conf left top width height line")
VALUE_RE = re.compile(r"^[\$€£]?\d[\d,.:/\-]*%?$")
ANCHOR_RE = re.compile(r"^[A-Za-z][A-Za-z\-']{3,}$")


# ------------------------------------------------------------------ helpers
def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def anls(truth: str, pred: str, tau: float = 0.5) -> float:
    """ST-VQA / DocVQA metric. Lower-cased, thresholded at tau."""
    t, p = truth.lower().strip(), pred.lower().strip()
    if not t and not p:
        return 1.0
    nl = levenshtein(t, p) / max(len(t), len(p), 1)
    return 1.0 - nl if nl < tau else 0.0


def digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def clean(s: str) -> str:
    s = s.strip().strip('"\'`').rstrip(".")
    s = re.sub(r"^(the value is|it is|value:|answer:)\s*", "", s, flags=re.I)
    return s.strip()


def tsv_words(path: str) -> list[Word]:
    out = subprocess.run(["tesseract", path, "stdout", "tsv"],
                         capture_output=True, text=True, timeout=180).stdout
    words = []
    for row in out.splitlines()[1:]:
        f = row.split("\t")
        if len(f) < 12 or not f[11].strip():
            continue
        try:
            conf = float(f[10])
        except ValueError:
            continue
        words.append(Word(f[11].strip(), conf, int(f[6]), int(f[7]),
                          int(f[8]), int(f[9]), (f[2], f[3], f[4])))
    return words


# ------------------------------------------------------------------ capture
def cmd_capture(args):
    import mss
    import mss.tools
    os.makedirs(FRAMES, exist_ok=True)
    for old in os.listdir(FRAMES):
        os.unlink(os.path.join(FRAMES, old))

    print(f"\nCapturing {args.frames} frames, one every {args.interval}s "
          f"(~{args.frames * args.interval}s total).")
    print(f"\n  >>> ALT-TAB TO YOUR BROWSER NOW. You have {args.delay} seconds. <<<")
    print("  >>> Browse normally. Do NOT return to this terminal. <<<\n")
    for s in range(args.delay, 0, -1):
        print(f"    {s}...", end="\r", flush=True)
        time.sleep(1)

    for i in range(args.frames):
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            mss.tools.to_png(shot.rgb, shot.size,
                             output=f"{FRAMES}/{i:03d}.png")
        time.sleep(args.interval)

    print(f"\ncaptured {args.frames} frames -> {FRAMES}/")
    print("next:  python3 screenbench.py build")


# ------------------------------------------------------------------ build
def cmd_build(args):
    if not shutil.which("tesseract"):
        sys.exit("tesseract required")
    paths = sorted(f"{FRAMES}/{p}" for p in os.listdir(FRAMES)
                   if p.endswith(".png"))
    if not paths:
        sys.exit("no frames - run capture first")

    questions, contaminated, barren = [], 0, 0
    for path in paths:
        words = tsv_words(path)
        text = " ".join(w.text for w in words)

        if sum(1 for m in CONTAMINATION if m in text) >= 2:
            contaminated += 1
            continue

        lower = text.lower()
        freq = collections.Counter(re.findall(r"[a-z][a-z\-']{3,}", lower))
        by_line = collections.defaultdict(list)
        for w in words:
            by_line[w.line].append(w)

        made = 0
        for line, ws in by_line.items():
            ws = sorted(ws, key=lambda w: w.left)
            for idx, w in enumerate(ws):
                if made >= args.per_frame:
                    break
                if w.conf < args.min_conf or not ANCHOR_RE.match(w.text):
                    continue
                key = w.text.lower()
                if key in BLOCKLIST or freq[key] != 1:
                    continue

                nxt = ws[idx + 1] if idx + 1 < len(ws) else None
                gap_ok = nxt and (nxt.left - (w.left + w.width)) < w.height * 3

                if nxt and gap_ok and nxt.conf >= args.min_conf \
                        and VALUE_RE.match(nxt.text):
                    questions.append({
                        "frame": path, "type": "adjacent", "anchor": w.text,
                        "truth": nxt.text,
                        "conf": [w.conf, nxt.conf],
                        "value_occurrences": text.count(nxt.text),
                        "box": [max(0, w.left - 30), max(0, w.top - 30),
                                nxt.left + nxt.width + 30,
                                w.top + max(w.height, nxt.height) + 30]})
                    made += 1
                elif nxt is None:
                    # word ends the line: nothing to its right at all
                    questions.append({
                        "frame": path, "type": "novalue", "anchor": w.text,
                        "truth": "NONE", "conf": [w.conf, 0],
                        "value_occurrences": 0,
                        "box": [max(0, w.left - 30), max(0, w.top - 30),
                                w.left + w.width + 30, w.top + w.height + 30]})
                    made += 1
        if made == 0:
            barren += 1

        # one absent-word control per frame
        miss = [a for a in ABSENT_WORDS if a.lower() not in lower]
        if miss:
            questions.append({"frame": path, "type": "absent",
                              "anchor": miss[hash(path) % len(miss)],
                              "truth": "NONE", "conf": [0, 0],
                              "value_occurrences": 0, "box": None})

    counts = collections.Counter(q["type"] for q in questions)
    with open(QFILE, "w") as f:
        json.dump({"built": time.strftime("%Y-%m-%d %H:%M"),
                   "min_conf": args.min_conf, "questions": questions}, f, indent=2)

    print(f"frames            : {len(paths)}")
    print(f"  contaminated    : {contaminated}  (harness output visible - dropped)")
    print(f"  no usable anchor: {barren}")
    print(f"questions         : {len(questions)}")
    for k in ("adjacent", "absent", "novalue"):
        print(f"  {k:<15} : {counts[k]}")
    if counts["adjacent"] < 15:
        print("\n  Thin on 'adjacent'. Re-capture on pages with labelled values")
        print("  (spec tables, carts, invoices) for a result worth trusting.")
    print(f"\nwritten -> {QFILE}\nnext: python3 screenbench.py eval --tag whole")


# ------------------------------------------------------------------ eval
def encode(img, width: int) -> str:
    im = img if img.width <= width else \
        img.resize((width, int(img.height * width / img.width)))
    for q in (None, 90, 70):
        buf = io.BytesIO()
        if q is None:
            im.save(buf, format="PNG")
        else:
            im.save(buf, format="JPEG", quality=q)
        if buf.tell() <= MAX_PAYLOAD:
            return base64.b64encode(buf.getvalue()).decode()
    return base64.b64encode(buf.getvalue()).decode()


def images_for(img, mode: str, width: int) -> list[str]:
    if mode == "whole":
        return [encode(img, width)]
    W, H = img.size
    ov = int(W * 0.08)
    return [encode(img.crop((0, 0, W // 2 + ov, H)), width),
            encode(img.crop((W // 2 - ov, 0, W, H)), width)]


def cmd_eval(args):
    from PIL import Image
    spec = json.load(open(QFILE))
    qs = spec["questions"]
    print(f"{args.tag}: {len(qs)} questions | {args.model} | "
          f"{args.mode} | width {args.width}\n")

    results = []
    for n, q in enumerate(qs, 1):
        img = Image.open(q["frame"]).convert("RGB")
        prompt = (f'Find the word "{q["anchor"]}" in this image. Output the '
                  f'value immediately to its right, copied exactly as shown '
                  f'including any currency symbol, comma, decimal point or '
                  f'colon. Output only that value. If the word is not present, '
                  f'or has no value to its right, output exactly: NONE')
        t0 = time.perf_counter()
        try:
            r = requests.post(f"{OLLAMA}/api/generate",
                              json={"model": args.model, "prompt": prompt,
                                    "images": images_for(img, args.mode, args.width),
                                    "stream": False, "keep_alive": "30m",
                                    "options": {"temperature": 0, "num_predict": 30}},
                              timeout=300)
            r.raise_for_status()
            ans = clean(r.json().get("response", ""))
        except Exception as e:
            ans = f"__ERROR__ {e}"
        dt = time.perf_counter() - t0

        truth = q["truth"]
        said_none = ans.upper() == "NONE"
        if q["type"] == "adjacent":
            if said_none:
                verdict = "ABSTAIN"
            elif ans == truth:
                verdict = "EXACT"
            elif digits(ans) and digits(ans) == digits(truth):
                verdict = "FORMAT"
            else:
                verdict = "WRONG"
            score = anls(truth, ans) if not said_none else 0.0
        else:
            verdict = "CORRECT" if said_none else "HALLUCINATED"
            score = 1.0 if said_none else 0.0

        results.append({**q, "answer": ans, "verdict": verdict,
                        "anls": round(score, 3), "seconds": round(dt, 2)})
        print(f"  [{n:>3}/{len(qs)}] {q['type']:<8} \"{q['anchor']}\" "
              f"truth={truth!r} got={ans[:24]!r} {verdict} [{dt:.2f}s]")

    path = f"{RUN}/eval_{args.tag}.json"
    json.dump({"tag": args.tag, "model": args.model, "mode": args.mode,
               "width": args.width, "results": results}, open(path, "w"), indent=2)
    print(f"\n-> {path}\nnext: python3 screenbench.py report")


# ------------------------------------------------------------------ report
def summarise(ev: dict) -> dict:
    rs = ev["results"]
    adj = [r for r in rs if r["type"] == "adjacent"]
    neg = [r for r in rs if r["type"] in ("absent", "novalue")]
    n_adj, n_neg = len(adj) or 1, len(neg) or 1
    ex = sum(r["verdict"] == "EXACT" for r in adj)
    fm = sum(r["verdict"] == "FORMAT" for r in adj)
    wr = sum(r["verdict"] == "WRONG" for r in adj)
    ab = sum(r["verdict"] == "ABSTAIN" for r in adj)
    hal = sum(r["verdict"] == "HALLUCINATED" for r in neg)
    secs = sorted(r["seconds"] for r in rs)
    return {"tag": ev["tag"], "mode": ev["mode"], "width": ev["width"],
            "n_adj": len(adj), "n_neg": len(neg),
            "exact": 100 * ex / n_adj, "format": 100 * fm / n_adj,
            "wrong": 100 * wr / n_adj, "abstain": 100 * ab / n_adj,
            "anls": sum(r["anls"] for r in adj) / n_adj,
            "halluc": 100 * hal / n_neg,
            "median_s": secs[len(secs) // 2] if secs else 0,
            "pass": (100 * ex / n_adj) >= 90 and hal == 0
                    and (sum(r["anls"] for r in adj) / n_adj) >= 0.95}


def cmd_report(args):
    evs = [json.load(open(f"{RUN}/{p}")) for p in sorted(os.listdir(RUN))
           if p.startswith("eval_") and p.endswith(".json")]
    if not evs:
        sys.exit("no eval files - run eval first")
    rows = [summarise(e) for e in evs]

    print(f"\n{'tag':<10}{'mode':<8}{'px':>6}{'exact':>8}{'ANLS':>7}"
          f"{'fmt':>6}{'wrong':>7}{'absta':>7}{'halluc':>8}{'med s':>7}  bars")
    print("-" * 88)
    for r in rows:
        print(f"{r['tag']:<10}{r['mode']:<8}{r['width']:>6}"
              f"{r['exact']:>7.0f}%{r['anls']:>7.2f}{r['format']:>5.0f}%"
              f"{r['wrong']:>6.0f}%{r['abstain']:>6.0f}%{r['halluc']:>7.0f}%"
              f"{r['median_s']:>7.2f}  {'PASS' if r['pass'] else 'FAIL'}")
    print("-" * 88)
    print(f"n = {rows[0]['n_adj']} adjacent, {rows[0]['n_neg']} negative "
          f"- identical questions across every row")
    print("\nbars: exact >=90%, ANLS >=0.95, hallucination ==0%")

    print("\nreading it:")
    print("  high ANLS, low exact  -> reading right, rendering wrong. Normalise.")
    print("  low both              -> inventing. No model size fixes this.")
    print("  hallucination > 0     -> disqualifying, whatever else passes.")

    for e in evs:
        bad = [r for r in e["results"]
               if r["verdict"] in ("WRONG", "HALLUCINATED")]
        if bad:
            print(f"\n{e['tag']} failures - open the frame and judge yourself:")
            for r in bad[:12]:
                print(f"  {r['frame']}  \"{r['anchor']}\"  "
                      f"truth={r['truth']!r} got={r['answer'][:28]!r}")


# ------------------------------------------------------------------ cli
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("capture"); c.set_defaults(fn=cmd_capture)
    c.add_argument("--frames", type=int, default=40)
    c.add_argument("--interval", type=float, default=3.0)
    c.add_argument("--delay", type=int, default=10)

    b = sub.add_parser("build"); b.set_defaults(fn=cmd_build)
    b.add_argument("--min-conf", type=float, default=85.0)
    b.add_argument("--per-frame", type=int, default=2)

    e = sub.add_parser("eval"); e.set_defaults(fn=cmd_eval)
    e.add_argument("--tag", required=True)
    e.add_argument("--mode", choices=["whole", "tiled"], default="whole")
    e.add_argument("--width", type=int, default=1280)
    e.add_argument("--model", default=os.environ.get("PROBE_VLM", "qwen2.5vl:7b"))

    r = sub.add_parser("report"); r.set_defaults(fn=cmd_report)

    os.makedirs(RUN, exist_ok=True)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nstopped")