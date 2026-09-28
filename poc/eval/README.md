# poc/eval — evaluation suite for the POC memory

Measures the real `poc/poc2_memory.py`. It never reimplements the system under
test: small switches (`hooks.py`) let it turn features on and off, and every
default reproduces normal behaviour.

## Setup (once)

```bash
python poc/eval/hooks.py poc/poc2_memory.py        # adds the switches; defaults unchanged
pip install pyyaml                                 # if not already in .venv-poc
echo 'poc/eval/results/' >> .gitignore
```

Check Ollama's real context window. It silently cuts off longer prompts:

```bash
docker exec ollama env | grep -i context           # OLLAMA_CONTEXT_LENGTH, if set
```

Put the number in `server_context` in the config (default assumption: 4096).

## Commands

```bash
python poc/eval/eval.py plan  poc/eval/configs/default.yaml   # jobs and a time estimate
python poc/eval/eval.py run   poc/eval/configs/quick.yaml     # smoke test, ~20 min
python poc/eval/eval.py run   poc/eval/configs/default.yaml   # full suite, several hours
python poc/eval/eval.py audit poc/eval/results/<run> --n 30   # sample verdicts for you
python poc/eval/eval.py agree poc/eval/results/<run>/audit.csv
python poc/eval/eval.py noisify poc/eval/datasets/house.yaml  # optional: pre-build speech noise
```

Run from inside `.venv-poc` with `poc/env.sh` sourced.

## What the full suite answers

Each job changes one thing, so every row is attributable.

| job | question it answers |
|---|---|
| `house.baseline` 0 to 1000 | Does accuracy hold as memory grows? (the trend) |
| `house.big_context` | Was the drop caused by the context window cutting memory off? |
| `house.speaker_aware` | Does labelling speakers stop guests, TV and screen text becoming "his words"? |
| `house.no_quote` | What does the quote check actually buy, at small and medium size? |
| `house.noisy` | How much do real transcription errors cost? |
| `house.variance` | How much do scores move run to run? (temperature 0.4, three repeats) |
| `pooh_*.compare_8b` | 8b vs 14b answering on the owner-written sets |

Memories are seeded once per size and cached in `results/cache/seed/`. Jobs
that differ only in answering (like `no_quote` vs `baseline`) reuse the same
memory. Sizes are nested: the 100-distractor memory is exactly the start of
the 1000-distractor one.

## Integrity checks (round 2)

Every summary ends its first table with two checks:

- **Ollama truncation warnings during this run.** It must be 0. It's read from Ollama's own log, because a prompt silently cut from the front loses its instructions. Round 1 had 874 of these, and the harness missed them.
- **Models not fully on the GPU.** If any are listed, the timings in that run aren't comparable.

The suite also runs with `STRICT_PARSE=1`: an extraction reply that isn't a list of operations is recorded as a failed extraction, not silently stored as nothing.

Speech jobs (`input: noisy` or `noisy_vocab`) put the *questions* through the same Piper and Whisper path as the statements. They score names by sound, so "Brennmore" counts for "Brenmoor", while a sound-alike of a *rejected* word still fails. `noisy_vocab` gives Whisper the names from the owner's own statements. Names spoken by guests, the TV or the screen are never used as vocabulary.

## Reading the results

Every run writes `results/run_<time>_<config>/`:

- `summary.md`: tables by job, model and size; by category; and every fabrication listed.
- `results.jsonl`: one line per question with both answers, the quote, verdicts and timings.
- `seed_stats.json`: facts count, extraction time and prompt size per memory size.
- `stores/`: the exact memory each quiz ran against.

**Verdicts.**

- **PASS** means right.
- **MISS** means it said it didn't know, which is safe.
- **FAB** means it said something wrong, which is the dangerous one.

**Columns.**

- **Answerable** is PASS on real questions, excluding traps.
- **Traps** must be answered "I don't know".
- **Facts-only FAB** comes from answering with the extracted facts alone. It measures the extractor.
- **Downgraded** counts answers turned into "I don't know" by the quote check.
- **Over ctx** counts calls whose estimated prompt exceeded `server_context`. **If it's above zero, part of memory was invisible to the model.**
- **VRAM peak** is sampled with `nvidia-smi` during the quiz.

## Datasets

Datasets are YAML files in `datasets/`. Each statement has `text`, `speaker`
and `phase`:

- **speaker** is one of `owner`, `partner`, `guest`, `tv` or `screen`.
- **phase** is `early` or `late`. Late statements (corrections, "forget that") are applied after the distractors, so they are always the newest thing said.

Each question has `q`, `expect`, `category`, and optionally `reject` and `variants`:

- **`expect`** is regex patterns, and `IDK` means "I don't know" is the right answer.
- **`reject`** fails an answer even if it matches.
- **`variants`** are paraphrases, scored separately.

Put `\b` around every short word and number, so `one` can't match `honey`.

## Honest limits

- **Scores are provisional until audited.** The regex scorer has been wrong before. Run `audit` and `agree` after every full run.
- **Temperature 0 is deterministic.** Repeats at 0 measure almost nothing, which is why variance is its own job at 0.4.
- **Distractors are templated.** They're realistic in kind, but not a person's real month of speech.
- **`noisify` is untested on this machine at the time of writing.** It needs Piper and faster-whisper, which `poc/env.sh` sets up.
- **Only you can write a truly blind test.** New datasets in your own words are worth more than more of mine.
