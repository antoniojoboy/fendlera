# ADR-0049 - The screen is ambient, not a tool

**Status:** Accepted. Reconciled with 0026 by 0054

**Date:** 2026-09-13

**Context**
As a tool, the model had to decide to look, and searched the web for what was on the monitor.

**Decision**
A watcher keeps one current description, refreshed only when a perceptual hash changes. Every turn receives it.

**Consequences**
A static screen costs nothing.
