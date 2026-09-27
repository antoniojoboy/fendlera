# ADR-0039 - The phone is a node

**Status:** Accepted. Supersedes 0013

**Date:** 2026-09-13

**Context**
The phone does enrolment and holds capabilities.

**Decision**
The phone offers capabilities and reports what it can reach; the resolver decides. Enrolment happens on the phone but the record lands in the resolver. Nothing runs locally when the resolver is unreachable. Offline presses queue and forward; a press with no link buzzes. Replay is blocked cryptographically (nonce, monotonic counter, node enrolment key). Staleness of an authentic event is her judgement. Events carry the claim ID.

**Consequences**
Offline and broken are distinguishable. A stale but authentic press becomes something she raises, not an action.
