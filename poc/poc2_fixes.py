#!/usr/bin/env python3
"""
poc2_fixes.py - apply the 28 Sep 2026 code fixes to poc2_memory.py.

Patches CODE only. The test fixtures (STATEMENTS, QUESTIONS, HELD_*, FRESH_*)
are never touched. Every edit must match exactly once, or nothing is written
and the script says which edit failed. A backup is kept as .bak.

    python poc/poc2_fixes.py poc/poc2_memory.py
"""
import shutil
import sys

EDITS = [
    # 1. Tokeniser: split hyphens and apostrophes, so "pick-up" matches
    #    "pick up's" and "five-minute" matches "five minute". The old
    #    [a-z0-9-]+ kept "pick-up" as one token, the log search missed the
    #    Thursday correction, and the answer went back to Wednesday.
    ("tokeniser (question side)",
     'words = {_stem(w) for w in re.findall(r"[a-z0-9-]+", question.lower())',
     'words = {_stem(w) for w in re.findall(r"[a-z0-9]+", question.lower())'),
    ("tokeniser (log side)",
     'tokens = {_stem(t) for t in re.findall(r"[a-z0-9-]+", body.lower())}',
     'tokens = {_stem(t) for t in re.findall(r"[a-z0-9]+", body.lower())}'),

    # 2. Corrections stand, and 3. inference never answers the unmentioned.
    ("evidence rules",
     '''    "When the two sources disagree, the user's own words win, and a later "
    "excerpt wins over an earlier one.\\n"''',
     '''    "When the two sources disagree, the user's own words win, and a later "
    "excerpt wins over an earlier one.\\n"
    "A fact marked '(previously ...)' records a correction the user made. "
    "The corrected value stands unless a LATER excerpt changes it again; an "
    "excerpt that is merely older never overrides it.\\n"
    "Inference extends what was said. It never answers a question about "
    "something that was never mentioned: if who did it, when, or whether it "
    "happened at all was never stated, the answer is I don't know - not yes "
    "and not no.\\n"'''),

    # 4. Tone as meant. General wording; no phrase from any test set.
    ("extraction: tone",
     '''    "If the speaker corrects themselves ('X, no wait, Y'), store only Y.\\n"''',
     '''    "If the speaker corrects themselves ('X, no wait, Y'), store only Y.\\n"
    "TONE is stored as meant, not as said: sarcasm and irony mean the "
    "opposite of their literal words, so store what the speaker actually "
    "thinks.\\n"'''),
]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    out = src
    for name, old, new in EDITS:
        if new in out:
            print(f"  skip    {name} (already applied)")
            continue
        n = out.count(old)
        if n != 1:
            print(f"  FAILED  {name}: expected 1 match, found {n}. Nothing written.")
            return 1
        out = out.replace(old, new)
        print(f"  ok      {name}")
    if out == src:
        print("nothing to change")
        return 0
    compile(out, path, "exec")          # refuse to write a file that won't parse
    shutil.copy(path, path + ".bak")
    open(path, "w", encoding="utf-8").write(out)
    print(f"written {path}  (backup: {path}.bak)")
    return 0


if __name__ == "__main__":
    sys.exit(main())