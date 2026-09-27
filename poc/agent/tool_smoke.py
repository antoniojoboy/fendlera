#!/usr/bin/env python3
"""
tool_smoke.py - STEP 0. Choose the loop driver by measurement.

    source env.sh
    python3 tool_smoke.py --model llama3.1:8b
    python3 tool_smoke.py --model qwen3:8b
    python3 tool_smoke.py --model llama3-groq-tool-use:8b

Twenty scripted questions. Five stubbed tools. Exact-match scoring on:
    - the right tool was selected (or none, when none should be)
    - required arguments are present and non-empty
    - no tool was invented
    - the two-step case chains correctly after a tool result

Touches nothing else. No screen, no OCR, no memory, no web. The stubs return
fixed strings. This decides one thing only: which 8B model can drive the loop.

GATE: >= 18/20 and ZERO invented tools. If no candidate clears it, the design
changes (a larger driver, or q8 without a resident VLM) - not the prompt.

Pull candidates first:
    docker exec -it ollama ollama pull qwen3:8b
    docker exec -it ollama ollama pull llama3-groq-tool-use:8b
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
NUM_CTX = 8192            # same as production - a different value reloads the model

SYSTEM = (
    "You are Desiree, an assistant with tools. Use a tool whenever a question "
    "is about the user's screen, about something seen earlier, about a current "
    "fact you cannot know reliably, or when the user asks you to watch for "
    "something. Answer directly, with no tool, for general knowledge, "
    "arithmetic and conversation. Never call a tool that is not listed."
)

TOOLS = [
    {"type": "function", "function": {
        "name": "read_screen",
        "description": "Survey what is on the user's screen right now: every open "
                       "window with its app, title and first line of content. Use "
                       "for 'what's on my screen', 'is X on screen', or as the first "
                       "step before reading one window in detail.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "read_window",
        "description": "Full text of ONE window on screen, by app name (firefox, "
                       "code, gnome-terminal, ...) or role (browser, editor, "
                       "terminal). Use when the user refers to a specific window, "
                       "page, or app.",
        "parameters": {"type": "object",
                       "properties": {"app": {"type": "string",
                                              "description": "app name or role"}},
                       "required": ["app"]}}},
    {"type": "function", "function": {
        "name": "search_memory",
        "description": "Recall screens the user looked at earlier today or "
                       "recently. Use for 'do you remember', 'earlier', 'before', "
                       "'did we see', 'what was I looking at'.",
        "parameters": {"type": "object",
                       "properties": {"cue": {"type": "string",
                                              "description": "what to search for"}},
                       "required": ["cue"]}}},
    {"type": "function", "function": {
        "name": "research",
        "description": "Look something up on the web across many sources. Use for "
                       "current prices, current office holders, recent releases, or "
                       "any fact that changes over time. Not for general knowledge "
                       "you already have.",
        "parameters": {"type": "object",
                       "properties": {"question": {"type": "string"}},
                       "required": ["question"]}}},
    {"type": "function", "function": {
        "name": "remember",
        "description": "File a standing interest so the user is told later when it "
                       "appears on screen. Use only when the user says they are "
                       "looking for, hunting for, or want to be told about something.",
        "parameters": {"type": "object",
                       "properties": {"want": {"type": "string",
                                               "description": "the thing, in a few words"}},
                       "required": ["want"]}}},
]
TOOL_NAMES = {t["function"]["name"] for t in TOOLS}
REQUIRED = {t["function"]["name"]: t["function"]["parameters"]["required"]
            for t in TOOLS}

# (question, acceptable first tools, chain)
# acceptable = set of tool names, or {"none"} for no tool. Several entries mean
# any of them is a correct choice - some questions genuinely admit two.
CASES = [
    ("What's on my screen?", {"read_screen"}, None),
    ("What does the web page say?", {"read_window"}, None),
    ("Read me what's in the terminal.", {"read_window"}, None),
    ("Do you remember that GPU listing from earlier?", {"search_memory"}, None),
    ("What was I looking at about ten minutes ago?", {"search_memory"}, None),
    ("What's the current price of an RTX 5090 in Australia?", {"research"}, None),
    ("What's the capital of Peru?", {"none"}, None),
    ("Hey, how's it going?", {"none"}, None),
    ("What's 15 percent of 240?", {"none"}, None),
    ("Keep an eye out for an RTX 5080 under 1500 dollars.", {"remember"}, None),
    ("I'm hunting for a used Miata under fifteen grand.", {"remember"}, None),
    ("Is there anything about tariffs on my screen?", {"read_screen", "read_window"}, None),
    ("What's the cheapest thing on this page?", {"read_window", "read_screen"}, None),
    ("Did we see any pink graphics cards earlier?", {"search_memory"}, None),
    ("Who is the prime minister of Australia right now?", {"research"}, None),
    ("What does it say in VS Code?", {"read_window"}, None),
    ("Summarise the article I've got open.", {"read_window", "read_screen"}, None),
    ("How does a heat pump work?", {"none", "research"}, None),
    ("Explain the difference between a list and a tuple in Python.", {"none"}, None),
    # Two-step: the screen shows a build with components but no per-part
    # prices. After that result the model should research, not guess.
    ("Which part in this build is the most expensive?", {"read_screen", "read_window"},
     {"result": "windows: firefox - PLE Infinite RTX 5090 Prebuilt | on screen: "
                "CPU: AMD Ryzen 7 9850X3D; Graphics Card: Gigabyte GeForce RTX "
                "5090 AORUS MASTER ICE 32GB; Memory: Kingston FURY 64GB; Case: "
                "HYTE Y70. Only one price is shown: $13,499 for the whole PC. "
                "No individual component prices are on screen.",
      "then": {"research", "none"}}),
]


def chat(model: str, messages: list, think_off: bool):
    body = {"model": model, "messages": messages, "tools": TOOLS,
            "stream": False, "keep_alive": "10m",
            "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": 200}}
    if think_off:
        body["think"] = False          # qwen3 emits <think> otherwise; ignored elsewhere
    r = requests.post(f"{OLLAMA}/api/chat", json=body, timeout=180)
    r.raise_for_status()
    return r.json().get("message", {})


def calls_of(msg: dict) -> list[tuple[str, dict]]:
    out = []
    for c in msg.get("tool_calls") or []:
        f = c.get("function", {})
        args = f.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"_unparseable": args}
        out.append((f.get("name", ""), args or {}))
    return out


def valid_args(name: str, args: dict) -> bool:
    for k in REQUIRED.get(name, []):
        v = args.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            return False
    return True


def run(model: str, think_off: bool, verbose: bool) -> dict:
    tally = {"pass": 0, "wrong_tool": 0, "no_call": 0, "unwanted_call": 0,
             "bad_args": 0, "invented": 0, "chain_fail": 0, "error": 0}
    t0 = time.perf_counter()

    for q, ok, chain in CASES:
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": q}]
        try:
            msg = chat(model, msgs, think_off)
        except Exception as e:
            tally["error"] += 1
            if verbose:
                print(f"  ERR   {q[:50]:<50} {type(e).__name__}")
            continue

        calls = calls_of(msg)
        name = calls[0][0] if calls else "none"
        args = calls[0][1] if calls else {}

        if calls and name not in TOOL_NAMES:
            tally["invented"] += 1
            verdict = f"INVENTED {name}"
        elif "none" in ok and not calls:
            verdict = "ok (no tool)"
            tally["pass"] += 1
        elif not calls:
            tally["no_call"] += 1
            verdict = f"NO CALL (wanted {'/'.join(sorted(ok - {'none'}))})"
        elif ok == {"none"}:
            tally["unwanted_call"] += 1
            verdict = f"UNWANTED {name}"
        elif name not in ok:
            tally["wrong_tool"] += 1
            verdict = f"WRONG {name} (wanted {'/'.join(sorted(ok - {'none'}))})"
        elif not valid_args(name, args):
            tally["bad_args"] += 1
            verdict = f"BAD ARGS {name}{args}"
        else:
            verdict = f"ok {name}{args if args else ''}"
            if chain:
                msgs.append(msg)
                msgs.append({"role": "tool", "content": chain["result"],
                             "tool_name": name})
                try:
                    msg2 = chat(model, msgs, think_off)
                    c2 = calls_of(msg2)
                    n2 = c2[0][0] if c2 else "none"
                    if n2 in chain["then"] and (n2 == "none" or n2 in TOOL_NAMES):
                        verdict += f" -> {n2} ok"
                    else:
                        tally["chain_fail"] += 1
                        verdict += f" -> {n2} CHAIN FAIL"
                        if verbose:
                            print(f"  {'':6}{q[:50]:<50} {verdict}")
                        continue
                except Exception as e:
                    tally["chain_fail"] += 1
                    verdict += f" -> CHAIN ERR {type(e).__name__}"
                    if verbose:
                        print(f"  {'':6}{q[:50]:<50} {verdict}")
                    continue
            tally["pass"] += 1

        if verbose:
            flag = "PASS " if verdict.startswith("ok") and "FAIL" not in verdict else "fail "
            print(f"  {flag} {q[:50]:<50} {verdict[:70]}")

    tally["seconds"] = round(time.perf_counter() - t0, 1)
    return tally


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    think_off = "qwen3" in a.model.lower()

    print(f"model {a.model} | {len(CASES)} cases | ctx {NUM_CTX}\n")
    t = run(a.model, think_off, verbose=not a.quiet)
    n = len(CASES)
    print(f"\n  {'PASS' if t['pass'] >= 18 and t['invented'] == 0 else 'FAIL'}"
          f"   {t['pass']}/{n} correct   (gate: >= 18 and zero invented)")
    print(f"  wrong tool {t['wrong_tool']} | no call {t['no_call']} | "
          f"unwanted call {t['unwanted_call']} | bad args {t['bad_args']} | "
          f"invented {t['invented']} | chain fail {t['chain_fail']} | "
          f"errors {t['error']} | {t['seconds']}s")
    if t["invented"]:
        print("\n  An invented tool is disqualifying regardless of the score:")
        print("  it means the loop cannot be trusted to stay inside its schema.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nstopped")
