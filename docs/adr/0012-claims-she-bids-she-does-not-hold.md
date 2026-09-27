# ADR-0012 - Claims: she bids, she does not hold

**Status:** Accepted. Extended by 0040 and 0048

**Date:** 2026-09-07

**Context**
One physical input, two consumers: the focused application and an agent asking a question.

**Decision**
When she asks a question expecting a press, she opens a time-bounded claim. The resolver checks claims before other context. Unanswered claims do not expire silently: she follows up, so the resolver reports claim outcomes back. A summon press pre-empts an open claim.

**Consequences**
She announces a gesture only when the available carriers cannot express the answer space.
