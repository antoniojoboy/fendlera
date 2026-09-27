#!/usr/bin/env python3
"""
poc2_test_fixes.py - fix eight scoring bugs in the POC 2 test fixtures.

Edits QUESTION PATTERNS only, one line each. Every edit must match exactly
once or nothing is written. A backup is kept as .testbak.

    python poc/poc2_test_fixes.py poc/poc2_memory.py

Why each one:
  main 33  'one' matched inside 'honey' - a wrong answer (three) scored PASS
  main 21  'roo' could match inside other words (room, brook)
  main 23  'red' could match inside 'hundred'
  main 44  'eight' could match inside 'weight'
  main 37  rejecting any 'tea' failed a correct 'marsh water, not tea'
  main 95  'by the afternoon' is in the statement, so 'afternoon' is right
  fresh 38 'five minute' missed 'five-minute'
  fresh 40 'ten' could match inside other words (often, written)
"""
import shutil
import sys

EDITS = [
    ("main 33",
     r'''("How many jars of honey were left over?", [r"\b1\b|one"], [])''',
     r'''("How many jars of honey were left over?", [r"\b1\b|\bone\b"], [])'''),
    ("main 21",
     r'''("Who found Tigger in the tree?", [r"roo"], [])''',
     r'''("Who found Tigger in the tree?", [r"\broo\b"], [])'''),
    ("main 23",
     r'''("What color balloon did I actually have?", [r"red"], [r"blue"])''',
     r'''("What color balloon did I actually have?", [r"\bred\b"], [r"blue"])'''),
    ("main 44",
     r'''("How many apples did Tigger squash?", [r"8|eight"], [])''',
     r'''("How many apples did Tigger squash?", [r"\b8\b|\beight\b"], [])'''),
    ("main 37",
     r'''("What does Eeyore drink?", [r"muddy|marsh|water|ditch"], [r"tea"])''',
     r'''("What does Eeyore drink?", [r"muddy|marsh|water|ditch"], [r"\bdrinks tea\b"])'''),
    ("main 95",
     r'''("What time did they find the honeypot?", IDK, [])''',
     r'''("What time did they find the honeypot?", [r"afternoon"] + IDK, [])'''),
    ("fresh 38",
     r'''("What is the time limit Rabbit set for Owl's speech?", [r"5|five minute"], [])''',
     r'''("What is the time limit Rabbit set for Owl's speech?", [r"\b5\b|five.?minute"], [])'''),
    ("fresh 40",
     r'''("How many lanterns is Piglet bringing?", [r"10|ten"], [])''',
     r'''("How many lanterns is Piglet bringing?", [r"\b10\b|\bten\b"], [])'''),
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
    compile(out, path, "exec")
    shutil.copy(path, path + ".testbak")
    open(path, "w", encoding="utf-8").write(out)
    print(f"written {path}  (backup: {path}.testbak)")
    return 0


if __name__ == "__main__":
    sys.exit(main())