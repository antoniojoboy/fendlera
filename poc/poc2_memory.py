#!/usr/bin/env python3
"""
POC 2 - Memory
Question: can it recall accurately under load, and correct itself when a fact
changes?

    source poc/env.sh

    python poc2_memory.py seed          # inject 20 facts with filler between
    python poc2_memory.py stats         # file size / token estimate
    python poc2_memory.py quiz          # ask all 20 back, scored
    python poc2_memory.py contradict    # change one fact, check which wins
    python poc2_memory.py chat          # talk to it

    python poc2_memory.py seed --echo   # reproduce the write-path bug (below)

    python poc2_memory.py xseed         # same, via write-time extraction
    python poc2_memory.py xquiz
    python poc2_memory.py xcontradict
    python poc2_memory.py xstats

TWO PATHS, DELIBERATELY.

  NAIVE  (seed/quiz/...)   append-only markdown, whole file into context every
                           turn. No vectors, no retrieval. The point is to FIND
                           the failure mode, not avoid it.

  EXTRACT (xseed/xquiz/...) a second pass decides what is durable and writes a
                           fact line, superseding rather than appending.
                           Conflicts resolve ONCE, at write time, by a process
                           with nothing else to do - instead of being
                           re-resolved on every read under time pressure.

WHAT THE FIRST RUN FOUND (2026-09-05, llama3.1:8b, 820 tokens):

  During seed, each fact arrives as a user turn while the memory file does not
  yet contain it. SYSTEM says "answer from the file, never guess", so the model
  treated the statement as a question, found nothing, and replied "I don't
  know." That denial was then appended to memory directly beneath the fact.

  At quiz time the model read each fact followed by a denial of it. The denial
  won. Seven facts were poisoned this way, and every single quiz failure came
  from that set - zero failures outside it.

  Not a recall problem. Not lost-in-the-middle. The WRITE PATH corrupted the
  store: the assistant's own output was filed as though it were established
  fact, and then overrode the user's statement sitting one line above it.

  Fix: seed no longer records the assistant's reply (echo=False). Pass --echo
  to reproduce the original behaviour and watch it happen.

PASS: >=18/20 recalled, and the contradiction handled (new fact wins).
"""

import os
import re
import sys
import json
import time
import datetime as dt

import requests

OLLAMA_URL   = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
MEM          = os.environ.get("MEM_FILE", "memory.md")
FACTS_FILE   = os.environ.get("FACTS_FILE", "facts.md")
# Append-only log of every statement and every supersession (ADR-0044).
# Never loaded wholesale; grepped only when facts cannot answer.
LOG_FILE     = os.environ.get("FACTS_LOG_FILE",
                              os.path.join(os.path.dirname(os.path.abspath(FACTS_FILE)),
                                           "facts_log.md"))

# temperature 0 so a re-run is comparable. Without this the default is ~0.8 and
# the same file scored 17, 17 and 19 on three consecutive runs - wide enough to
# straddle the pass bar and make you draw the wrong conclusion from n=1.
OPTIONS = {"temperature": 0}

SYSTEM = (
    "You are a personal assistant with a persistent memory file. Everything "
    "you have been told is below. Answer from it. If a fact was later changed, "
    "the most recent statement wins. If you do not know, say you do not know - "
    "never guess."
)

# The extraction pass. Deliberately narrow: it decides what is durable and
# emits one operation. It never writes prose, and it never answers the user.
EXTRACT_SYSTEM = (
    "You extract durable facts for a memory store. You are given the current "
    "facts and one new statement from the user.\n"
    "Reply with ONE JSON object and nothing else. No markdown, no backticks.\n"
    '  {"action":"add","key":"<short key>","value":"<the fact>"}\n'
    '  {"action":"update","key":"<existing key>","value":"<the new fact>"}\n'
    '  {"action":"skip"}\n'
    "ALWAYS add a statement about any of these, even if it seems minor: where "
    "the user lives, works or studies; their job; people in their life; their "
    "projects, machines, devices and tools; their plans, budgets and goals; "
    "their stated preferences and habits.\n"
    "Keep the whole fact in the value, not a fragment - 'Northmoor Freight, "
    "logistics analyst', not just 'Northmoor Freight'. Include what kind of "
    "thing it is when that is stated ('suburb', 'street').\n"
    "Use update ONLY when the new statement changes the SAME fact already in "
    "the store - reuse that key exactly. A statement ABOUT an existing fact "
    "(an extra detail, a nickname, a mishearing) is a new fact with its own "
    "new key, not an update.\n"
    "Use skip ONLY for chit-chat that says nothing about the user. When in "
    "doubt, add: a wrong add costs one line, a wrong skip loses the fact.\n"
    "Keys are lowercase, two to four words, no punctuation."
)

