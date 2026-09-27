# ADR-0055 - poc5_desiree is the platform foundation

**Status:** Accepted. Supersedes 0027

**Date:** 2026-09-28

**Context**
Two unmerged lines existed: `poc5_desiree.py` (passed all five integration bars) and `poc/agent/` (tool-driven, text only).

**Decision**
Build the platform from `poc5_desiree.py`. `poc/agent/` stays as reference.

**Consequences**
The working configuration is VLM qwen2.5vl:3b, MODE_SWITCH=0.
