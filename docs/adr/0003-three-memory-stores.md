# ADR-0003 - Three memory stores

**Status:** Accepted. Refined by 0029

**Date:** 2026-09-06

**Context**
POC 2 showed facts and transcripts have opposite requirements. Facts must be small and resident; the transcript holds the assistant's reasoning, which is where architectural decisions live, and must be kept.

**Decision**
- `facts.md`: resident, loaded every turn, superseding, small.
- `log/DATE.md`: append-only, both speakers, never loaded wholesale.
- `decisions/`: ADRs, retrieved by keyword match, never resident.

**Consequences**
The log can keep the assistant's turns safely because it never enters context. Only extracted facts are resident, and extraction emits `skip` for non-facts, so "I don't know" can never be filed as a belief. Anything in `decisions/` reaches the model on a keyword match, so that directory is trusted input by construction.