# ---------------------------------------------------------------------------
# TEST FIXTURES - invented, not real personal data. They exist to be recalled
# as arbitrary strings; their truth is irrelevant to what this measures. Keys
# are checked for uniqueness so no question can be answered from the wrong
# fact. (An earlier version used the platform name as both the project and the
# street name, which made one question scoreable two ways.)
# ---------------------------------------------------------------------------
FACTS = [
    "My cat is called Pemberton.",
    "I live in the suburb of Hallidge.",
    "My main machine is called Sakura.",
    "The platform I'm building is called fendlera.",
    "My assistant persona is called Desiree.",
    "I work at Northmoor Freight as a logistics analyst.",
    "Our head office is in Kalgan.",
    "I'm studying for the AZ-305 certification.",
    "My street is Verrall Road.",
    "My commute takes about 25 minutes.",
    "My GPU runs hot above 80 degrees and I want warning at 78.",
    "I take my coffee black with no sugar.",
    "The data warehouse runs on Azure Synapse.",
    "I have a Sony SRS-XB3 bluetooth speaker.",
    "My budget for this project is 5 to 10 hours a week.",
    "I want three POCs done in the first week.",
    "The old work platform was called Chrysus.",
    "People kept hearing Chrysus as 'crisis'.",
    "I use Ollama for local inference.",
    "My preferred notification channel is push to phone.",
]

QUESTIONS = [
    ("What is my cat called?", "pemberton"),
    ("What suburb do I live in?", "hallidge"),
    ("What is my main machine called?", "sakura"),
    ("What is the platform I'm building called?", "fendlera"),
    ("What is my assistant persona called?", "desiree"),
    ("Where do I work and what's my job title?", "northmoor"),
    ("Which suburb is our head office in?", "kalgan"),
    ("Which certification am I studying for?", "az-305"),
    ("What street do I live on?", "verrall"),
    ("How long is my commute?", "25"),
    ("At what GPU temperature do I want a warning?", "78"),
    ("How do I take my coffee?", "black"),
    ("What does the data warehouse run on?", "synapse"),
    ("What bluetooth speaker do I own?", "xb3"),
    ("How many hours a week is my budget?", "5"),
    ("How many POCs do I want in week one?", "three"),
    ("What was the old work platform called?", "chrysus"),
    ("What did people mishear that name as?", "crisis"),
    ("What do I use for local inference?", "ollama"),
    ("What's my preferred notification channel?", "push"),
]

FILLER = [
    "What's a good way to structure a Python project?",
    "Explain the difference between a list and a tuple.",
    "What's the weather like in general in September?",
    "Tell me something about gold mining.",
    "How does a heat pump work?",
]


# ---------------------------------------------------------------- ollama
def chat(system: str, user: str, timeout: int = 180) -> str:
    r = requests.post(f"{OLLAMA_URL}/api/chat",
                      json={"model": OLLAMA_MODEL, "stream": False,
                            "options": OPTIONS,
                            "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": user}]},
                      timeout=timeout)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


# ---------------------------------------------------------------- naive path
def read_mem() -> str:
    if not os.path.exists(MEM):
        return ""
    with open(MEM, encoding="utf-8") as f:
        return f.read()


def append_mem(role: str, text: str):
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(MEM, "a", encoding="utf-8") as f:
        f.write(f"\n[{stamp}] {role}: {text.strip()}\n")


def ask(user_text: str, record: bool = True, echo: bool = False) -> str:
    """
    Whole memory file into context. This is the naive bit, on purpose.

    echo=False writes only the user's statement. echo=True also writes the
    assistant's reply - which is what poisoned the store on the first run.
    """
    reply = chat(SYSTEM + "\n\n--- MEMORY FILE ---\n" + read_mem(), user_text)
    if record:
        append_mem("user", user_text)
        if echo:
            append_mem("assistant", reply)
    return reply


# ---------------------------------------------------------------- extract path
_LINE = re.compile(r"^- ([^:]+): (.*)$")


