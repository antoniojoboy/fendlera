# ADR-0009 - The LLM is never in the input path

**Status:** Accepted

**Date:** 2026-09-07

**Context**
A press must resolve in milliseconds and deterministically.

**Decision**
The agent configures and queries the resolver. It never arbitrates a press in real time.

**Consequences**
The resolver is unit-testable. Input keeps working with no model loaded.
