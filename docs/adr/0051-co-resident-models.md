# ADR-0051 - Co-resident models

**Status:** Accepted

**Date:** 2026-09-14

**Context**
VRAM, not loaded-model count, decides eviction. q8 chat plus qwen2.5vl:7b evicted; a 14B chat model narrated tool calls instead of making them and was slower.

**Decision**
llama3.1:8b-instruct-q8_0 for chat, qwen2.5vl:3b for description. About 12.8GB, both resident.

**Consequences**
Screen calls fell from 2.8s to 0.6s. Tool selection remains the model's weakness.
