# ADR-0033 - No ambient speech transcription

**Status:** Accepted

**Date:** 2026-09-13

**Context**
Always-on transcription records people who did not consent.

**Decision**
Transcription happens in explicit, bounded sessions everyone present can be told about. The audio source class is sound events only, and a DVR-writing audio source is off unless a task opens it.

**Consequences**
The "remember the restaurant someone mentioned" case is lost, accepted. The name match still needs continuous transcription, which is discarded.
