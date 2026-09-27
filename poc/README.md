# POCs

Throwaway. Three questions, answered cheaply, before any platform code exists.

**These are not fendlera.** No shared code, no config layer, no abstractions.
They live here so they follow me between machines, and they get deleted once
they've done their job. If you find yourself refactoring one of these into
something reusable, stop — that's the platform, and it belongs in `src/`.

Excluded from the published package via `[tool.hatch.build.targets.sdist]` in
`pyproject.toml`. Don't remove that.

## Setup

Separate venv from the platform, so POC dependencies never leak into
`pyproject.toml`:

```bash
python3 -m venv .venv-poc
source .venv-poc/bin/activate
python -m pip install -r poc/requirements.txt
source poc/env.sh
```

`env.sh` sets the venv, CUDA library path, audio devices, model, voice and an
absolute `MEM_FILE`, and warms Ollama. Source it every new terminal.

`poc1` also needs `aplay` (`sudo apt install alsa-utils`) and a Piper voice:

```bash
python -m piper.download_voices en_GB-jenny_dioco-medium
```

**The venv prompt lies.** `(.venv-poc)` in your prompt proves nothing — there
were two `.venv-poc` directories on this machine at one point and PEP 668
errors followed for an hour. The only trustworthy check:

```bash
python -c "import sys; print(sys.prefix)"
```

## 1 — Voice · 2–3 hrs

```bash
python poc/poc1_voice.py
```

Enter to start speaking, Enter to stop. Prints `stt / llm-first-token /
FIRST AUDIO / median` after every turn.

The whole POC is `speak_streaming()` — it synthesises on the first complete
sentence while the model is still generating. Don't "simplify" that into
waiting for the full response; that's the difference between ~0.2s and ~6s.

- **PASS** — median first-audio under 2.0s wired, and after ten minutes you
  still want to talk to it.
- **FAIL** — you catch yourself typing instead.

**Result: PASS.** Median 0.15s on GPU, against a 2.0s bar. Breakdown: stt
0.02s, llm-first-token 0.02s, remainder is Piper. Ran 25 unprompted turns.

Two things cost an hour each and are now fixed in the code — read the comments
before changing either:

- Piper reads stdin line-wise and produces **silence** without a trailing
  newline. No error, no output.
- CTranslate2 loads cuBLAS lazily on the first `encode()`, so `device="cuda"`
  initialises fine and then dies mid-conversation. `load_whisper()` forces a
  dummy transcribe at startup with a CPU fallback.

**Not this week:** wake word, always-on listening, barge-in, echo cancellation.

## 2 — Memory · 3 hrs

```bash
python poc2_memory.py seed        # 20 facts, filler in between
python poc2_memory.py stats       # watch the context size grow
python poc2_memory.py quiz        # ask all 20 back, scored
python poc2_memory.py contradict  # change one fact, see which wins
```

Deliberately naive — append-only markdown, whole file into context every turn.
The point is to *find* the failure mode, not avoid it.

- **PASS** — ≥18/20 recalled, contradiction handled cleanly.
- **FAIL** — recalls recent and first few, loses the middle.

**Result: FAIL, but not for the expected reason.** 17, 17, 19 across three runs
at temperature 0.8 — median 17 against a bar of 18.

The misses weren't clustered in the middle, and at 820 tokens lost-in-the-middle
was never plausible. The cause was the **write path**: during `seed` each fact
arrives while the file doesn't yet contain it, so the model treated the
statement as a question, answered "I don't know", and that denial was appended
directly beneath the fact. Seven facts were poisoned. Every quiz failure came
from those seven; none from the other thirteen.

Not a capacity problem. The store was corrupted by its own writes.

Fixed: `seed` no longer records the assistant's reply. `--echo` reproduces the
original behaviour if you want to watch it happen. Temperature is now pinned to
0 so runs are comparable — the 17/17/19 spread straddled the pass bar and made
n=1 misleading.

One genuinely good sign: all three failures were "I do not know." **Zero
fabrications.** That's one line of `SYSTEM` doing real work, and it's the
opposite of what POC 1 did unprompted.

### Extraction path

```bash
python poc2_memory.py xseed
python poc2_memory.py xquiz
python poc2_memory.py xcontradict
python poc2_memory.py xstats
```

A second pass decides what's durable and writes a fact line, **superseding**
rather than appending. Conflicts resolve once at write time rather than being
re-derived on every read while the model is also trying to answer you.

Compare `stats` against `xstats`. The gap is what extraction bought, and it
widens with every turn.

**Not this week:** vector database, embeddings, schema design.

