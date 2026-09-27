# ADR-0020 - Reachability is an edge, not an attribute

**Status:** Accepted

**Date:** 2026-09-08

**Context**
Headphones move between nodes.

**Decision**
Which node can reach which sink is a relationship recorded as an edge. Binding is re-resolved at press time.

**Consequences**
Routing is decided when a message fires, not when it was queued. This is not runtime identity re-resolution.
