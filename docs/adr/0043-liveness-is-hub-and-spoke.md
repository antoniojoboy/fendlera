# ADR-0043 - Liveness is hub-and-spoke

**Status:** Accepted

**Date:** 2026-09-13

**Context**
A dead device cannot report that it is dead.

**Decision**
The central node polls enrolled devices on the ticker. Three states: reachable and producing, unreachable, reachable but silent (compared against the source's expected interval).

**Consequences**
A fourth failure, healthy but pointed at the wrong thing, only the describer can see; she says so rather than guessing.
