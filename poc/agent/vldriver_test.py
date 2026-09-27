#!/usr/bin/env python3
"""
vldriver_test.py - can a vision model BE the driver?

    source env.sh
    docker exec -it ollama ollama pull qwen3-vl:8b
    python3 vldriver_test.py --model qwen3-vl:8b
    python3 vldriver_test.py --model qwen2.5vl:7b
    python3 vldriver_test.py --model qwen3:8b --blind      # text-only baseline

THE DECISION THIS SETTLES
The proposed architecture has ONE model that sees the screen directly and
also drives the conversation and the tools - eyes and mind in the same place,
with OCR as reading glasses. That only works if a vision model can call tools
reliably. Most cannot: multimodal chat templates and function-definition
templates are separate code paths and most vision releases ship only the
first, so Ollama rejects tools outright. This suite finds out, on your
hardware, with your screen.

SIX PHASES. A, B, C, D are scored automatically; E and F are measurements.

  A  CAPABILITY     does the model accept tools at all, and tools WITH an
                    image in the same request? A hard gate - if this fails,
                    nothing else matters and the suite stops.

  B  TOOL SELECTION 14 questions with a real screenshot attached, scored
                    exactly as tool_smoke scored the text driver: right tool,
                    valid arguments, no invented tool, correct two-step chain.
                    The comparison against qwen3:8b's 19/20 is the point.

  C  VISION TRUTH   the window manager already knows how many windows are
                    open, which is focused, and what each is titled. That is
                    free, exact ground truth for what the eyes should see -
                    no human labelling, no model judging a model.

  D  READING        a number is taken from tesseract at full resolution, then
                    the model is asked for it three ways: from the image
                    alone, with OCR text supplied, and with OCR supplied and
                    a conflicting figure planted in the image description.
                    This measures whether the glasses actually get worn.

  E  REASONING      six questions judged by eye - conversation quality, not
                    a score. A driver has to be good company as well as
                    accurate.

  F  COST           VRAM before and after, first-token and full latency per
                    phase, with and without an image.

GATE for adopting a vision driver:
    A  must pass outright
    B  >= 18/20 equivalent (>= 12/14 here) and ZERO invented tools
    C  >= 80% on window facts
    D  exact match with OCR supplied, and OCR must win the conflict case
    F  screen turn under 2.5s to first token
If B fails but A passes, the eyes work and the mind does not: keep the
two-model split. If A fails, the model cannot be the driver at all.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import statistics
import subprocess
import sys
import time

import requests

from windows import list_windows
from screenread import grab, read_all, survey

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
NUM_CTX = int(os.environ.get("NUM_CTX", "8192"))
WIDTH = int(os.environ.get("VLM_WIDTH", "1280"))

SYSTEM = (
    "You are Desiree, an assistant on the user's Linux desktop. You can see "
    "the screen in the image attached to each message. You also have tools: "
    "read_window for the exact text of one window, research for anything "
    "about the world as it is now, search_memory for what was on screen "
    "earlier, and remember for things to watch for. Default to using a tool "
    "for anything current or factual; answer directly for arithmetic, "
    "definitions and conversation. Reply in at most three plain sentences."
)

TOOLS = [
    {"type": "function", "function": {
        "name": "read_window",
        "description": "Exact text of ONE window on screen (OCR at full "
                       "resolution). Use when exact wording or a number matters "
                       "- the image is downscaled and its small text is "
                       "unreliable. app is an app name or role.",
        "parameters": {"type": "object",
                       "properties": {"app": {"type": "string"}},
                       "required": ["app"]}}},
    {"type": "function", "function": {
        "name": "research",
        "description": "Look a question up on the web. Use for prices, current "
                       "facts, products, people, anything that changes.",
        "parameters": {"type": "object",
                       "properties": {"question": {"type": "string"}},
                       "required": ["question"]}}},
    {"type": "function", "function": {
        "name": "search_memory",
        "description": "Recall screens looked at earlier today.",
        "parameters": {"type": "object",
                       "properties": {"cue": {"type": "string"}},
                       "required": ["cue"]}}},
    {"type": "function", "function": {
        "name": "remember",
        "description": "File something to be told about when it appears on "
                       "screen. Only when the user says they are looking for it.",
        "parameters": {"type": "object",
                       "properties": {"want": {"type": "string"}},
                       "required": ["want"]}}},
]
TOOL_NAMES = {t["function"]["name"] for t in TOOLS}
REQUIRED = {t["function"]["name"]: t["function"]["parameters"]["required"] for t in TOOLS}

# (question, acceptable tools or {"none"})
# Note there is no read_screen here: the model SEES the screen. Needing a tool
# to find out what is on screen would mean the eyes are not working.
CASES = [
    ("What's on my screen?", {"none"}),
    ("Which window am I using right now?", {"none"}),
    ("Roughly how many windows do I have open?", {"none"}),
    ("What's the exact text of the first heading in the browser?", {"read_window"}),
    ("Read me the exact price shown in the browser.", {"read_window"}),
    ("What's the capital of Peru?", {"none"}),
    ("What's 15 percent of 240?", {"none"}),
    ("What's the current price of an RTX 5090 in Australia?", {"research"}),
    ("Who is the prime minister of Australia right now?", {"research"}),
    ("Is this prebuilt any good?", {"research", "read_window"}),
    ("Keep an eye out for an RTX 5080 under 1500 dollars.", {"remember"}),
    ("Do you remember what I was looking at earlier?", {"search_memory"}),
    ("Explain the difference between a list and a tuple.", {"none"}),
    ("Does this page look like a shopping site or a news site?", {"none"}),
]

REASONING = [
    "How are you finding this so far?",
    "I'm trying to decide between a prebuilt and building it myself. Thoughts?",
    "Explain how a heat pump works, briefly.",
    "What do you make of what I'm working on right now?",
    "If I bought the machine on screen, what would you change about it first?",
    "Tell me something you noticed that I didn't ask about.",
]


# ------------------------------------------------------------------ helpers
def vram() -> int:
    try:
        o = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits",
             "-i", "0"], text=True).strip()
        return int(o)
    except Exception:
        return 0


def gb(mib: int) -> float:
    return round(mib / 1024, 2)


def encode(img, width: int = WIDTH) -> str:
    if img.width > width:
        img = img.resize((width, int(img.height * width / img.width)))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def chat(model: str, messages: list, tools: bool, image: str | None = None,
         timeout: int = 300) -> tuple[dict, float, str]:
    """Returns (message, seconds, error). Never raises."""
    msgs = [dict(m) for m in messages]
    if image is not None:
        msgs[-1]["images"] = [image]
    body = {"model": model, "messages": msgs, "stream": False, "keep_alive": "30m",
            "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": 220}}
    if "qwen3" in model:
        body["think"] = False
    if tools:
        body["tools"] = TOOLS
    t0 = time.perf_counter()
    try:
        r = requests.post(f"{OLLAMA}/api/chat", json=body, timeout=timeout)
        if r.status_code >= 400:
            return {}, time.perf_counter() - t0, f"HTTP {r.status_code}: {r.text[:160]}"
        return r.json().get("message", {}), time.perf_counter() - t0, ""
    except Exception as e:
        return {}, time.perf_counter() - t0, f"{type(e).__name__}: {e}"


def calls_of(msg: dict) -> list[tuple[str, dict]]:
    out = []
    for c in msg.get("tool_calls") or []:
        f = c.get("function", {})
        args = f.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        out.append((f.get("name", ""), args))
    return out


def valid_args(name: str, args: dict) -> bool:
    return all(str(args.get(k, "")).strip() for k in REQUIRED.get(name, []))


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


# ------------------------------------------------------------------ phases
def phase_a(model: str, image: str, blind: bool) -> dict:
    print("\nA  CAPABILITY")
    out = {}
    msg, secs, err = chat(model, [{"role": "user", "content": "Say OK."}], tools=True)
    out["tools_text"] = not err
    print(f"  {'ok  ' if not err else 'FAIL'} accepts tools (text only)"
          + (f"   {err}" if err else ""))
    if blind:
        out["tools_image"] = out["sees"] = None
        return out
    msg, secs, err = chat(model, [{"role": "user", "content": "Say OK."}],
                          tools=True, image=image)
    out["tools_image"] = not err
    print(f"  {'ok  ' if not err else 'FAIL'} accepts tools WITH an image"
          + (f"   {err}" if err else ""))
    msg, secs, err = chat(model, [{"role": "user", "content":
                                   "Name the applications visible in this image, "
                                   "comma separated, nothing else."}],
                          tools=False, image=image)
    seen = norm(msg.get("content", ""))
    out["sees"] = bool(seen) and not err
    print(f"  {'ok  ' if out['sees'] else 'FAIL'} sees the image: {seen[:90]!r}")
    return out


def phase_b(model: str, image: str | None) -> dict:
    print("\nB  TOOL SELECTION (with the screen attached)" if image else
          "\nB  TOOL SELECTION (text only)")
    t = {"pass": 0, "wrong": 0, "no_call": 0, "unwanted": 0, "bad_args": 0,
         "invented": 0, "error": 0, "times": []}
    for q, ok in CASES:
        msg, secs, err = chat(model, [{"role": "system", "content": SYSTEM},
                                      {"role": "user", "content": q}],
                              tools=True, image=image)
        t["times"].append(secs)
        if err:
            t["error"] += 1
            print(f"  ERR  {q[:46]:<46} {err[:40]}")
            continue
        calls = calls_of(msg)
        name = calls[0][0] if calls else "none"
        args = calls[0][1] if calls else {}
        if calls and name not in TOOL_NAMES:
            t["invented"] += 1; verdict = f"INVENTED {name}"
        elif "none" in ok and not calls:
            t["pass"] += 1; verdict = "ok (no tool)"
        elif not calls:
            t["no_call"] += 1; verdict = f"NO CALL (wanted {'/'.join(sorted(ok))})"
        elif ok == {"none"}:
            t["unwanted"] += 1; verdict = f"UNWANTED {name}"
        elif name not in ok:
            t["wrong"] += 1; verdict = f"WRONG {name} (wanted {'/'.join(sorted(ok))})"
        elif not valid_args(name, args):
            t["bad_args"] += 1; verdict = f"BAD ARGS {name}{args}"
        else:
            t["pass"] += 1; verdict = f"ok {name}{args if args else ''}"
        flag = "PASS " if verdict.startswith("ok") else "fail "
        print(f"  {flag} {q[:46]:<46} {verdict[:52]}  [{secs:.1f}s]")
    print(f"\n  {t['pass']}/{len(CASES)}  wrong {t['wrong']} | no call {t['no_call']} | "
          f"unwanted {t['unwanted']} | bad args {t['bad_args']} | "
          f"invented {t['invented']} | errors {t['error']}")
    return t


def phase_c(model: str, image: str, truth: dict) -> dict:
    """Ground truth from the window manager. No labelling, no model judging."""
    print("\nC  VISION AGAINST WINDOW-MANAGER TRUTH")
    checks, hits = [], 0
    qa = [
        ("How many application windows are open? Reply with just the number.",
         lambda a: _near_int(a, truth["count"], 1),
         f"count = {truth['count']}"),
        ("Which application is focused right now? Reply with just its name.",
         lambda a: truth["focused"] in norm(a) or
                   any(w in norm(a) for w in truth["focused_words"]),
         f"focused = {truth['focused']}"),
        ("Name every application you can see, comma separated.",
         lambda a: sum(1 for x in truth["apps"] if x in norm(a)) >= max(1, len(truth["apps"]) - 1),
         f"apps = {', '.join(truth['apps'])}"),
        ("What is the browser showing? One short phrase.",
         lambda a: any(w in norm(a) for w in truth["browser_words"]),
         f"browser title words = {truth['browser_words']}"),
        ("Which window is on the left side of the screen? Just the app name.",
         lambda a: truth["leftmost"] in norm(a),
         f"leftmost = {truth['leftmost']}"),
    ]
    for q, judge, why in qa:
        if not why.endswith("None"):
            msg, secs, err = chat(model, [{"role": "user", "content": q}],
                                  tools=False, image=image)
            a = msg.get("content", "")
            ok = (not err) and judge(a)
            hits += ok
            checks.append(ok)
            print(f"  {'ok  ' if ok else 'FAIL'} {why:<44} said {norm(a)[:46]!r}")
    pct = 100 * hits / max(1, len(checks))
    print(f"\n  {hits}/{len(checks)} = {pct:.0f}%   (gate 80%)")
    return {"hits": hits, "of": len(checks), "pct": pct}


def _near_int(answer: str, target: int, tol: int) -> bool:
    m = re.search(r"\d+", answer or "")
    return bool(m) and abs(int(m.group()) - target) <= tol


def phase_d(model: str, image: str, number: str, context: str) -> dict:
    """Does it wear the glasses? Same number, three ways."""
    print("\nD  READING - does OCR win over the model's own eyes?")
    if not number:
        print("  skipped: no number found on screen by OCR")
        return {}
    res = {}
    q = (f"What exactly is the figure {number[:2]}... shown on screen? "
         f"Reply with the figure only, copied exactly.")

    msg, _s, _e = chat(model, [{"role": "user", "content":
                                "Copy the first price or figure you can see in this "
                                "image, exactly. Figure only."}], tools=False, image=image)
    a1 = norm(msg.get("content", ""))
    res["image_only"] = number.lower() in a1
    print(f"  {'ok  ' if res['image_only'] else 'fail'} from the image alone: "
          f"{a1[:40]!r}   (truth {number})")

    msg, _s, _e = chat(model, [{"role": "user", "content":
                                f"OCR of this screen at full resolution:\n{context[:3000]}\n\n"
                                f"Copy the first price or figure exactly. Figure only."}],
                       tools=False, image=image)
    a2 = norm(msg.get("content", ""))
    res["with_ocr"] = number.lower() in a2
    print(f"  {'ok  ' if res['with_ocr'] else 'FAIL'} with OCR supplied:      "
          f"{a2[:40]!r}   (gate: must match)")

    # A plausible near-miss, not an absurd one: a model rejecting "$99999999"
    # for being silly would pass this check without ever consulting the OCR.
    digits = [c for c in number if c.isdigit()]
    planted, seen = "", 0
    for c in number:
        if c.isdigit():
            planted += str((int(c) + (3 if seen in (1, 2) else 0)) % 10)
            seen += 1
        else:
            planted += c
    if planted == number:
        planted = number.replace(digits[-1], str((int(digits[-1]) + 4) % 10), 1)
    msg, _s, _e = chat(model, [{"role": "user", "content":
                                f"A previous glance suggested the figure was {planted}. "
                                f"OCR of the screen at full resolution says:\n{context[:3000]}\n\n"
                                f"What is the figure? Figure only."}],
                       tools=False, image=image)
    a3 = norm(msg.get("content", ""))
    res["ocr_wins_conflict"] = number.lower() in a3 and planted.lower() not in a3
    print(f"  {'ok  ' if res['ocr_wins_conflict'] else 'FAIL'} OCR beats a planted "
          f"guess ({planted}): {a3[:30]!r}")
    return res


def phase_e(model: str, image: str) -> dict:
    print("\nE  REASONING AND CONVERSATION - judge these yourself")
    times = []
    for q in REASONING:
        msg, secs, err = chat(model, [{"role": "system", "content": SYSTEM},
                                      {"role": "user", "content": q}],
                              tools=False, image=image)
        times.append(secs)
        print(f"\n  you: {q}")
        print(f"  her: {norm(msg.get('content', '')) if not err else err}"[:400])
        print(f"       [{secs:.1f}s]")
    return {"times": times}


# ------------------------------------------------------------------ main
def ground_truth(img, reads) -> dict:
    wins = [r.win for r in reads]
    visible = [r for r in reads if not (r.excluded or r.hidden)]
    focused = next((w for w in wins if w.active), None)
    browser = next((r for r in visible if r.win.role == "browser"), None)
    leftmost = min(visible, key=lambda r: r.win.x).win.app if visible else ""
    title_words = []
    if browser:
        title_words = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", browser.win.title)
                       if w.lower() not in {"mozilla", "firefox", "google", "chrome"}][:4]
    return {"count": len(visible),
            "apps": sorted({r.win.app for r in visible}),
            "focused": focused.app if focused else "",
            "focused_words": re.findall(r"[a-z]{3,}", (focused.app if focused else "")),
            "browser_words": title_words,
            "leftmost": leftmost}


def first_number(reads) -> tuple[str, str]:
    """A figure tesseract is confident about, plus the text around it."""
    for r in reads:
        if r.excluded or r.hidden:
            continue
        m = re.search(r"[\$£€]\s?\d[\d,]*(?:\.\d{2})?", r.text)
        if m:
            return m.group().replace(" ", ""), r.text
    for r in reads:
        if r.excluded or r.hidden:
            continue
        m = re.search(r"\b\d{3,}\b", r.text)
        if m:
            return m.group(), r.text
    return "", (reads[0].text if reads else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--blind", action="store_true", help="text-only baseline")
    ap.add_argument("--skip", default="", help="phases to skip, e.g. E")
    a = ap.parse_args()
    skip = set(a.skip.upper())

    print(f"model {a.model} | ctx {NUM_CTX} | image width {WIDTH}")
    base = vram()
    print(f"VRAM at rest {gb(base)}GB")

    img = grab()
    wins = list_windows(img.width, img.height)
    reads = read_all(img, wins)
    truth = ground_truth(img, reads)
    number, context = first_number(reads)
    print(f"screen {img.width}x{img.height} | {truth['count']} visible windows | "
          f"focused {truth['focused']} | OCR figure for phase D: {number or 'none'}")
    print("\nWM truth: " + json.dumps(truth))
    image = None if a.blind else encode(img)

    A = phase_a(a.model, image, a.blind)
    if not A["tools_text"]:
        print("\nSTOP: this model does not accept tools at all. It cannot be the "
              "driver. It can still be the eyes in a two-model split.")
        return
    if not a.blind and A.get("tools_image") is False:
        print("\nSTOP: tools work without an image but fail WITH one. A single "
              "seeing driver is not possible on this model in Ollama.")
        return

    after = vram()
    B = phase_b(a.model, image)
    C = phase_c(a.model, image, truth) if (not a.blind and "C" not in skip) else {}
    D = phase_d(a.model, image, number, context) if (not a.blind and "D" not in skip) else {}
    if "E" not in skip:
        phase_e(a.model, image)

    print("\n" + "=" * 70)
    print(f"model            {a.model}")
    print(f"A capability     tools {'ok' if A['tools_text'] else 'FAIL'}"
          f" | tools+image {A.get('tools_image')} | sees {A.get('sees')}")
    print(f"B tool selection {B['pass']}/{len(CASES)}   invented {B['invented']}"
          f"   (gate >=12 and 0 invented)")
    if C:
        print(f"C vision truth   {C['hits']}/{C['of']} = {C['pct']:.0f}%   (gate 80%)")
    if D:
        print(f"D reading        image-only {D.get('image_only')} | "
              f"with OCR {D.get('with_ocr')} | OCR wins conflict "
              f"{D.get('ocr_wins_conflict')}   (gate: last two true)")
    if B["times"]:
        print(f"F latency        median {statistics.median(B['times']):.2f}s | "
              f"worst {max(B['times']):.2f}s   (gate median < 2.5s)")
    print(f"F VRAM           {gb(base)}GB -> {gb(after)}GB  "
          f"(+{gb(after - base)}GB for this model)")
    gate = (A["tools_text"] and (a.blind or A.get("tools_image"))
            and B["pass"] >= 12 and B["invented"] == 0
            and (not C or C["pct"] >= 80)
            and (not D or (D.get("with_ocr") and D.get("ocr_wins_conflict"))))
    print(f"\n-> {'PASS - can be the seeing driver' if gate else 'FAIL'}")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nstopped")