# Security model

The trust model across Fendlera, Subtend and Subcortical.

## Structural rules

- **Named tools only, no shell** (ADR-0001). A dangerous command is
  unrepresentable, not filtered.
- **No unilateral delete** (ADR-0044). Removal is a proposal a person confirms.
- **No model in a gate position.** Guardrail models and classifiers are evaded
  routinely. They may sit alongside deterministic controls, never replace them.
- **One writable directory** (ADR-0007). The agent's identity is not in it.

## Identity and access

- A device is trusted because it was enrolled, never because of where its
  packets came from. The tailnet must not become what loopback was for OpenClaw.
- A reverse proxy erases origin, which is why origin can never grant trust.
- A press is a button, never an authorisation. An unmatched voice is a guest.
- Tools declare the tier needed to call them; grants decide which stores an
  identity reaches; identity comes from the session, never an argument
  (ADR-0035).

## Untrusted content

Fetched pages, screens, camera frames, logs and ambient audio are one class
(ADR-0045). Priming the model is not a defence. Three layers:

1. Provenance stamped at write time, before content reaches memory.
2. Spotlighting at read time: retrieved observations arrive in a labelled block
   that describes the world and never commands.
3. Structure that holds when the first two fail: named tools, no unilateral
   delete, tier-scoped tools. Observations never write memory; only a principal
   speaking through a session can.

Ambient audio is the worst surface: a microphone only has to hear a sentence.
It is off unless a task opens it.

Fetching runs in a quarantined subprocess with no memory, no tools and a hard
timeout. A subprocess is not a sandbox; a deployment adds a network namespace
and read-only mounts.

## Exfiltration

The line is enumerable versus free-text arguments, not local versus external
(ADR-0046). Every tool records which it is. Free-text-out tools (messages,
announcements) get a confirmation rule when Home Assistant integration makes the
real list known.

## Container defaults

The shipped default bind is a security decision. OpenClaw's compose file
defaulted to 0.0.0.0 and tens of thousands of instances were found by scanning.
