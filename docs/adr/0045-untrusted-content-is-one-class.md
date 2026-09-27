# ADR-0045 - Untrusted content is one class

**Status:** Accepted

**Date:** 2026-09-13

**Context**
Fetched pages, screens, camera frames and ambient audio are the same risk. Prompt injection has no model-level fix.

**Decision**
Three layers. Provenance at write time: every stored observation carries its source, observation time, trust level and, for solicited content, why it was fetched. Spotlighting at read time: retrieved observations arrive in a labelled block that describes the world and never commands. Structure underneath: named tools, no unilateral delete, tier-scoped tools. Observations never cause a memory write; only a principal speaking through a session can.

**Consequences**
An observation is never an instruction. A classifier in front of the model was considered and rejected: a model in a gate position fails the same way (see 0001).
