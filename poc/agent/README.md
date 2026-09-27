# Desiree — clean set, 13 Sep 2026

Read `desiree-reset-design.pdf` first. It is the spec; these files are the
parts of it that exist so far. Nothing here is a router or a prompt rule.

| file | role | build step | verified by |
|---|---|---|---|
| `selftest.py` | exercises every deterministic part, no hardware | run first | itself — 86 checks |
| `tool_smoke.py` | picks the loop-driver model by measurement | 0 (done: qwen3:8b) | harness self-tested against scripted responses |
| `windows.py` | real windows from the WM: app, role, rect, focus, occlusion | 1 | selftest + your eyes |
| `screenread.py` | capture; per-window OCR; survey; spec pairs; per-window exclusion | 1 | selftest + your eyes |
| `recall.py` | episodes (merged, searchable) + standing interests (with price ceilings) | 2 / 6 | selftest |
| `agent.py` | the loop: qwen3 driving seven tools with provenance; text in/out | 2 | selftest (scripted model + stubbed tools) + your eyes |
| `research.py` | map-reduce web lookup, quote-verified, reconciled in code | 2 | selftest on the pure parts |
| `watcher.py` | always-on settle-based sampling, per-window exclusion, redaction | 4 | selftest on redaction and change detection |

Removed from the previous set, deliberately: every poc5 variant, catalogue.py,
observations.py, all five scoring harnesses, preflight.sh, vram_probe.py.
Voice (persistent piper pipe, GPU whisper, speculative capture) is lifted
from poc5_screen_v3 at step 3 — not before.

## Step 1: closed 13 Sep

## Step 2 gate, now
    sudo apt install -y wmctrl x11-utils xdotool tesseract-ocr
    pip install mss pillow numpy
    python3 selftest.py            # must say: all self-tests passed
    python3 agent.py --trace       # REPL; --trace shows every tool call and result

Ten questions, judged by eye. Suggested set:
  1. what's on my screen                     -> read_screen
  2. what does the browser say               -> read_window
  3. what does my screen look like           -> describe_screen
  4. is that graphics card white or black    -> describe_window
  5. what's the capital of peru              -> no tool
  6. what's the current price of an rtx 5090 in australia   -> research
  7. keep an eye out for a 5080 under 1500   -> remember
  8. do you remember the PLE page            -> search_memory (after 1 or 2)
  9. what's 15% of 240                       -> no tool
 10. which part in this build is the most expensive         -> read -> research

Pass = correct tool(s), answers match what you can see, every fact says
where it came from, and no number is stated that no tool returned.