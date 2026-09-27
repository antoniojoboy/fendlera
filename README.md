# fendlera

A headless harness for building capable offline agents.

Pluggable models, an extensible tool layer, and a memory layer that lives in
plain files. Runs on hardware you own. No cloud dependency, and nothing breaks
when the internet does.

**Status: early development.** Proofs of concept in `poc/`; the platform in
`src/` is not usable yet.

## What this is

Fendlera is the platform: runtime, tool registry, memory layer, sandbox
mechanism. It is not an assistant — it is the thing you build one with.

An instance is configured, not forked. The image is immutable; one volume is
mounted at runtime:

```
mount/
  profile/     personality.yaml, directives.yaml   read-only to the agent
  workspace/   memory vault and files               the agent's only writable surface
```

On first run an empty `profile/` is seeded with the default persona, and never
touched again. One writable directory, and it does not contain her identity.

That contract is the boundary between this repo and any deployment of it.

## Design constraints

These are decided, not open questions. Records are in `docs/adr/`.

**Named tools only, no shell.** Every tool is a fixed command with no
user-controlled arguments and structured output. "Is `rm -rf` safe?" is a
question that only exists if there is a shell; with named tools it is
unrepresentable.

**No unilateral delete.** Removing anything keeps a human in the loop. The agent
proposes; a person confirms. Superseded facts are logged, never silently
destroyed.

**An observation is never an instruction.** Screen, camera, fetched pages and
ambient audio are one class: untrusted content. It enters as something the agent
knows, never as something it has been told to do.

**Provenance at write time.** Every observation is stamped with its source, when
it was observed, its trust level and why it was fetched, before it is stored.
The stamp travels with it on every read.

**Only a person can cause a memory write.** Observations go to the log book.
Facts are extracted only from what a principal said.

**Fetching is quarantined.** Retrieved pages are attacker-controlled input.
Fetching runs in a process with no tools, no memory and no filesystem, so a
hostile page captures something that can only return a string.

**Default-deny egress.** Two networks: the agent on an internal network with no
gateway, and a proxy container with an allowlist.

**Ambient mode has no write tools.** System-initiated work over untrusted input
(logs, feeds, video) observes and notifies. It does not act.

**No LLM as a security boundary.** Guardrail models are defeated routinely; they
belong alongside deterministic controls, never instead of them.

## Layout

```
fendlera/
  pyproject.toml
  src/fendlera/          the platform (planned layout below)
    config.py            loads persona from profile/
    runtime.py           the tool loop
    memory/
    tools/               one module per named tool
    connectors/
  poc/                   throwaway, excluded from the published package
  bench/                 model and vision benchmarks
  docs/
    adr/                 decision records, numbered in decision order
    architecture/        design documents
    results/             benchmark and POC results
    hardware/            device notes
```

## Licence

MIT.