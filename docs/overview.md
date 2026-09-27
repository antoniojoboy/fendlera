# Project overview

**28 Sep 2026.** The one place to start reading. Detail lives in the decision
records (`docs/adr/`) and the architecture docs (`docs/architecture/`).

## In one paragraph

A personal assistant that runs entirely on hardware you own. It is speech-first,
it watches what is happening (screens, cameras, machine state), and it can be
driven by cheap wearables: a ring press, a headset tap. It is built as three
products that ship together but run whole apart. Desirée is the author's own
instance.

## The three products

| Product | Job | Knows | Repo |
|---|---|---|---|
| **Fendlera** | the harness: model, memory, persona, conversation | judges | [fendlera](https://github.com/antoniojoboy/fendlera) |
| **Subtend** | the periphery: symbols in, reaching you out | what you did | [subtend](https://github.com/antoniojoboy/subtend) |
| **Subcortical** | perception: capture, detect, describe, record | what is happening | inside fendlera until it has code |

- **Fendlera** is the only thing that judges. One mind; everything else feeds it
  or carries for it.
- **Subtend** turns a press into an action in milliseconds with no model in the
  path, and owns every outbound route: speakers at home, headphones out, a buzz
  on the watch.
- **Subcortical** turns the world into text, one file per source, and never
  decides what matters. It runs even with no chat model loaded.

```
 wearables ──► Subtend ──► claims / actions ─┐
                  ▲                            │
                  └──── outbound routing ◄─────┤
                                               ▼
 screens, cameras, ──► Subcortical ──► DVR ──► Fendlera ◄──► you (voice, text)
 telemetry, logs          (describes)          (judges)
```

## Principles that hold everywhere

- **Named tools only, no shell.** Dangerous actions are unrepresentable.
- **No unilateral delete.** Removal is a proposal a person confirms.
- **No model in a gate position.** Deterministic controls decide; models do not
  arbitrate presses, safety or routing.
- **An observation is never an instruction.** Everything perceived or fetched is
  untrusted, stamped with provenance at write time, and can never cause a memory
  write.
- **Perception is ingress; tools are egress.** She can see everything and do
  only what a named tool allows.
- **Significance is judgement, not a threshold.** No configured numbers for what
  matters.
- **A press is a button, never an authorisation.** Trust comes from enrolment,
  never from network origin.

## Where things stand

| Area | State |
|---|---|
| Voice (POC 1) | PASS: 0.15s median to first audio |
| Memory (POC 2) | formal FAIL 17/20, root-caused to the write path; fix applied, **not re-scored** |
| Lookup (POC 3) | built, **not scored** |
| Hands-free conversation (POC 4) | absorbed into POC 5 |
| End-to-end (POC 5) | PASS on all five bars; the platform foundation (ADR-0055) |
| Subtend drivers | black ring, white ring, earbud working; profilers done |
| Platform code (`src/`) | not started |
| Subcortical code | prototype inside POC 5 only |
| No unilateral delete (ADR-0044) | decided, **not built** |

Working configuration: llama3.1:8b-instruct-q8_0 for chat, qwen2.5vl:3b for
description, Whisper small.en, both models resident in 16GB.

## Known limits

- **Tool selection by an 8B model** is the weakest link. It is the model, not the
  architecture.
- **A Bluetooth headset cannot give microphone and buttons at once.** Input
  needs a second radio (the white ring).
- **Switching headset profiles costs about 2.8s.** Per-utterance switching is
  off.
- **Reading a product grid from pixels mis-pairs names and prices.** A page
  reader is the answer, not a bigger vision model.

## Open questions

- How Desirée proposes changes to her own persona: what, when, and how it reaches
  you (ADR-0008).
- The drift probe set: what exactly it tests.
- Confirmation rule for free-text-out tools, pinned until Home Assistant
  (ADR-0046).
- Whether sensitive reads need a second factor beyond voiceprint (ADR-0035).
- Per-conversation headset profile switching: untested (ADR-0053).
- Headset presses in HFP as a new root-only source type on Linux.
- A controlled describer vocabulary.
- Benchmarks: a scenario corpus for measuring harness changes.

## Proposed next

Not yet decided. Re-score POC 2 with the write-path fix, and build ADR-0044
(superseded facts appended to the log book) in the same change, since both touch
the extraction write path.

## Reading order

1. This page.
2. `docs/architecture/fendlera.md`, then `subcortical.md`, then Subtend's
   `docs/architecture/subtend.md`.
3. `docs/architecture/security.md` and `identity-and-access.md`.
4. `docs/adr/README.md` for every decision in order.
5. `docs/results/` for what was measured.
