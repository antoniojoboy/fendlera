#!/usr/bin/env python3
"""
make_poc6_desiree.py - build poc/poc6_desiree.py from poc/poc5_desiree.py.

    python poc/make_poc6_desiree.py

POC 5 is left untouched. The new file is POC 5 with:

  1. POC 6 MEMORY in place of the single facts.md. Files are the truth,
     code routes, only his words write facts (ADR-0058, 0060-0064).
  2. A REAL CONVERSATION:
     - every turn sees what she remembers that bears on it (recall), and the
       last few exchanges, so "it" and "that" mean something;
     - she files AFTER replying, in the background, the way Claude's memory
       works, and says any read-back ("New person: Noor, your partner.") at
       the next quiet moment;
     - her own replies are logged but never searched, so she can never
       quote her own earlier guess back as evidence (the POC 2 poisoning).
  3. OBSERVATIONS: the ambient screen and web lookups are stored as
     observations, so "what was on my screen earlier" is answerable and
     always attributed, never filed as his fact.
  4. ONE MODEL for talking and for memory, so nothing swaps in the
     conversational path (ADR-0025). qwen3 thinking is switched off.

Every edit is checked against an exact anchor. If poc5_desiree.py has moved
on, this stops and says which anchor, and writes nothing.
"""
import ast
import re
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
src = here / "poc5_desiree.py"
dst = here / "poc6_desiree.py"
s = src.read_text(encoding="utf-8")


def stop(what):
    sys.exit(f"STOP: {what}\npoc5_desiree.py has changed since this generator was written. "
             "Nothing was written.")


def rep(old, new, count=1):
    global s
    n = s.count(old)
    if n != count:
        stop(f"expected {count} of this anchor, found {n}:\n  {old[:100]!r}")
    s = s.replace(old, new)


# ---- 0. header
rep('POC 5 - End-to-end integration\n',
    'POC 6 Desiree - POC 5 with POC 6 memory and a real conversation.\n'
    'GENERATED from poc5_desiree.py by make_poc6_desiree.py. Edit the generator,\n'
    'or accept that this file is now the one you maintain.\n\n'
    'Original POC 5 header follows.\n\n'
    'POC 5 - End-to-end integration\n')

# ---- 1. imports
rep('\nimport requests\n',
    '\nimport requests\n\nimport poc6_memory as mem\nfrom pathlib import Path as _Path\n')

# ---- 2. memory rules in the system prompt
rep(r'''        "If a fact was later changed, the most recent statement wins.\n\n"''',
    r'''        "MEMORY. Everything you know about him, the people in his life, his "
        "projects, and what others have said comes ONLY from the WHAT YOU "
        "REMEMBER block. HIS WORDS are the evidence, and the later line wins. "
        "OBSERVATIONS are what other people, the TV, the screen or the web "
        "said: never state them as his facts, say where they came from. If "
        "it is not in the block, say you don't know rather than guessing. You "
        "remember things he tells you automatically; never say you cannot "
        "remember or that you have no memory.\n\n"''')

# ---- 3. qwen3 must not think out loud: it would be spoken
rep('json={"model": OLLAMA_MODEL, "stream": True,',
    'json={**_think(), "model": OLLAMA_MODEL, "stream": True,')
rep('json={"model": OLLAMA_MODEL, "stream": False,',
    'json={**_think(), "model": OLLAMA_MODEL, "stream": False,')

# ---- 4. the old single-file extract() is replaced by POC 6
a = s.find("def extract(user_text: str):")
m = s.find("# Subcortical - sources.")
if a < 0 or m < 0:
    stop("could not find extract() or the Subcortical section after it")
b = s.rfind("# ====", 0, m)
if b < a:
    stop("section divider before Subcortical not found after extract()")
s = s[:a] + '''HISTORY_TURNS = int(os.environ.get("HISTORY_TURNS", "4"))
HISTORY: "collections.deque" = collections.deque(maxlen=HISTORY_TURNS)
PENDING_READBACK: list = []


def _think() -> dict:
    """qwen3 and deepseek reason in <think> blocks, which TTS would read aloud."""
    return {"think": False} if OLLAMA_MODEL.startswith(("qwen3", "deepseek")) else {}


def _observe(source: str, text: str):
    """Perception must never break because memory did."""
    try:
        mem.observe(source, text)
    except Exception as exc:
        say(f"  [memory] observe failed: {exc}")


def extract(user_text: str):
    """
    POC 6. Runs AFTER she has replied, on its own thread. Only what the
    principal said reaches it; tool output and the screen go to observations.
    Read-backs are queued and spoken at the next quiet moment (ADR-0057).
    """
    try:
        r = mem.extract(user_text, verbose=False, speaker=mem.OWNER)
    except Exception as exc:
        say(f"  [memory] extract failed: {type(exc).__name__}: {exc}")
        return
    if r.get("touched"):
        say(f"  [memory] filed in {', '.join(r['touched'])}")
    for t in r.get("inbox", []):
        say(f"  [memory] inbox: {t}")
    for t in r.get("readbacks", []):
        say(f"  [memory] read-back: {t}")
        PENDING_READBACK.append(t)


''' + s[b:]