## 4 — Hands-free conversation · 4–5 hrs

```bash
pip install pysilero-vad
python poc4_conversation.py --tune     # see what Whisper hears for the name
python poc4_conversation.py
```

**No wake-word model.** Everything is transcribed continuously; the
conversation opens on a deterministic name match in the text. Affordable only
because STT runs in ~0.02s on this GPU — that's the constraint wake-word models
exist to work around, and it doesn't apply here.

Saying the name opens the window; after that, no name needed. Silence for
`CONVERSATION_WINDOW` seconds (default 25) closes it.

In IDLE everything is transcribed but nothing is sent to the model, logged or
remembered unless the name appears. Set `LOG_IDLE=1` to keep ambient
transcripts — off by default, and think before turning it on.

Run `--tune` first. Whisper renders "Desiree" as desiray / desree / daisy ray
and worse; add what you actually see to `NAME_VARIANTS` rather than lowering
`NAME_RATIO`, which opens the gate on everything.

- **PASS** — all six bars in the module docstring.
- **FAIL** — self-triggering, or the window model turns out to be wrong in
  practice.

Three stores, because they have opposite requirements:

| Store | Loaded | Shape |
|---|---|---|
| `memory/facts.md` | every turn | superseding, small |
| `memory/log/DATE.md` | never | append-only, both speakers |
| `memory/decisions/` | keyword match | ADRs, immutable |

The log keeps the assistant's turns — that's where architectural reasoning
lives. But it isn't resident, so it can't poison recall the way POC 2 did.

**Tunable:** `WAKE_THRESHOLD` (0.5), `CONVERSATION_WINDOW` (25s), `HANG` (0.8s
of silence ends a turn). Expect to tune `HANG` first — too low cuts you off
mid-sentence, too high adds latency to every turn.

**Not this week:** barge-in, echo cancellation, multi-speaker, speaker ID.

## 3 — Lookup · 1–2 hrs

```bash
python poc3_lookup.py "what version of python is current"
python poc3_lookup.py --test
```

This tests the **model**, not the architecture. Search plumbing is solved; what
you're measuring is whether it invents detail the source didn't contain.

- **PASS** — ≥9/10 correct AND zero invented specifics.
- **FAIL** — plausible detail not in the source. Try
  `llama3.1:8b-instruct-q8_0` before concluding anything about the design.

One fabricated number is worse than three "I don't know"s. `NOT IN SOURCES` is
a *correct* answer when the sources lack it.

**Security:** fetched pages are attacker-controlled input. In fendlera proper,
fetching runs quarantined — no tools, no memory, no filesystem — so a hostile
page captures a process that can only return a string. Don't wire this into
anything with write access, not even as a test.

## Results

| POC | Metric | Bar | Actual | Pass |
|---|---|---|---|---|
| 1 | Median end-of-speech → first audio | < 2.0s | 0.15s | ✅ |
| 1 | Still want to talk after 10 min | yes | yes, 25 turns | ✅ |
| 2 | Facts recalled | ≥ 18/20 | 17 median (17/17/19) | ❌ |
| 2 | Contradiction handled | yes | | |
| 2 | Facts recalled, write path fixed | ≥ 18/20 | | |
| 3 | Answers correct | ≥ 9/10 | | |
| 3 | Invented specifics | 0 | | |
| 4 | Name opens conversation | ≥ 8/10 | | |
| 4 | False opens in 30 min | ≤ 1 | | |
| 4 | Follow-up turns without the name | ≥ 5 | | |
| 4 | Self-triggers (hears herself) | 0 | | |
| 4 | Cut off mid-sentence in 10 turns | 0 | | |
| 4 | Median first audio | < 2.0s | | |

Bars were set before building. Don't move them after seeing results.

**Reading the outcome**

- All pass → build it. Start on the platform skeleton and config contract.
- Voice fails → not fatal. Memory without voice is useful; voice without
  memory is a novelty. Drop to text, revisit later.
- Memory fails → the most important result. It scopes the real work.
- Lookup fails → hardware/model-size question, not a design question.
- All fail → genuinely useful information for eight hours. Walk away, or wait
  for better local models.

## Known model behaviour

`llama3.1:8b` at Q4 fabricates confidently under mild pressure. In POC 1 it
claimed to be calling the OpenWeatherMap API, invented a Perth forecast, and
defended the fabricated source across four turns of pushback. It also botched a
cubing T-perm definition.

`llama3.1:8b-instruct-q8_0` is the upgrade path. Avoid the `deepseek-r1`
variants here — they emit visible thinking blocks, which breaks both the TTS
sentence splitter and the memory transcript.