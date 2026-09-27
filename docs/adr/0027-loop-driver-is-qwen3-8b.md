# ADR-0027 - Loop driver is qwen3:8b

**Status:** Superseded by 0051 and 0055

**Date:** 2026-09-13

**Context**
A tool-selection smoke test scored qwen3:8b 19/20, llama3.1:8b 16/20, llama3-groq-tool-use 9/20.

**Decision**
qwen3:8b drives the loop.

**Consequences**
The platform foundation is `poc5_desiree`, which runs llama3.1:8b-instruct-q8_0. The smoke test result stands as data.
