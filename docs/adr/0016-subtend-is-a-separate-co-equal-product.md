# ADR-0016 - Subtend is a separate, co-equal product

**Status:** Accepted

**Date:** 2026-09-08

**Context**
Sinks may be on other machines entirely. An AGPL Gadgetbridge port must stay away from MIT platform code.

**Decision**
Two products that ship together, on the Ollama and Open WebUI model: Fendlera is the conversation, Subtend is the periphery. Four repos: `fendlera`, `subtend`, `subtend-agent-linux`, `subtend-agent-android`.

**Consequences**
Neither needs the other to run. The agent repos are created when they have code.
