# POC 5 - end-to-end integration

**Result: PASS.** All five bars fired. Working configuration:
`VLM_MODEL=qwen2.5vl:3b MODE_SWITCH=0`.

## The bar

Speak through the headset mic, she answers through the headset, a button press
answers a question she asked, the conversation continues by voice, and she can
see the screen. One session, no keyboard.

Why one integration rather than more coverage: if a headset works as a carrier,
any audio carrier will; if the screen works as a source, a camera will. One run
validates the source and sink contract.

## What the bar could not be met with

A Bluetooth headset cannot give microphone and buttons at once (see Subtend's
device survey). The press came from the white ring on a separate radio while the
headset mic was live. That proves two sources, which is closer to the real claim.

## Measured

| | Result |
|---|---|
| Ordinary turns, first audio | 0.4 to 3.7s |
| Screen description | 0.60 to 1.8s (was 2.9s before downscaling to 1280px JPEG q70) |
| Models resident | llama3.1:8b-instruct-q8_0 8.6GB + qwen2.5vl:3b 2.9GB |
| Speech to text | small.en, 0.02 to 0.05s |

## Architecture in the code

- Producer/consumer threads: speech and typing are producers on one queue; a
  router never blocks; one turn worker may. Fixed a bug where an open claim
  stopped all listening.
- The screen is ambient: one current description, refreshed on a perceptual-hash
  change.
- Barge-in is a button press, with cooperative audio cancellation.
- Lookup runs in a quarantined subprocess; results carry source, time and why
  they were fetched. Tool output never reaches fact extraction.
- Zero-argument named tools for GPU, system stats and time.

## Remaining limit: the model

Tool selection by the 8B model: looking up the time, calling yes/no in reply to
a question it was asked, searching for literal phrases, speaking tool machinery
aloud. It trusts a tool result over a fact in its prompt; making the time a tool
fixed the time case. This tests the model, not the architecture.

A 14B model was worse: it narrated tool calls instead of making them.

## Open

- Utterances arriving mid-turn are dropped by design; revisit if turns get faster.
- A page-reading tool (DOM) for comparison shopping.
