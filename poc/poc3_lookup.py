#!/usr/bin/env python3
"""
POC 3 - Lookup
Question: is a locally-runnable model accurate enough to trust with fetched content?

    source poc/env.sh
    export SEARX_URL=http://localhost:8080     # optional, else duckduckgo

    python poc3_lookup.py "what version of python is current"
    python poc3_lookup.py --test               # 10 scored questions

THIS IS NOT TESTING YOUR ARCHITECTURE, IT IS TESTING YOUR MODEL. Search
plumbing is solved. What you are measuring is whether the model invents detail
the source page did not contain.

You have already seen it do exactly that: in POC 1 it claimed to be using the
OpenWeatherMap API, invented a Perth forecast, and defended the fabricated
source across four turns of pushback. That is the behaviour this scores.

PASS: >=9/10 correct AND ZERO invented specifics.
      One fabricated number is worse than three "I don't know"s.
FAIL: plausible detail not in the source -> try llama3.1:8b-instruct-q8_0
      before you conclude anything about the design.

SECURITY - out of scope here, in scope for production: fetched pages are
attacker-controlled input. In fendlera proper, fetching runs in a quarantined
process with no tools, no memory and no filesystem, so a hostile page captures
something that can only return a string. Do not wire this into anything with
write access, not even as a test.
"""

import os
import re
import sys
import textwrap

import requests
from bs4 import BeautifulSoup

OLLAMA_URL   = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
SEARX_URL    = os.environ.get("SEARX_URL", "")
UA           = "Mozilla/5.0 (compatible; fendlera-poc/0.1)"
MAX_CHARS    = 6000          # per page, into context

# Force the failure mode into the open: it must refuse rather than guess.
SYSTEM = (
    "Answer ONLY from the SOURCES below. Rules:\n"
    "1. If the sources do not contain the answer, reply exactly: NOT IN SOURCES\n"
    "2. Never add a number, date, version or name that is not in the sources.\n"
    "3. Cite the source number you used, like [1].\n"
    "4. Be brief - two sentences maximum."
)

# Specific numbers/dates/versions - that is where models invent.
TEST_QUESTIONS = [
    "What is the latest stable version of Python?",
    "Who is the current Prime Minister of Australia?",
    "What is the population of Perth, Western Australia?",
    "When was PostgreSQL first released?",
    "What port does Ollama listen on by default?",
    "What is the maximum context length of Llama 3.1 8B?",
    "Who founded Anthropic and in what year?",
    "What is the current version of Ubuntu LTS?",
    "How many people work at Perseus Mining?",
    "What licence is faster-whisper released under?",
]


# ---------------------------------------------------------------- search
def search(query: str, n: int = 3):
    if SEARX_URL:
        r = requests.get(f"{SEARX_URL}/search",
                         params={"q": query, "format": "json"},
                         headers={"User-Agent": UA}, timeout=20)
        r.raise_for_status()
        return [(d.get("title", ""), d["url"])
                for d in r.json().get("results", [])[:n]]
    from ddgs import DDGS
    with DDGS() as ddg:
        return [(d.get("title", ""), d["href"])
                for d in ddg.text(query, max_results=n)]


# ---------------------------------------------------------------- fetch
def fetch(url: str) -> str:
    """
    Stage one. In production this runs in a process with no tools, no memory
    and no filesystem. Here it just strips and truncates.
    """
    r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "noscript", "iframe", "form", "aside"]):
        tag.decompose()
    text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n"))
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()[:MAX_CHARS]


# ---------------------------------------------------------------- answer
def answer(question: str, verbose: bool = True):
    try:
        results = search(question)
    except Exception as e:
        print(f"  search failed: {e}")
        return None, []

    sources, blocks = [], []
    for i, (title, url) in enumerate(results, 1):
        try:
            body = fetch(url)
        except Exception as e:
            if verbose:
                print(f"  [{i}] fetch failed {url} ({e})")
            continue
        if not body:
            continue
        sources.append((i, title, url))
        blocks.append(f"[{i}] {title}\n{url}\n\n{body}")
        if verbose:
            print(f"  [{i}] {title[:70]}  ({len(body)} chars)")

    if not blocks:
        print("  no usable sources")
        return None, []

    prompt = "SOURCES\n\n" + "\n\n---\n\n".join(blocks) + f"\n\nQUESTION: {question}"
    r = requests.post(f"{OLLAMA_URL}/api/chat",
                      json={"model": OLLAMA_MODEL, "stream": False,
                            "options": {"temperature": 0},
                            "messages": [{"role": "system", "content": SYSTEM},
                                         {"role": "user", "content": prompt}]},
                      timeout=240)
    r.raise_for_status()
    return r.json()["message"]["content"].strip(), sources


# ---------------------------------------------------------------- modes
def run_test():
    print(f"model: {OLLAMA_MODEL}   search: {SEARX_URL or 'duckduckgo'}\n")
    print("Score each yourself against the source. Track INVENTED separately -")
    print("that is the number that matters.\n" + "=" * 68)

    rows = []
    for i, q in enumerate(TEST_QUESTIONS, 1):
        print(f"\n[{i:>2}] {q}")
        a, srcs = answer(q, verbose=True)
        if a is None:
            rows.append((i, q, "NO SOURCES", ""))
            continue
        print(f"\n     ANSWER: {textwrap.fill(a, 66, subsequent_indent='             ')}")
        for n, _t, url in srcs:
            print(f"     [{n}] {url}")
        rows.append((i, q, a, srcs[0][2] if srcs else ""))

    print("\n" + "=" * 68)
    print("\nSCORE SHEET - open each source and check every specific claim\n")
    print(f"  {'#':<4}{'correct':<10}{'invented':<10}question")
    for i, q, _a, _u in rows:
        print(f"  {i:<4}{'[ ]':<10}{'[ ]':<10}{q[:44]}")
    print("\n  correct:  ___/10   (bar: 9)")
    print("  invented: ___/10   (bar: 0)")
    print("\n  'NOT IN SOURCES' is a CORRECT answer when the sources lack it.")
    print("  Refusing to guess is the behaviour you want.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} \"question\"  |  --test")
        sys.exit(1)
    if sys.argv[1] == "--test":
        run_test()
    else:
        q = " ".join(sys.argv[1:])
        a, srcs = answer(q)
        if a:
            print(f"\n{textwrap.fill(a, 74)}\n")
            for n, t, url in srcs:
                print(f"  [{n}] {t[:60]}\n      {url}")
