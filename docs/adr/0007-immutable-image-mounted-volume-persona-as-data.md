# ADR-0007 - Immutable image, mounted volume, persona as data

**Status:** Accepted

**Date:** 2026-09-07

**Context**
An earlier model made the persona a private fork, so having one required being the author.

**Decision**
Ship an immutable image with a default persona. One volume is mounted: `profile/` (personality and directives, read-only to the agent) and `workspace/` (memory vault and files, the agent's only writable surface). On first run an empty `profile/` is seeded with the default persona and never touched again.

**Consequences**
Anyone who pulls the image gets a working agent and can author their own persona. One writable directory, and it does not contain her identity.
