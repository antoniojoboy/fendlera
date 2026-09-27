# ADR-0029 - Control-room memory

**Status:** Accepted

**Date:** 2026-09-13

**Context**
An operator does not keep one book.

**Decision**
Three stores: the DVR (one text file per source, descriptions in time order), the log book (what she authored and his responses), the radio (conversation). Raw images and audio go to a separate blob store. "One memory" means one retrieval, not one store. No pre-merged chronological file; the merged view is assembled at read time.

**Consequences**
The DVR is never resident. Blob retention is a disk-space policy, description retention is a memory policy, and they need not agree. A hand edit is always the truth because nothing is cached.