# ---- 5. read-backs are spoken when she is idle
rep('''                if (state["mode"] == "OPEN" and not state["busy"]''',
    '''                if (PENDING_READBACK and not state["busy"]
                        and not speaking.is_set()):
                    line = " ".join(PENDING_READBACK)
                    PENDING_READBACK.clear()
                    threading.Thread(target=speak, args=(line,),
                                     daemon=True).start()
                if (state["mode"] == "OPEN" and not state["busy"]''')

# ---- 6. every turn sees what she remembers, not the whole facts file
rep(r'''context = system_prompt() + "\n\n--- FACTS ---\n" + facts_block()''',
    r'''try:
                recall, rtrace = mem.recall(query)
            except Exception as exc:          # memory failing must not end the turn
                say(f"  [memory] recall failed: {type(exc).__name__}: {exc}")
                recall, rtrace = "(memory unavailable this turn)", {"files": [], "lines": 0}
            say(f"  [memory] read {', '.join(rtrace['files']) or 'no files'}, "
                f"{rtrace['lines']} lines")
            context = system_prompt() + "\n\n--- WHAT YOU REMEMBER ---\n" + recall''')

# ---- 7. and the last few exchanges
rep('''            messages = [{"role": "system", "content": context},
                        {"role": "user", "content": query}]''',
    '''            messages = [{"role": "system", "content": context}]
            for _u, _a in HISTORY:
                messages += [{"role": "user", "content": _u},
                             {"role": "assistant", "content": _a}]
            messages.append({"role": "user", "content": query})''')

# ---- 8. her reply: remembered for the conversation, logged, never evidence
rep('''                append_log("assistant", reply)''',
    '''                append_log("assistant", reply)
                HISTORY.append((query, reply.strip()))
                try:
                    mem.note_own(reply)
                except Exception as exc:
                    say(f"  [memory] could not log reply: {exc}")''')

# ---- 9. the screen and the web are observations
s, n = re.subn(r'^(\s*)append_log\("screen", desc\)$',
               r'\1append_log("screen", desc)\n\1_observe("screen", desc)', s, flags=re.M)
if n != 2:
    stop(f"expected 2 screen log lines, found {n}")
s, n = re.subn(r'''^(\s*)append_log\("lookup", f"\[\{i\}\] \{s\['url'\]\}  \(query: \{query\}\)"\)$''',
               r'''\1append_log("lookup", f"[{i}] {s['url']}  (query: {query})")
\1_observe("web", f"{s['title']} ({s['url']}): {s['text'][:600]}")''', s, flags=re.M)
if n != 1:
    stop(f"expected 1 lookup log line, found {n}")

# ---- 10. memory set up at start: its own folder, owner only, one model
rep('\n    _ensure_dirs()\n',
    '''
    _ensure_dirs()
    mem.ROOT = _Path(os.environ.get("MEM6_DIR")
                     or os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory6"))
    # Only he is a principal until someone is enrolled (ADR-0040). Everyone
    # and everything else is an observation.
    mem.PRINCIPALS[:] = ["owner"]
    mem.OWNER = "owner"
    # One model for talking and memory, so nothing swaps mid-conversation.
    for _k in ("EXTRACT_MODEL", "SELECT_MODEL", "ANSWER_MODEL"):
        setattr(mem, _k, os.environ.get(f"MEM_{_k}") or OLLAMA_MODEL)
    say(f"  [memory] {mem.ROOT}  (model {mem.EXTRACT_MODEL})")
''')

try:
    ast.parse(s)
except SyntaxError as exc:
    stop(f"the result does not parse: {exc}")
dst.write_text(s, encoding="utf-8")
print(f"wrote {dst.relative_to(here.parent)}  ({len(s.splitlines())} lines). "
      f"{src.name} is unchanged.")
