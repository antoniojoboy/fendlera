# ADR-0041 - Presence comes from the worn device

**Status:** Accepted

**Date:** 2026-09-13

**Context**
Room-to-room handoff had no trigger.

**Decision**
Presence is inferred from where the enrolled wearable is connected. Rooms are not modelled. Worn detection is not built because the headset powers down when removed.

**Consequences**
No motion sensors, no access-point proximity. An HFP profile going active is a stronger presence signal than connection.
