# ADR-0031 - The looking-back pass

**Status:** Accepted

**Date:** 2026-09-13

**Context**
A stalled download fires no detector: absence of change is the signal.

**Decision**
A pass reads a window of the record and asks what has not been said and what is unresolved. No open-threads store: the pattern lives in the sequence. Mundane observations decay on age; commitments decay only on resolution.

**Consequences**
Trend detection falls out of the same operation. Most passes are silent.
