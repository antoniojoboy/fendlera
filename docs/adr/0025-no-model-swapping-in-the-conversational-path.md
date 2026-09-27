# ADR-0025 - No model swapping in the conversational path

**Status:** Accepted

**Date:** 2026-09-12

**Context**
A swap round-trip is about ten seconds against a 0.15s first-audio result.

**Decision**
Models on the conversational path stay resident. Continuous detection (cheap, CPU) is a separate job from episodic description (a VLM, only when something is being looked at).

**Consequences**
VRAM is the binding constraint on what can be co-resident; see 0051.
