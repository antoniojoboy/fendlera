# Fendlera architecture

The harness. Decisions: ADR-0001 to 0008, 0025, 0026, 0029, 0030, 0044, 0045,
0049 to 0055.

## Position

Fendlera is about continuity and control of the loop. It persists across years,
holds files that are genuinely yours, and runs whether or not anyone's servers
are up. It is deliberately modest: memory, routing, commands. It is not a
reasoning engine. For hard reasoning, use a frontier model; that is correct tool
selection, not defeat.

The honest line on local models: **no reasoning about things it cannot see.** An
8B model reasons poorly about the world but can reason about your files:
retrieval, spotting contradictions, "you said the opposite in June". Narrow and
grounded.

## Distribution (ADR-0007)

An immutable image with a default persona, plus one mounted volume:

```
mount/
  profile/     personality.yaml, directives.yaml   read-only to the agent
  workspace/   memory vault and files               the agent's only writable surface
```

On first run an empty `profile/` is seeded and never touched again. Anyone who
pulls the image gets a working agent; persona is data you author, not a fork you
maintain.

## Persona (ADR-0008)

- `personality.yaml` is characterisation, not configuration: voice, nicknames,
  vocal tics, the persona's own preferences.
- `directives.yaml` is closer to a system prompt: what she pushes back on and how.
- The persona evolves as memory accumulates. Nothing is out of the human's reach,
  including the disagreement directive. The only boundary is that the agent
  cannot write to `profile/`.
- Drift toward agreeableness is a documented risk. The drift probe is a
  how-to-test guide: fork the persona into a throwaway instance with no memory of
  the test, check invariants (given a bad plan, does she still say so), destroy
  it. It tests the floor, not sameness.

Open: the propose-a-diff mechanism for persona changes.

## The loop (ADR-0026, 0055)

One tool-calling loop. No question routers or classifiers. Her own prose is
never fed back in as evidence.

Built from `poc/poc5_desiree.py`:

- **Producers and a router.** Speech (VAD then Whisper) and typing are producers
  on one queue. A router never blocks; one turn worker may. Typing skips the name
  gate because typing is already addressing her.
- **The screen is ambient** (ADR-0049). One current description every turn,
  refreshed on a perceptual-hash change.
- **Named tools**, several with zero arguments so there is no field an injection
  can write into: look at the screen now, look something up, ask a yes/no
  question (opens a Subtend claim), GPU stats, system stats, time.
- **Preambles** before slow tools. Fifteen seconds of silence is
  indistinguishable from a crash.
- **A model trusts a tool result over a prompt fact.** If it ignores a fact in
  its prompt, make the fact a tool.

## Voice

- **Streaming speech.** Synthesis starts on the first complete sentence while the
  model is still generating: the difference between ~0.2s and ~6s.
- **No wake-word model** (ADR-0004). Continuous transcription with a
  deterministic name match. Being named is not being addressed (ADR-0034).
- **Mic gate, not echo cancellation.** Frames are dropped while she speaks.
- **Barge-in is the button** (ADR-0050), with cooperative cancellation.
- Piper loaded once in-process; Whisper small.en.

## Memory (ADR-0002, 0003, 0029, 0030, 0044)

**Write-time extraction.** A second pass reads each finished turn and emits one
operation (add, update, skip), applied deterministically in code. The model
decides what; the code decides how. Conflicts resolve once, at write time.

A deterministic pre-filter keeps questions, requests and deictic phrases ("the
stuff on my screen") away from extraction.

**Stores:**

| Store | Loaded | Shape |
|---|---|---|
| facts | every turn | current only, superseding, small |
| log book | never wholesale | append-only, both speakers, her own turns marked |
| decisions | on keyword match | ADRs, immutable |
| DVR | never; retrieved | Subcortical's per-source records |

**Supersession** will append the old value to the log book (ADR-0044, not yet
built). Today the old value is overwritten.

**Retrieval:** grep, then FTS5, then hybrid, climbing only on measured failure.
Every index is derived from the markdown and rebuildable.

Obsidian is a view over the files. No JavaScript plugins in any vault she writes
to (ADR-0005).

## Models (ADR-0025, 0051, 0052)

| Role | Model | VRAM |
|---|---|---|
| chat and tools | llama3.1:8b-instruct-q8_0 | ~8.6GB |
| describer | qwen2.5vl:3b | ~2.9GB |
| speech to text | Whisper small.en | ~0.5GB |

Both Ollama models stay resident; VRAM, not a loaded-model count, decides
eviction. No model swapping on the conversational path. A 14B chat model was
worse: it narrated tool calls instead of making them.

Models are referenced by endpoint, never bundled. The model is the cheap,
swappable part.

## Lookup

Fetching runs in a quarantined subprocess: no memory, no tools, a hard timeout.
Results carry source, time and why they were fetched, and never reach fact
extraction. Ad-redirect URLs are dropped before fetching.

## Competitive position

Occupied, so not led with: local pluggable headless harnesses, markdown-as-truth
memory, deny-first tools, self-editing persona, ambient sensing, offline voice
pipelines. Home Assistant and Wyoming are integrations, not things to rebuild.

Still open, and where Fendlera competes:

- input as a first-class plural (voice, gesture, screen, camera through one
  context into one memory);
- wearable input resolved by context;
- governed persona evolution with replay;
- identity outside the writable surface.

OpenClaw is the closest neighbour and was declined as a foundation on
auditability (ADR-0024).
