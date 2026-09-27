# ADR-0010 - Sources, resolver, sinks

**Status:** Accepted. Envelope extended by 0021

**Date:** 2026-09-07

**Context**
Every device speaks a different protocol.

**Decision**
Sources normalise raw events to `(source_id, symbol, timestamp)` before the resolver sees them. The resolver maps symbol plus context to an action. Sinks execute.

**Consequences**
A source never learns what "next track" means; the resolver never learns what a ring is. Proven across three transports in the device survey.
