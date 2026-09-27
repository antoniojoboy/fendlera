# ADR-0038 - Timers are first-class; one background process

**Status:** Accepted

**Date:** 2026-09-13

**Context**
Almost every useful thing on a smart device is a timer, and background processes should be few.

**Decision**
Exactly one background process: a ticker that compares the time against a list on disk. Rows are one-off wakes or recurring entries. Timers carry the authority of his word and are never judged. Recurring rows default to a one-year expiry as a backstop. Condition-based wakes come from detection on an open watch, not polling.

**Consequences**
She never counts; she writes a row and is woken by it. She may not delete a row he wrote; she proposes.
