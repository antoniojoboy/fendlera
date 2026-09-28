# ADR-0060 - Triage at the door: only principals' speech writes facts

**Status:** Accepted

**Date:** 2026-09-28

**Context**
Everything Desirée perceives arrives through Subcortical: microphone, screen,
cameras. ADR-0054 makes perception ingress: observed, never obeyed. ADR-0045
makes everything carry provenance. ADR-0019 attributes every utterance to a
principal.

The eval showed where authority must be enforced. With speaker labels on and
the quote check off, every attack came back: the TV's code, the guest's code,
the screen's address. The extractor had been told the source and told to
ignore it, and did not. The protection that worked (4 fabrications at 72.7%)
came from code: the quote check refusing any answer not grounded in his own
logged words.

**Decision**
Subcortical triages every input by source **before** anything reaches memory,
and **code**, not the model, decides where each input may write:

```
microphone -> speaker ID -+- him / household -> conversation + fact extraction
                          +- guest ----------> conversation + observations
                          +- unknown / media -> observations (ambient, not a turn)
screen / cameras -> Subcortical -> observations
```

- A write path is chosen by the source, in code. His speech can write
  `me/`. A household member's speech can write only `people/<self>/`.
  Nothing else can write facts at all. A path that isn't writable from a
  source cannot be reached by any model output: the same principle as the
  single writable mount (profile read-only, workspace writable).
- **Authority floor:** a lower-authority source can never supersede a
  higher one about the owner. Within the same authority, the newer statement
  wins (recency).
- **Unknown voices default to ambient, never to him.**
- **The quote check and speaker labels stay together** at answer time, as the
  last line of defence if anything is misrouted.

**Rejected**

- **Telling the extractor who spoke and trusting it to comply.** Measured to
  fail.
- **A trust weight that can be outvoted.** Repetition from a low-trust source,
  like a TV advert, would accumulate into belief. Authority is a floor, not a
  weight.

**Consequences**
The door is now the weakest point. If speaker ID labels the TV as him, it
writes into `me/`, and nothing downstream can tell. Speaker verification
(ADR-0019) moves from a nice-to-have to the load-bearing control, and it needs
its own tests. Read-back (ADR-0057) is the backstop for what gets through.
