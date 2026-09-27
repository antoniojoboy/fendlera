# ADR-0017 - Three components

**Status:** Accepted

**Date:** 2026-09-08

**Context**
Capability to act on a machine must live somewhere auditable.

**Decision**
Fendlera (container). Resolver (container, holds no OS capability at all). Node agent (host process, holds session-level grants on its own machine only).

**Consequences**
A compromised resolver cannot type, click or run anything. Grants live on the machine they apply to.
