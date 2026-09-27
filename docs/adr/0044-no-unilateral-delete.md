# ADR-0044 - No unilateral delete

**Status:** Accepted. Not yet built

**Date:** 2026-09-13

**Context**
Agents acting without consent are what gives harnesses a bad name.

**Decision**
Delete always keeps a human in the loop; cleanup is a proposal answered by one confirm press. Supersession is not exempt: the facts file stays current-only, and every superseded value is also appended to the log book.

**Consequences**
Behaviour change to the POC 2 write path, which today overwrites with no history.
