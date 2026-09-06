# fendlera

A headless harness for building capable offline agents.

Pluggable models, an extensible tool layer, and a memory layer that lives in
plain files. Runs on hardware you own. No cloud dependency, and nothing breaks
when the internet does.

**Status: early development.** Name reserved, nothing usable yet.

## What this is

Fendlera is the platform: runtime, tool registry, memory layer, sandbox
mechanism. It is not an assistant — it is the thing you build one with.

An instance is configured, not forked:

> Fendlera reads its persona and instance configuration from
> `/config/instance.yaml`, mounted at runtime. It ships a default persona and
> starts successfully with no config present.

That contract is the boundary between this repo and any deployment of it.

## Design constraints

These are decided, not open questions.

**Named tools only, no shell.** Every tool is a fixed command with no
user-controlled arguments and structured output. "Is `rm -rf` safe?" is a
question that only exists if there is a shell; with named tools it is
unrepresentable.

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
  src/fendlera/
    config.py          loads persona from /config/instance.yaml
    runtime.py         the tool loop
    memory/
    tools/             one module per named tool
    connectors/
  poc/                 throwaway, excluded from the published package
```

## Licence

MIT.
