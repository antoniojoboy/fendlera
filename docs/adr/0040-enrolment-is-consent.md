# ADR-0040 - Enrolment is consent

**Status:** Accepted

**Date:** 2026-09-13

**Context**
Per-symbol opt-in adds a decision to every button.

**Decision**
Enrolling a device gives all its symbols to the agent; there is no per-button marking. A live claim takes precedence over the static binding for a symbol; an unclaimed press falls through to its binding. Devices are enrolled as fixed (with a place name) or mobile.

**Consequences**
With a headset enrolled, a press during a call goes to the agent, not call control. Accepted.
