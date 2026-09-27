# ADR-0008 - Persona: personality and directives; it evolves; the floor is customisable

**Status:** Accepted. Overrides the 6 Sep state-of-play document, which placed the disagreement floor in the harness

**Date:** 2026-09-07

**Context**
Persona could be configuration (role, model, tools) or characterisation. It could be fixed or allowed to grow.

**Decision**
Two files: `personality.yaml` (characterisation: voice, nicknames, tics, the persona's own preferences) and `directives.yaml` (what to push back on). The persona evolves as memory accumulates. Nothing is out of the human's reach, including the disagreement directive; the only boundary is that the agent cannot write to `profile/`.

**Consequences**
Drift toward agreeableness is a documented risk, so a drift probe exists as a how-to-test guide in the docs rather than shipped tooling. Open: how she proposes changes to her own persona, what she may propose, when, and how a proposal reaches the human.
