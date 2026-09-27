# ADR-0030 - Retrieval ladder

**Status:** Accepted

**Date:** 2026-09-13

**Context**
Each retrieval method fails differently: grep silently and empty, FTS5 silently on synonyms, vectors loudly and wrong.

**Decision**
grep, then FTS5 only when grep measurably fails, then hybrid keyword-plus-vector only when FTS measurably fails. Every index is derived from the markdown and rebuildable.

**Consequences**
"Not in sources" is preferred to a fabrication, which is why grep comes first. Consolidation summarises without embedding-driven clustering.
