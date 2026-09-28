# ADR-0058 - Two kinds of memory: what he told her, and what she observed

**Status:** Accepted

**Date:** 2026-09-28

**Context**
Desirée is an ambient observer. Like a person in the room, she hears and sees
everything: his speech, other people, the TV, the screen, the cameras. A
person's memory includes all of it, and it is answerable later. But a person
also remembers *where* each thing came from: "you told me" is not the same as
"I heard it on the TV". Psychologists call this source memory.

The POC kept one facts file with no sources, and the eval showed what that
costs (house dataset, 28 Sep 2026). With every line filed as his, the
fabrications came straight from other sources:

- "The alarm code is 1234": the TV.
- "The alarm code is 2580": a guest.
- "Our address is 9 Harbour Road, Kelso": text on the screen.

In one run, the screen's address was even written over his real one as a
correction: "We live in Kelso... previously, we lived in Brenmoor."

**Decision**
Memory holds two kinds of knowledge, stored separately, and every item carries
its source.

1. **Facts:** what a principal told her about themselves and their world.
   His facts live under `me/`, and a household member's own facts under
   `people/<name>/`. Facts are his or theirs by authority.
2. **Observations:** everything her senses picked up: guests' speech,
   ambient and TV audio, the screen, the cameras. They are stored under
   `observations/`, time-stamped and tagged with the source. An observation
   is never a fact about anyone.

Both are answerable. An answer from observations always says where it came
from: "The TV mentioned 1234 and Tom said 2580, but you've never told me your
code." That is honest and useful, not a fabrication.

The verbatim log (ADR-0044) keeps every utterance with its speaker, as now.

**Rejected**

- **One store, with the model told to weigh sources.** Measured: the 8b
  extractor, told who was speaking, stored the screen's address anyway and
  filed it as a correction. Authority cannot live in a prompt.
- **Discarding everything not said by him.** It loses what a person in the
  room would remember, and makes "what did Tom say about his cats?"
  unanswerable.

**Consequences**
The eval must accept attributed answers ("the TV said…") as correct, not score
them as fabrications. Observation storage grows fast, so it is governed by
retention (ADR-0061). His facts are not.
