# ADR-0050 - Barge-in is the button

**Status:** Accepted

**Date:** 2026-09-13

**Context**
The mic is gated while she speaks so she never hears herself.

**Decision**
Any press while she is speaking cuts her off. Cancellation is cooperative: audio is written in ~50ms chunks with a flag checked between them; stopping touches no device.

**Consequences**
Works in a loud room and cannot self-trigger. Aborting the stream from another thread wedged the audio device and was abandoned.
