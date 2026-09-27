# ADR-0037 - Only the time is resident; telemetry is a source

**Status:** Accepted

**Date:** 2026-09-13

**Context**
A snapshot of machine state has no trend in it.

**Decision**
The current time stays resident. CPU, GPU and RAM are sampled and appended to a per-machine file like any other source.

**Consequences**
"Climbing for forty minutes" is visible; "81 degrees" alone is not the signal.