def read_facts() -> "dict[str, str]":
    facts = {}
    if os.path.exists(FACTS_FILE):
        for line in open(FACTS_FILE, encoding="utf-8"):
            m = _LINE.match(line.rstrip())
            if m:
                facts[m.group(1).strip()] = m.group(2).strip()
    return facts


def write_facts(facts: "dict[str, str]"):
    with open(FACTS_FILE, "w", encoding="utf-8") as f:
        f.write("# facts\n\n")
        for k, v in facts.items():
            f.write(f"- {k}: {v}\n")


def facts_block() -> str:
    facts = read_facts()
    if not facts:
        return "(empty)"
    return "\n".join(f"- {k}: {v}" for k, v in facts.items())


# Deterministic, before any model sees the statement. A model deciding what
# is "worth remembering" was the failure (POC 2 re-run, 28 Sep 2026): Q4 and
# q8 each skipped a different set of real facts. Rules decide the obvious
# cases; the model never gets a vote on them.
_QUESTION = re.compile(
    r"^\s*(what|what's|whats|who|whom|whose|when|where|why|how|which|is|are|"
    r"am|was|were|do|does|did|can|could|would|should|will|shall|may|might|"
    r"have|has|had)\b", re.I)
_REQUEST = re.compile(
    r"^\s*(please\s+)?(tell|explain|describe|show|give|list|find|search|"
    r"look|help|write|make|let's|lets)\b", re.I)
_REMEMBER = re.compile(
    r"^\s*(please\s+)?(remember|note|don't forget|dont forget|keep in mind)"
    r"(\s+that)?[\s,:]*", re.I)
_PREVIOUSLY = re.compile(r"\s*\(previously .*\)\s*$")


def is_question_or_request(text: str) -> bool:
    t = text.strip()
    return t.endswith("?") or bool(_QUESTION.match(t)) or bool(_REQUEST.match(t))


def log_line(kind: str, text: str):
    """Append-only. Every statement, every supersession. Never rewritten."""
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {kind}: {text.strip()}\n")


def _slug_key(text: str, facts: "dict[str, str]") -> str:
    """Fallback key for a forced remember the model would not format."""
    n = 1
    while f"note {n}" in facts:
        n += 1
    return f"note {n}"


def _apply(key: str, value: str, action: str, verbose: bool):
    """
    Write one fact. If the key already holds a different value this is a
    supersession, whatever the model called it: the new line carries
    '(previously <old>)' and the change is appended to the log (ADR-0044).
    Only one level of 'previously' is kept inline; the log holds the rest.
    """
    facts = read_facts()
    was = facts.get(key)
    if was is not None and _PREVIOUSLY.sub("", was) != value:
        old = _PREVIOUSLY.sub("", was)
        facts[key] = f"{value} (previously {old})"
        log_line("superseded", f"{key}: {old} -> {value}")
        if verbose:
            print(f"        (supersede) {key}: {old}  ->  {value}")
    else:
        facts[key] = value
        if verbose:
            print(f"        ({action}) {key}: {value}")
    write_facts(facts)


def extract(user_text: str, verbose: bool = True):
    """
    The second pass. Order matters:
      1. log the statement verbatim - the safety net for anything missed
      2. questions and requests skip by rule, no model call
      3. an explicit 'remember ...' is always stored, by rule
      4. everything else goes to the model, which picks key and value
    """
    log_line("user", user_text)

    if is_question_or_request(user_text):
        if verbose:
            print("        (skip, rule: question/request)")
        return {"action": "skip", "by": "rule"}

    forced = bool(_REMEMBER.match(user_text))
    statement = _REMEMBER.sub("", user_text, count=1) if forced else user_text

    prompt = (f"CURRENT FACTS\n{facts_block()}\n\n"
              f"NEW STATEMENT\n{statement}")
    if forced:
        prompt += "\n\nThe user explicitly asked for this to be remembered. Do not skip."
    raw = chat(EXTRACT_SYSTEM, prompt, timeout=120)
    raw = re.sub(r"```(?:json)?|```", "", raw).strip()

    try:
        op = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except Exception:
        op = {"action": "unparseable"}

    action = op.get("action")
    key = str(op.get("key", "")).strip().lower()
    value = str(op.get("value", "")).strip()

    if action in ("add", "update") and key and value:
        _apply(key, value, action, verbose)
        return op

    if forced:
        # The model skipped or garbled an explicit request. His word wins.
        key = _slug_key(statement, read_facts())
        _apply(key, statement.strip(), "add, rule: remember", verbose)
        return {"action": "add", "key": key, "value": statement, "by": "rule"}

    if verbose:
        print(f"        ({action}{', unparseable: ' + raw[:60] if action == 'unparseable' else ''})")
    return op


