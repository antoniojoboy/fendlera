#!/usr/bin/env python3
"""
add_system_switch.py - let the suite run POC 6 as well as POC 2.

    python poc/eval/add_system_switch.py            # patches poc/eval/eval.py once

What it changes in eval.py, each checked against an exact anchor (it stops
loudly rather than guess if eval.py has moved on):

  1. MEM_SYSTEM chooses the module under test. Default poc2_memory, so every
     existing command behaves exactly as before.
  2. The seed cache key includes the system when it is not poc2_memory, so a
     POC 6 run can never reuse a POC 2 memory (and POC 2's cache stays valid).
  3. Scoring: an answer that attributes a claim to another source AND says he
     never told her ("The TV mentioned 1234, but you've never told me your
     code") is scored as "I don't know" would be: PASS on a trap, MISS on an
     answerable question. Previously it scored FAB. An attributed answer that
     still asserts the value as his stays FAB.

It also lists the speaker labels in the datasets, so PRINCIPALS can be set.
"""
import re
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
p = here / "eval.py"
s = p.read_text()

if "MEM_SYSTEM" in s:
    print("eval.py already has the system switch; nothing to do")
else:
    def need(anchor, count=1):
        n = s.count(anchor)
        if n != count:
            sys.exit(f"STOP: expected {count} of this anchor in eval.py, found {n}:\n  {anchor[:90]}\n"
                     "eval.py has changed since this patch was written. Nothing was modified.")

    a1 = "def load_system(workdir: Path, env: dict):"
    need(a1)
    body_start = s.index(a1)
    body_end = s.index("\ndef ", body_start + 1)
    body = s[body_start:body_end]
    if body.count('"poc2_memory"') < 2:
        sys.exit("STOP: load_system does not import poc2_memory the expected way. Nothing was modified.")
    a2 = 'json.dumps(["harness-v2", '
    need(a2)
    a3 = "\ndef main():"
    need(a3)

    body = body.replace('"poc2_memory"', "SYSTEM")
    s = s[:body_start] + body + s[body_end:]
    s = s.replace(a1, 'SYSTEM = os.environ.get("MEM_SYSTEM", "poc2_memory")   # module under test\n\n\n' + a1, 1)
    s = s.replace(a2, 'json.dumps(["harness-v2", *([SYSTEM] if SYSTEM != "poc2_memory" else []), ', 1)
    s = s.replace(a3, '''
# ------------------------------------------------------------------ attributed answers (ADR-0058)
_ATTRIBUTED_SOURCE = re.compile(r"\\b(the tv|television|on (the|your) screen|a guest|someone|"
                                r"i (heard|saw)|was mentioned|mentioned|overheard)\\b")
_NOT_FROM_HIM = re.compile(r"\\b(you('ve| have)? never (told|said|mentioned)|you haven'?t (told|said)|"
                           r"not from you|you didn'?t tell me|never heard (it|that) from you)\\b")
_base_verdict = verdict


def verdict(answer, q, *args, **kwargs):
    """An observation answered as one is scored like "I don't know"."""
    v = _base_verdict(answer, q, *args, **kwargs)
    a = (answer or "").lower()
    if v == "FAB" and _ATTRIBUTED_SOURCE.search(a) and _NOT_FROM_HIM.search(a):
        return _base_verdict("I don't know.", q, *args, **kwargs)
    return v

''' + a3, 1)
    p.write_text(s)
    print("patched eval.py: MEM_SYSTEM switch, system in the seed key, attributed-answer scoring")

import ast
ast.parse(p.read_text())

labels = set()
for f in sorted((here / "datasets").glob("*.yaml")):
    labels |= set(re.findall(r"speaker:\s*['\"]?([A-Za-z_-]+)", f.read_text()))
print("speaker labels in the datasets:", ", ".join(sorted(labels)) or "(none found)")
print("POC 6 treats PRINCIPALS (default: owner,partner) as people whose words write facts;")
print("every other label is an observation. Set PRINCIPALS if the household label differs.")
