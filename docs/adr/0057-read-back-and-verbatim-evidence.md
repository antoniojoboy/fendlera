# ADR-0057 - Read back what matters; answer with his own words

**Status:** Proposed

**Date:** 2026-09-28

**Context**
POC 2 was re-run against spoken-style tests: long rambling statements with
several facts each, corrections, negations, sarcasm, conditionals, other
people's facts, and questions never answered. Three sets, one written by the
owner himself, 250 questions in all.

What the measurements showed (qwen3:8b for extraction and answering):

- **Extraction alone is unsafe.** Answering from extracted facts only produced
  12 fabrications on the owner's own 75-question set: confident, wrong answers.
- **His verbatim words fix most of it.** Giving every answer the matching log
  lines, numbered in the order he said them, cut that to 1 on the same set.
  Across the three sets, fabrications went to 0, 0 and 1.
- **The remaining errors are born at write time.** Sarcasm stored literally
  ("loves Monday mornings"), a correction missed by retrieval, a vague fact
  overwritten by an unrelated update. No answering rule reliably recovers a
  fact that was wrong from the moment it was stored.

A model alone will not reach 100%. The owner's bar is set by consequence: a
7% error rate over 1000 facts is 70 wrong things in a system that runs the
house.

**Decision**

1. **Every answer about him is grounded in his own words.** The extracted
   facts are an index and a summary. His verbatim statements are the
   evidence, and they win when the two disagree. A recorded correction
   ("previously ...") stands unless something he said later changes it.
2. **What matters is read back when it is stored.** When she stores a fact
   that changes something, or that other decisions will depend on, she says
   it back in one short line: "Got it, pick-up's Thursdays now." He corrects
   it on the spot or lets it stand. The error is caught where it is born,
   while he still remembers what he meant.
3. **Read-back never blocks.** Silence means the fact stands. It is a chance
   to correct, not a confirmation dialogue.
4. **"I don't know" is a correct answer.** Never-stated things get no yes and
   no no. A miss is safe; a fabrication is not.

**Rejected**

- **Tuning the prompt until the test passes.** Each fix written after seeing
  a failure turns that test set into training data. Observed directly: the
  first test reached 30/30 while a fresh set still exposed new failures.
- **Keyword rules for what to store.** Brittle, and each one is a guess about
  speech that real speech breaks.
- **Confirming every fact.** Nobody tolerates that for long, and ignored
  confirmations are worse than none.

**Consequences**
Which facts deserve read-back is her judgement, and that judgement will
sometimes be wrong. The read-back itself is spoken output and goes through the
normal output routing. Accuracy is measured on three held-apart test sets,
with fabrications counted separately from misses. No prompt change is accepted
on the strength of one set.