_STOP = {"what", "which", "where", "when", "does", "have", "that", "this",
         "with", "from", "your", "mine", "about", "there", "their", "would",
         "should", "could", "called", "name"}
_DONT_KNOW = re.compile(r"\b(i do not know|i don't know|i dont know|not in (the )?memory)\b", re.I)


def xask_facts(user_text: str) -> str:
    """Answer from the extracted facts only. Measures the extractor."""
    return chat(SYSTEM + "\n\n--- MEMORY FILE ---\n" + facts_block(), user_text)


def search_log(question: str, limit: int = 5) -> str:
    """
    Rung one of the retrieval ladder (ADR-0030): word overlap, no index.
    Only user statements are searched - what he said, verbatim.
    """
    if not os.path.exists(LOG_FILE):
        return ""
    words = {w for w in re.findall(r"[a-z0-9-]+", question.lower())
             if len(w) > 3 and w not in _STOP}
    if not words:
        return ""
    scored = []
    for line in open(LOG_FILE, encoding="utf-8"):
        if "] user: " not in line:
            continue
        body = line.split("] user: ", 1)[1].strip()
        if is_question_or_request(body):
            continue
        hits = sum(1 for w in words if w in body.lower())
        if hits:
            scored.append((hits, body))
    scored.sort(key=lambda x: -x[0])
    return "\n".join(f"- {b}" for _h, b in scored[:limit])


def xask(user_text: str) -> str:
    """
    Facts first. If they cannot answer, grep the log and ask again with what
    he actually said. A missed extraction becomes a retrieval problem rather
    than a lost fact.
    """
    a = xask_facts(user_text)
    if not _DONT_KNOW.search(a):
        return a
    excerpts = search_log(user_text)
    if not excerpts:
        return a
    context = (SYSTEM + "\n\n--- MEMORY FILE ---\n" + facts_block() +
               "\n\n--- LOG EXCERPTS (things the user said, verbatim) ---\n" +
               excerpts)
    return chat(context, user_text)


