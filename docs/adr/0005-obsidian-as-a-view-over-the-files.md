# ADR-0005 - Obsidian as a view over the files

**Status:** Accepted

**Date:** 2026-09-06

**Context**
The memory store is markdown. A human editing surface is the best debugging tool the memory layer will have.

**Decision**
Adopt Obsidian's conventions (YAML frontmatter, wikilinks, tags) as a view over the files. No JavaScript-executing plugins (Templater, Dataview JS) in any vault the agent writes to.

**Consequences**
The dependency is on a file format, not a product. A JS plugin would create a path from attacker-influenced text to code execution on the host. Concurrent edits are a risk if a note is open while the agent rewrites it, so the agent appends rather than rewrites.
