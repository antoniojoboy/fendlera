# ADR-0028 - Subcortical: everything up to text; one judging mind

**Status:** Accepted

**Date:** 2026-09-13

**Context**
Perception needs models (VLM, speech-to-text) but judgement must not fork.

**Decision**
Subcortical does capture, cheap detection, description and appending to the record. Judgement is always Fendlera's. Describers are separate models by mechanical necessity (frames in, text out), not by design choice.

**Consequences**
Test of the boundary: Subcortical runs with no chat model present and keeps filling the record. Three processes, whole apart: Fendlera judges, Subtend knows what he did, Subcortical knows what is happening.
