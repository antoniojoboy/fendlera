# ADR-0035 - Stores and access tiers

**Status:** Accepted

**Date:** 2026-09-13

**Context**
Observations, private statements and guests need different access without classifying data at write time.

**Decision**
Desirée's own store holds what sources observed. Every person has a private store; stores are mutually closed. Tiers: household (own store plus hers), enrolled (own store, general tools), guest (speaks, gets general help, no stores). The tool declares the tier needed to call it; the grant decides which stores a caller's identity reaches. Identity comes from the session, never from an argument.

**Consequences**
The gate is at retrieval and is about who is asking. Open: whether anything genuinely sensitive needs a second factor beyond voiceprint.
