# ADR-0046 - Enumerable versus free-text tool arguments

**Status:** Pinned until Home Assistant integration

**Date:** 2026-09-13

**Context**
Exfiltration needs a field to write data into.

**Decision**
Every tool records whether its arguments are enumerable or free-text. Enumerable tools cannot leak. The confirmation rule for free-text-out tools is decided when the real list exists.

**Consequences**
Reversible: a property of tool definitions, not the architecture. Candidate answer: free-text-out becomes a proposal she confirms.
