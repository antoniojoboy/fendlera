# ADR-0036 - Subtend owns all outbound routing

**Status:** Accepted

**Date:** 2026-09-13

**Context**
Reaching him and deciding what to say are different jobs.

**Decision**
Everything she emits goes through Subtend. She emits once; Subtend chooses the carrier from what is connected, holds the queue, and never drops a message. Each message records delivered, pending or undelivered. Delivery to the app is the durable baseline.

**Consequences**
"Did you tell me?" always has an answer. A message with nothing reachable is logged, not a failure.
