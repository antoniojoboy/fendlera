# ADR-0047 - Capability belongs to the session

**Status:** Accepted

**Date:** 2026-09-13

**Context**
A headset offers four symbols in A2DP and none in HFP.

**Decision**
The node reports current capability on events (PipeWire and BlueZ profile changes on D-Bus); the resolver holds the mapping. Event-driven, never polled.

**Consequences**
Enrolment is neither a property of the device nor the pairing; it is the session.