# ---------------------------------------------------------------- modes
def _seeder(handler, label):
    print(f"seeding {len(FACTS)} facts [{label}]\n")
    for i, fact in enumerate(FACTS, 1):
        print(f"  [{i:>2}/{len(FACTS)}] {fact}")
        handler(fact)
        if i % 4 == 0:
            f = FILLER[(i // 4 - 1) % len(FILLER)]
            print(f"        (filler) {f}")
            handler(f)


def cmd_seed():
    echo = "--echo" in sys.argv
    if echo:
        print("!! --echo: recording assistant replies too. This is the bug.\n")
    _seeder(lambda t: ask(t, echo=echo), "naive, echo=on" if echo else "naive")
    print(f"\ndone. {os.path.getsize(MEM)} bytes -> {MEM}")


def cmd_xseed():
    # Starts clean. Before 28 Sep 2026 xseed added to whatever facts.md held,
    # so a rerun inherited the previous run's mistakes.
    for p in (FACTS_FILE, LOG_FILE):
        if os.path.exists(p):
            os.remove(p)
    _seeder(lambda t: extract(t), "extraction")
    n = len(read_facts())
    print(f"\ndone. {n} facts -> {FACTS_FILE}")
    if n < len(FACTS):
        print(f"  ({len(FACTS) - n} statements were skipped or merged - "
              f"open the file and check whether that was right)")


def _quiz(answerer, source):
    print(f"quizzing against {source}\n")
    hits, misses = 0, []
    for i, (q, key) in enumerate(QUESTIONS, 1):
        a = answerer(q)                 # never recorded - would contaminate
        ok = key.lower() in a.lower()
        hits += ok
        print(f"  [{i:>2}] {'PASS' if ok else 'FAIL'}  {q}")
        print(f"        -> {a[:110]}")
        if not ok:
            misses.append((i, q, a))

    print(f"\n  SCORE: {hits}/{len(QUESTIONS)}   bar is 18")
    if misses:
        print("\n  MISSES - note WHERE in the file these facts sit:")
        for i, q, a in misses:
            print(f"    [{i:>2}] {q}\n         got: {a[:150]}")
        print("\n  Clustered in the MIDDLE -> lost-in-the-middle, needs retrieval.")
        print("  Scattered -> look at what is in the file around each miss first.")
        print("  Numbers and dates failing before names is expected.")


def cmd_quiz():
    _quiz(lambda q: ask(q, record=False), f"{MEM} ({os.path.getsize(MEM)} bytes)")


def cmd_xquiz():
    """
    Two scores, deliberately. Facts-only measures the extractor. With-fallback
    measures the whole design. Reporting only the second would let the log
    hide a bad extractor.
    """
    print(f"quizzing against {FACTS_FILE} ({len(read_facts())} facts) "
          f"+ log fallback {LOG_FILE}\n")
    facts_hits = both_hits = 0
    rescued = []
    for i, (q, key) in enumerate(QUESTIONS, 1):
        a1 = xask_facts(q)
        ok1 = key.lower() in a1.lower()
        a2 = a1
        if not ok1:
            a2 = xask(q)
        ok2 = key.lower() in a2.lower()
        facts_hits += ok1
        both_hits += ok2
        tag = "PASS" if ok1 else ("LOG " if ok2 else "FAIL")
        print(f"  [{i:>2}] {tag}  {q}")
        print(f"        -> {a2[:110]}")
        if ok2 and not ok1:
            rescued.append(i)

    print(f"\n  FACTS ONLY    : {facts_hits}/{len(QUESTIONS)}   (the extractor)")
    print(f"  WITH FALLBACK : {both_hits}/{len(QUESTIONS)}   (the design)   bar is 18")
    if rescued:
        print(f"  rescued by the log: {rescued}")


def _contradict(answerer, writer, label):
    new = "Actually, I renamed my main machine - it's called Fuji now."
    q   = "What is my main machine called?"

    print(f"[{label}]")
    print(f"before : {answerer(q)}\n")
    print(f"stating: {new}")
    writer(new)
    time.sleep(0.5)
    a = answerer(q)
    print(f"after  : {a}\n")

    ok = "fuji" in a.lower() and "sakura" not in a.lower()
    print(f"  {'PASS' if ok else 'FAIL'} - new fact should win cleanly, "
          f"old fact should not be repeated")


def cmd_contradict():
    _contradict(lambda q: ask(q, record=False), lambda t: ask(t), "naive")
    print(f"  (reset with: sed -i '/Fuji/d' {MEM})")


def cmd_xcontradict():
    _contradict(xask, lambda t: extract(t), "extraction")
    print(f"  (the fact line itself should have changed - check {FACTS_FILE})")


def cmd_stats():
    if not os.path.exists(MEM):
        print("no memory file yet")
        return
    n = os.path.getsize(MEM)
    lines = sum(1 for _ in open(MEM, encoding="utf-8"))
    print(f"{MEM}: {n} bytes, {lines} lines, ~{n // 4} tokens")
    print("every turn sends all of it. watch this number - it is why the "
          "naive version stops working.")


def cmd_xstats():
    facts = read_facts()
    if not facts:
        print("no facts file yet")
        return
    n = os.path.getsize(FACTS_FILE)
    print(f"{FACTS_FILE}: {n} bytes, {len(facts)} facts, ~{n // 4} tokens")
    if os.path.exists(LOG_FILE):
        print(f"{LOG_FILE}: {os.path.getsize(LOG_FILE)} bytes, never loaded wholesale")
    print("compare against the naive file. the gap is what extraction bought "
          "you, and it widens with every turn.")


def cmd_chat():
    print(f"chat - memory in {MEM}, ctrl-c to quit\n")
    while True:
        try:
            t = input("you: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return
        if t:
            print(f"her: {ask(t)}\n")


if __name__ == "__main__":
    cmds = {"seed": cmd_seed, "quiz": cmd_quiz, "contradict": cmd_contradict,
            "stats": cmd_stats, "chat": cmd_chat,
            "xseed": cmd_xseed, "xquiz": cmd_xquiz,
            "xcontradict": cmd_xcontradict, "xstats": cmd_xstats}
    mode = sys.argv[1] if len(sys.argv) > 1 else "chat"
    if mode not in cmds:
        print(f"usage: {sys.argv[0]} [{'|'.join(cmds)}] [--echo]")
        sys.exit(1)
    cmds[mode]()