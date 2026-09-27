# ADR-0024 - OpenClaw declined as a foundation

**Status:** Accepted

**Date:** 2026-09-12

**Context**
OpenClaw is the closest architectural neighbour: a gateway control plane with nodes holding device capability, WebSocket and Tailscale.

**Decision**
Declined, on auditability. Adopting a Node.js gateway with a large dependency tree would surrender the requirement to justify every line running in the house, to save a fortnight. The licence was clean. The shape is kept: gateway as control plane, nodes hold capability.

**Consequences**
Its CVEs supply trust rules adopted here: network origin is never identity; a reverse proxy erases origin; the container's default bind is a security decision. Integrating as an OpenClaw node type remains a live alternative.
