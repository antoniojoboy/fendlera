#!/usr/bin/env python3
"""
agent.py - STEP 2. The loop. Text in, text out. No voice, no watcher.

    source env.sh
    python3 agent.py                         # REPL
    python3 agent.py "what's on my screen"   # one question
    python3 agent.py --trace "..."           # show every tool call and result

ONE LOOP, SEVEN TOOLS, NO ROUTER
    user turn
      -> model sees: system, tool schemas, earlier USER turns, earlier TOOL
         RESULTS (digested) - never her own earlier prose
      -> model emits tool calls (zero or more)
      -> harness runs each: named, fixed schema, sandboxed; returns data + source
      -> repeat, max 4 steps
      -> model answers; the answer must say which sense each fact came from

TOOLS AND WHAT THEY RETURN
    read_screen        OCR   survey: every window, app, title, first line   [read]
    read_window(app)   OCR   full text + label/value pairs of one window      [read]
    describe_screen    VLM   layout and appearance of the whole screen        [impression]
    describe_window    VLM   appearance of one window, higher resolution      [impression]
    search_memory      log   episodes matching a cue, with age + confidence   [recalled]
    research           web   verified points across many pages               [web]
    remember           log   files a standing want                           [filed]

[read] means OCR - exact text, trustworthy for numbers. [impression] means the
vision model - layout, colour, what things look like - never trusted for a
number. The distinction is carried in every tool result and the model is told
to carry it into every answer. That is the whole grounding mechanism; there
is no "never guess" rule.

WHY HER PROSE IS NOT IN THE CONTEXT
Yesterday she copied her previous description verbatim over a screen that had
changed, and later repeated a past "I don't know" over an answer sitting in
front of her. Her output filed as evidence outranked the evidence. ADR-0002.
So the model gets prior user turns and prior tool results, digested - and
nothing she said.

GATE: ten questions answered correctly by eye, including "which part in this
build is the most expensive" doing read -> research -> answer.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time

import requests

from windows import list_windows, pick
from screenread import grab, read_all, survey
from recall import Memory, Interests

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DRIVER = os.environ.get("DRIVER_MODEL", "qwen3:8b")
VLM = os.environ.get("VLM_MODEL", "qwen2.5vl:7b")
NUM_CTX = int(os.environ.get("NUM_CTX", "8192"))
MAX_STEPS = 4
LOG = os.environ.get("AGENT_LOG", "agent_turns.jsonl")

SYSTEM = (
    "You are Desiree, an assistant on the user's Linux desktop with tools that "
    "read the screen, look at the screen, recall earlier screens, search the "
    "web, and file things to watch for.\n\n"
    "DEFAULT TO USING A TOOL. Answer without one only when the answer is "
    "settled ground: arithmetic, definitions, history, how things work in "
    "general, or plain conversation. Everything else - anything about the "
    "world as it is now, any product, person, organisation, price, version or "
    "event, anything that could depend on the user's screen or on what they "
    "saw earlier - gets looked up. Looking is cheap; a confident stale answer "
    "is not. If unsure whether to look, look.\n\n"
    "The screen changes constantly: look every time it is asked about. Nothing "
    "from an earlier turn is current.\n\n"
    "Every tool result is tagged with its source. Say where each fact came "
    "from: 'the screen says', 'it looks like', 'from earlier', 'from the web', "
    "or 'from what I know'. State a number only if a [read] or [web] result "
    "this turn contained it, or say it is from your own knowledge.\n\n"
    "Messages beginning with '[' are notes to you about earlier turns - never "
    "repeat them.\n\n"
    "Reply in at most five plain sentences. No lists, no markdown."
)

TOOLS = [
    {"type": "function", "function": {
        "name": "read_screen",
        "description": "Survey the screen right now: every open window with its "
                       "app, title and first line of text. Exact text (OCR). Use "
                       "first for any question about what is on screen.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "read_window",
        "description": "The full text of ONE window, plus any label/value pairs "
                       "on it (spec sheets, forms). Exact text (OCR). app is an "
                       "app name (firefox, code, gnome-terminal) or a role "
                       "(browser, editor, terminal).",
        "parameters": {"type": "object",
                       "properties": {"app": {"type": "string"}},
                       "required": ["app"]}}},
    {"type": "function", "function": {
        "name": "describe_screen",
        "description": "What the whole screen LOOKS like: layout, which windows, "
                       "images, colours. A visual impression, not exact text - "
                       "never use it for numbers or small print.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "describe_window",
        "description": "What ONE window looks like, at higher resolution: images, "
                       "colours, layout. Visual impression only.",
        "parameters": {"type": "object",
                       "properties": {"app": {"type": "string"}},
                       "required": ["app"]}}},
    {"type": "function", "function": {
        "name": "search_memory",
        "description": "Recall screens the user looked at earlier: 'do you "
                       "remember', 'earlier', 'before', 'did we see'.",
        "parameters": {"type": "object",
                       "properties": {"cue": {"type": "string"}},
                       "required": ["cue"]}}},
    {"type": "function", "function": {
        "name": "research",
        "description": "Look a question up on the web and return points verified "
                       "against their pages. The default for anything about the "
                       "world as it is now. depth 'quick' reads ~6 pages (~15s) - "
                       "use it unless the question needs many sources reconciled, "
                       "then 'deep' (~16 pages, ~45s).",
        "parameters": {"type": "object",
                       "properties": {"question": {"type": "string"},
                                      "depth": {"type": "string",
                                                "enum": ["quick", "deep"]}},
                       "required": ["question"]}}},
    {"type": "function", "function": {
        "name": "remember",
        "description": "File something the user wants to be told about when it "
                       "appears on screen, e.g. 'rtx 5080 under 1500'. Only when "
                       "they say they are looking out for it.",
        "parameters": {"type": "object",
                       "properties": {"want": {"type": "string"}},
                       "required": ["want"]}}},
]
TOOL_NAMES = {t["function"]["name"] for t in TOOLS}


# ------------------------------------------------------------------ tools
class Tools:
    """Each method returns {"source": str, "content": str}. Screen tools
    share one capture per turn so two reads see the same frame."""

    def __init__(self):
        self.mem = Memory()
        self.ints = Interests()
        self._frame = None
        self._reads = None

    def new_turn(self):
        self._frame = self._reads = None

    def _capture(self):
        if self._frame is None:
            self._frame = grab()
            wins = list_windows(self._frame.width, self._frame.height)
            self._reads = read_all(self._frame, wins)
            text = "\n\n".join(f"[{r.win.app}] {r.win.title}\n{r.text}"
                               for r in self._reads if not (r.excluded or r.hidden)
                               and len(r.text) > 40)
            if text:
                self.mem.see(text)               # every look becomes memory
        return self._frame, self._reads

    def read_screen(self) -> dict:
        _f, reads = self._capture()
        if not reads:
            return {"source": "[read] screen OCR", "content": "No windows found."}
        return {"source": "[read] screen OCR", "content": survey(reads)}

    def read_window(self, app: str) -> dict:
        _f, reads = self._capture()
        wins = [r.win for r in reads]
        w = pick(wins, app)
        if not w:
            names = ", ".join(sorted({v.app for v in wins}))
            return {"source": "[read] screen OCR",
                    "content": f"No window matches '{app}'. Open windows: {names}."}
        r = next(r for r in reads if r.win.wid == w.wid)
        if r.excluded:
            return {"source": f"[read] {w.app}", "content": "That window is excluded from reading."}
        if r.hidden:
            return {"source": f"[read] {w.app}", "content": "That window is mostly behind others; not readable."}
        pairs = r.spec_pairs()
        out = f"WINDOW {w.app}: {w.title}\n"
        if pairs:
            out += "LABEL/VALUE PAIRS:\n" + "\n".join(f"  {a}: {b}" for a, b in pairs[:30]) + "\n"
        out += "TEXT:\n" + r.text[:6000]
        return {"source": f"[read] OCR of {w.app}", "content": out}

    def _vlm(self, img, prompt: str, width: int = 1280) -> str:
        if img.width > width:
            img = img.resize((width, int(img.height * width / img.width)))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        r = requests.post(f"{OLLAMA}/api/chat", json={
            "model": VLM, "stream": False, "keep_alive": "30m",
            "options": {"temperature": 0.2, "num_ctx": NUM_CTX, "num_predict": 160},
            "messages": [{"role": "user", "content": prompt,
                          "images": [base64.b64encode(buf.getvalue()).decode()]}]},
            timeout=300)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()

    def describe_screen(self) -> dict:
        frame, _r = self._capture()
        text = self._vlm(frame, "Describe this screen in three sentences: the "
                                "layout, what each window appears to be, and any "
                                "images or notable colours. Do not read small text "
                                "and do not state any numbers.")
        return {"source": "[impression] vision model, whole screen", "content": text}

    def describe_window(self, app: str) -> dict:
        frame, reads = self._capture()
        w = pick([r.win for r in reads], app)
        if not w:
            return {"source": "[impression]", "content": f"No window matches '{app}'."}
        x1, y1, x2, y2 = w.rect
        crop = frame.crop((max(0, x1), max(0, y1), min(x2, frame.width), min(y2, frame.height)))
        text = self._vlm(crop, "Describe what this window shows in three sentences: "
                               "what kind of page or app, any images or products "
                               "and their colours, and the layout. Do not state "
                               "numbers.", width=1600)
        return {"source": f"[impression] vision model, {w.app}", "content": text}

    def search_memory(self, cue: str) -> dict:
        out = self.mem.phrase(cue, 4)
        return {"source": "[recalled] episode log",
                "content": out or f"No memory of anything matching '{cue}'."}

    def research(self, question: str, depth: str = "quick") -> dict:
        import research as R
        want = 16 if depth == "deep" else 6
        res = R.research(question, want=want, per_query=4 if want == 6 else 6,
                         verbose=False)
        lines = []
        n = res.get("numeric")
        if n:
            lines.append(f"NUMERIC: {n['currency'] or ''} {n['median']:,.2f} median of "
                         f"{n['agree']} agreeing sources, range {n['low']:,.2f}-{n['high']:,.2f}")
        for c in res["clusters"][:6]:
            p = c["points"][0]
            lines.append(f"- [{len(c['domains'])} sites] {c['aspect']}: {p.point} "
                         f"(\"{p.quote[:70]}\" - {p.source.domain})")
        if not lines:
            lines.append("NOT FOUND: nothing verifiable against its own page.")
        src = (f"[web] fetched {res['sources']} given page(s)" if R.URL_RE.search(question)
               else f"[web] {res['sources']} pages, {depth}")
        return {"source": src, "content": "\n".join(lines)}

    def remember(self, want: str) -> dict:
        x = self.ints.add(want)
        if not x:
            return {"source": "[filed]", "content": f"Not filed: '{want}' is too vague or already filed."}
        return {"source": "[filed]", "content": f"Watching for: {x['phrase']}."}

    def run(self, name: str, args: dict) -> dict:
        fn = getattr(self, name, None)
        if name not in TOOL_NAMES or fn is None:
            return {"source": "[error]", "content": f"No such tool: {name}."}
        try:
            return fn(**{k: v for k, v in args.items()
                         if k in fn.__code__.co_varnames})
        except TypeError as e:
            return {"source": "[error]", "content": f"Bad arguments for {name}: {e}"}
        except Exception as e:
            return {"source": "[error]", "content": f"{name} failed: {type(e).__name__}: {e}"}


# ------------------------------------------------------------------ provenance
import re

WEB_CLAIM = re.compile(r"\b(from the web|web sources?|online|according to (the )?"
                       r"(web|internet)|i (have )?looked (it |that )?up|search results?)\b", re.I)
# 'I can see' and 'it looks like' are idioms, not screen claims - listing them
# turned a correct research answer into a false confession.
SCREEN_CLAIM = re.compile(r"\b(the screen (says|shows|displays)|on (the |your )?screen|"
                          r"your screen|the (window|page|browser) (shows|says|displays))\b", re.I)
ECHO = re.compile(r"\[(used:|no tools\]|web\]|read\]|recalled\]|filed\]|impression\])")
NUMBER = re.compile(r"(?:[\$£€]\s?\d[\d,]*|\b\d{1,3}(?:,\d{3})+\b|\b\d{4,}\b|"
                    r"\b\d+\.\d+\b|\bAUD\b|\bUSD\b)")
OWN_KNOWLEDGE = re.compile(r"\b(from (my|what i) (own )?know(ledge)?|not checked|i believe|"
                           r"as far as i know|i think)\b", re.I)

SCREEN_TOOLS = {"read_screen", "read_window", "describe_screen", "describe_window"}

# An explicit instruction is honoured regardless of what the model decides.
# This is not a router guessing intent - it is the user saying which tool.
EXPLICIT = [
    (re.compile(r"\b(research|look (it |that |this )?up|search (for|the web for)|"
                r"google|find out|check online)\b|https?://", re.I), "research"),
    (re.compile(r"\b(look (at|on) (my |the )?screen|read (my |the )?screen|"
                r"what'?s on (my |the )?screen|see (my |the )?screen|"
                r"check (my |the )?screen)\b", re.I), "read_screen"),
]
SHORT_REF = re.compile(r"^\W*(research|look (it |that |this )?up|search|google|"
                       r"find out|check online)( for)?( it| that| this)?\W*$", re.I)


def explicit_tools(text: str) -> set[str]:
    return {tool for rx, tool in EXPLICIT if rx.search(text)}


def research_query(text: str, previous: str) -> str:
    """'look it up' means the previous question; otherwise strip the verb."""
    if SHORT_REF.match(text.strip()) and previous:
        return previous
    q = re.sub(r"\b(can you|could you|please|go and|just|for me)\b", "", text, flags=re.I)
    q = re.sub(r"\b(research|look (it |that |this )?up|search (for|the web for)|"
               r"google|find out|check online)\b", "", q, flags=re.I)
    return re.sub(r"\s+", " ", q).strip(" ?.,:") or previous or text


# The model DOES have these tools. A denial is wrong every time it is uttered,
# and asking permission is declining to act. Both become forced tool calls.
DENY_SCREEN = re.compile(r"\b(don'?t|do not|cannot|can'?t|unable to|no) (have )?(access|see|view|"
                         r"look at|read)\b[^.]{0,40}\b(screen|display|desktop|window)", re.I)
DENY_WEB = re.compile(r"\b(don'?t|do not|cannot|can'?t|unable to|no) (have )?(access|browse|"
                      r"search|look)\b[^.]{0,40}\b(web|internet|online|current|latest|real-?time|"
                      r"reviews?|pricing|prices?|up-to-date)", re.I)
ASK_PERMISSION = re.compile(r"\b(would you like|do you want|shall i|should i|want me to)\b"
                            r"[^.?]{0,40}\b(research|look (it |that )?up|search|check|find out|"
                            r"look at (your |the )?screen)\b", re.I)


def denied_or_deferred(answer: str) -> set[str]:
    """Tools the model wrongly said it lacked, or asked permission to use."""
    out = set()
    if DENY_SCREEN.search(answer):
        out.add("read_screen")
    if DENY_WEB.search(answer) or (ASK_PERMISSION.search(answer)
                                   and re.search(r"research|look|search|check|find", answer, re.I)
                                   and not re.search(r"screen", answer, re.I)):
        out.add("research")
    if ASK_PERMISSION.search(answer) and re.search(r"screen", answer, re.I):
        out.add("read_screen")
    return out


def provenance_violations(answer: str, used: set[str]) -> list[str]:
    """The model is not trusted to be honest about where a fact came from.
    A claimed source must correspond to a tool actually run this turn."""
    v = []
    if ECHO.search(answer):
        v.append("repeats internal notes (lines beginning with '[') instead of answering")
    if WEB_CLAIM.search(answer) and "research" not in used:
        v.append("says 'from the web' but research was not used this turn")
    if SCREEN_CLAIM.search(answer) and not (used & SCREEN_TOOLS) \
            and not DENY_SCREEN.search(answer):
        v.append("describes the screen but did not look this turn")
    return v


def flag_unbacked_numbers(answer: str, sources: list[str]) -> str:
    """A number with no [read] or [web] result behind it is the model's own
    knowledge. If it did not say so, say so for it."""
    backed = any(("[read]" in s or "[web]" in s) for s in sources)
    if NUMBER.search(answer) and not backed and not OWN_KNOWLEDGE.search(answer):
        return answer.rstrip() + " (That figure is from my own knowledge, not checked.)"
    return answer


# ------------------------------------------------------------------ loop
def chat(messages: list, use_tools: bool = True) -> dict:
    body = {"model": DRIVER, "messages": messages, "stream": False,
            "keep_alive": "30m", "think": False,
            "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": 300}}
    if use_tools:
        body["tools"] = TOOLS
    r = requests.post(f"{OLLAMA}/api/chat", json=body, timeout=300)
    r.raise_for_status()
    return r.json()["message"]


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


class Agent:
    def __init__(self, tools: Tools | None = None, chat_fn=chat, trace: bool = False):
        self.tools = tools or Tools()
        self.chat = chat_fn
        self.trace = trace
        self.context: list[dict] = []        # prior USER turns + digested tool results only

    def _digest(self, results: list[dict]) -> str:
        return "\n".join(f"{r['source']}: {r['content'][:280]}" for r in results)

    def _run_loop(self, messages: list, results: list, called: list) -> tuple[str, int]:
        """Tool loop until an answer. Mutates messages/results/called."""
        steps, answer = 0, ""
        while True:
            msg = self.chat(messages, use_tools=(steps < MAX_STEPS))
            calls = calls_of(msg)
            if not calls:
                answer = (msg.get("content") or "").strip()
                break
            if steps >= MAX_STEPS:
                messages.append({"role": "user", "content":
                                 "No more tools. Answer now from the results above, "
                                 "and say what is missing if something is."})
                msg = self.chat(messages, use_tools=False)
                answer = (msg.get("content") or "").strip()
                break
            steps += 1
            messages.append({"role": "assistant", "content": msg.get("content") or "",
                             "tool_calls": msg.get("tool_calls")})
            for name, args in calls:
                res = self.tools.run(name, args)
                results.append(res)
                called.append({"tool": name, "args": args, "source": res["source"]})
                if self.trace:
                    print(f"    -> {name}({args})  {res['source']}")
                    print("       " + res["content"][:400].replace("\n", "\n       "))
                messages.append({"role": "tool", "tool_name": name,
                                 "content": f"{res['source']}\n{res['content']}"})
        return answer, steps

    def ask(self, text: str) -> dict:
        t0 = time.perf_counter()
        self.tools.new_turn()
        messages = [{"role": "system", "content": SYSTEM}] + self.context + \
                   [{"role": "user", "content": text}]
        results, called = [], []

        answer, steps = self._run_loop(messages, results, called)

        # Explicit instructions are honoured even if the model declined.
        required = (explicit_tools(text) | denied_or_deferred(answer)) - {c["tool"] for c in called}
        if required:
            prev = next((m["content"] for m in reversed(self.context)
                         if m["role"] == "user" and not m["content"].startswith("[")), "")
            messages.append({"role": "assistant", "content": answer})
            for tool in sorted(required):
                args = {"question": research_query(text, prev)} if tool == "research" else {}
                res = self.tools.run(tool, args)
                results.append(res)
                called.append({"tool": tool, "args": args, "source": res["source"],
                               "forced": True})
                if self.trace:
                    print(f"    -> {tool}({args})  {res['source']}  [forced: you asked]")
                    print("       " + res["content"][:400].replace("\n", "\n       "))
                messages.append({"role": "user", "content":
                                 f"You were asked to {tool.replace('_', ' ')}. Result:\n"
                                 f"{res['source']}\n{res['content']}\n\nNow answer."})
            msg = self.chat(messages, use_tools=False)
            answer = (msg.get("content") or "").strip()

        # Provenance enforcement: one corrective retry, then an honest fallback.
        used = {c["tool"] for c in called}
        violations = provenance_violations(answer, used)
        corrected = False
        if violations:
            messages.append({"role": "assistant", "content": answer})
            messages.append({"role": "user", "content":
                             "Your answer " + "; ".join(violations) + ". Use the "
                             "tool now, or restate the answer without that claim."})
            answer, more = self._run_loop(messages, results, called)
            steps += more
            corrected = True
            used = {c["tool"] for c in called}
            if provenance_violations(answer, used):
                answer = ("I claimed a source I didn't actually check. "
                          "I don't have that - do you want me to look it up?")

        if not answer:
            answer = ("I could not put an answer together from that."
                      + (" The tools returned: " + self._digest(results)[:300]
                         if results else ""))
        answer = flag_unbacked_numbers(answer, [r["source"] for r in results])

        # Carry forward: the user's words, which tools were used, and DURABLE
        # results only (web, memory). Screen results are perishable - carrying
        # them made her answer 'what's on the screen' from the last look.
        self.context.append({"role": "user", "content": text})
        durable = [r for r in results if r["source"].startswith(("[web]", "[recalled]", "[filed]"))]
        marker = ("[used: " + ", ".join(sorted(used)) + "]") if used else "[no tools]"
        if durable:
            self.context.append({"role": "user", "content":
                                 f"{marker}\n" + self._digest(durable)})
        else:
            self.context.append({"role": "user", "content": marker})
        self.context = self.context[-12:]

        turn = {"ts": time.time(), "question": text, "answer": answer,
                "tools": called, "steps": steps, "corrected": corrected,
                "violations": violations,
                "seconds": round(time.perf_counter() - t0, 2)}
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(turn) + "\n")
        except OSError:
            pass
        return turn


def preload():
    for m in (DRIVER, VLM):
        body = {"model": m, "prompt": "ok", "stream": False, "keep_alive": "30m",
                "options": {"num_ctx": NUM_CTX, "num_predict": 1}}
        requests.post(f"{OLLAMA}/api/generate", json=body, timeout=900)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="*")
    ap.add_argument("--trace", action="store_true")
    a = ap.parse_args()

    print(f"driver {DRIVER} | vision {VLM} | ctx {NUM_CTX}")
    print("preloading...")
    preload()
    agent = Agent(trace=a.trace)

    if a.question:
        t = agent.ask(" ".join(a.question))
        print(f"\n{t['answer']}\n  [{t['steps']} tool step(s), {t['seconds']}s]")
        return

    print("ready. ctrl-c to quit.\n")
    while True:
        try:
            q = input("you: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye"); return
        if not q:
            continue
        t = agent.ask(q)
        print(f"her: {t['answer']}")
        print(f"     [{', '.join(c['tool'] for c in t['tools']) or 'no tools'}"
              f" | {t['seconds']}s]\n")


if __name__ == "__main__":
    main()