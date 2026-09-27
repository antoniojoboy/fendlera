# ADR-0021 - Principals are first-class

**Status:** Accepted. Access model in 0035

**Date:** 2026-09-08

**Context**
Retrofitting multiple people into a single-user contract means a rewrite.

**Decision**
A principal is an opaque UUID generated at enrolment, never a name. `principal_id` is in the event envelope from build step one, hardcoded until speaker verification lands. Devices attribute presses; voiceprints attribute speech. An unmatched voice is `null`: helpful but unprivileged.

**Consequences**
A press is a button, never an authorisation. A name may be learned from conversation; authorisation may not. An unverified voice never gets memory read access.
