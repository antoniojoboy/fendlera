#!/usr/bin/env bash
# poc/env.sh - source this, don't execute it.
#
#   source poc/env.sh
#
# Everything goes through PipeWire deliberately. Never address ALSA hardware
# directly (plughw:3,0 etc) - PipeWire holds those devices exclusively, so you
# get "Device or resource busy", and card numbers shift when you plug things
# in. `wpctl set-default` is the right lever; this just uses whatever it points
# at, which makes this file portable between machines.
#
# CHANGED 13 Sep 2026, and these are behaviour changes, not tidying:
#   * Piper is now VERIFIED, not just configured. A missing voice used to
#     produce silence with no error, because poc code sends piper's stderr to
#     /dev/null. That cost a whole POC 5 run.
#   * CUDA is now checked before you trust any timing. libcublas failing to
#     load silently drops Whisper to CPU.
#   * Sink/source pinning SKIPS if the Shokz are connected, because
#     poc5_desiree.py manages that card's profile itself.
#   * VLM_MODEL added and warmed for poc5's screen tool.

# --- venv ------------------------------------------------------------------
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_venv="$_here/../.venv-poc"

if [ ! -f "$_venv/bin/activate" ]; then
    echo "!! no venv at $_venv"
    echo "   python3 -m venv .venv-poc && source .venv-poc/bin/activate"
    echo "   python -m pip install -r poc/requirements.txt"
    return 1 2>/dev/null || exit 1
fi
source "$_venv/bin/activate"

# --- cuda ------------------------------------------------------------------
# CTranslate2 needs cuBLAS/cuDNN from the pip-installed nvidia wheels. Glob the
# .so files rather than importing nvidia.cublas.lib - those are namespace
# packages with no __file__, so the import trick throws and looks like the
# wheels are missing when they are not.
# site.getsitepackages()[0] can return the BASE interpreter's path from inside
# a venv, which silently finds no nvidia wheels. sysconfig purelib is the
# venv's own site-packages, always.
_sp="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])' 2>/dev/null)"
if [ -d "$_sp/nvidia" ]; then
    _cudalibs="$(find "$_sp/nvidia" -name 'lib' -type d 2>/dev/null | tr '\n' ':')"
    export LD_LIBRARY_PATH="${_cudalibs}${LD_LIBRARY_PATH}"
fi

# --- audio -----------------------------------------------------------------
export AUDIO_OUT=default        # aplay -> ALSA default -> pipewire -> your sink
unset AUDIO_IN                  # sounddevice default -> pipewire -> your source

# EMPTY = discover whichever Bluetooth headset is connected. A hardcoded MAC
# here meant switching from the Shokz to the JLab failed with "are the Shokz
# connected?" - and, like the model vars, `${BT_MAC:-...}` also let a stale
# export from an earlier session win. FENDLERA_* is never exported by this
# file, so it cannot go stale.
export BT_MAC="${FENDLERA_BT_MAC:-}"
export BT_NODE_NAME="${FENDLERA_BT_NODE:-}"

# The Shokz AVRCP node is SILENT while the profile is HFP (confirmed 13 Sep:
# the press leaves as AT+CHUP on the HFP control channel instead). The mic is
# the reason the buttons are gone. So the button source is the WHITE RING,
# which is on a separate BLE radio and is unaffected by the audio profile.
export RING_NODE_NAME="${RING_NODE_NAME:-Anko43559336}"

# Lookup. Leave SEARX_URL empty to use duckduckgo via ddgs.
export SEARX_URL="${SEARX_URL:-}"
export FETCH_N="${FETCH_N:-3}"
export FETCH_TIMEOUT="${FETCH_TIMEOUT:-45}"

# The bluetooth speaker steals both default sink and source when it reconnects.
# Pin the headset if present - BUT NOT when the Shokz are connected, because
# poc5 switches that card to HFP and sets itself as default. Fighting over the
# default device mid-run is how you end up debugging the wrong thing.
_shokz_card="bluez_card.${BT_MAC//:/_}"
if pactl list short cards 2>/dev/null | grep -q "$_shokz_card"; then
    echo "shokz  : connected - leaving audio defaults alone for poc5"
elif command -v wpctl >/dev/null && command -v pactl >/dev/null; then
    _jabra_sink="$(pactl list short sinks | grep -i jabra | head -1 | cut -f1)"
    _jabra_src="$(pactl list short sources | grep -i jabra | grep -v monitor | head -1 | cut -f1)"
    [ -n "$_jabra_sink" ] && wpctl set-default "$_jabra_sink" 2>/dev/null
    [ -n "$_jabra_src" ]  && wpctl set-default "$_jabra_src"  2>/dev/null
fi

# --- models ----------------------------------------------------------------
export OLLAMA_URL=http://localhost:11434
# UPGRADED 13 Sep 2026. llama3.1:8b at Q4 selected tools badly: it called
# look_up for the time (which is in the system prompt), ask_yes_no in reply to
# a yes/no QUESTION, and look_at_screen for "can we try that again". The q8_0
# build is the documented upgrade path from the POC README.
#
# VRAM, and this is a DELIBERATE overcommit. q8 chat (~8.5GB) plus the 7B VLM
# will not co-reside in 16GB, so ollama evicts one to load the other and every
# screen look pays a model load - then the next spoken turn pays another to
# swap back. Chosen anyway, 14 Sept: the 3B describer said "multiple
# applications open" where the 7B said "AMD Ryzen processors, along with their
# prices", and could not then answer which CPU was cheapest. The ambient
# screen was working; the description simply was not specific enough to answer
# from. For a POC measuring whether the DESIGN works, a vague answer is worse
# than a slow one - a wrong answer teaches you nothing about the architecture.
#
# Watch the [screen] timing. If it jumps from ~0.8s to many seconds, that is
# the swap, not the describer. Revisit only if it makes the thing unusable.
# Smaller describer: FENDLERA_VLM=qwen2.5vl:3b source poc/env.sh
# ASSIGNED, not defaulted. ${OLLAMA_MODEL:-...} only applies when the var is
# UNSET, so a value left over from sourcing this file earlier in the same
# shell silently won and the upgrade never happened. Override with FENDLERA_*
# instead, which is never exported by this file and so cannot go stale.
export OLLAMA_MODEL="${FENDLERA_MODEL:-llama3.1:8b-instruct-q8_0}"
export VLM_MODEL="${FENDLERA_VLM:-qwen2.5vl:3b}"     # poc5 screen describer
export MODE_SWITCH="${FENDLERA_MODE_SWITCH:-0}"      # HFP/A2DP switching, experimental, off
export DRIVER_MODEL="${FENDLERA_DRIVER:-qwen3:8b}"     # poc/agent only, not warmed
# small.en, not base.en. base was mishearing badly on the 16kHz mSBC mic -
# "tap" as "turn", "Ryzen 9" as "9 rise and 9". STT measures 0.02-0.04s
# against a 2.0s budget, so there is room to spend and accuracy is the point.
# Go further with FENDLERA_WHISPER=medium.en if small still mishears.
export WHISPER_SIZE="${FENDLERA_WHISPER:-small.en}"
export WHISPER_DEVICE=cuda        # 'auto' silently picks CPU; be explicit

export PIPER_RATE=22050           # medium/high 22050, low/x_low 16000
export ASSISTANT_NAME=Desiree

# Piper needs -m/--model and will NOT default to anything. If PIPER_VOICE is
# empty the poc code omits --model, piper exits with a usage error, and its
# stderr goes to /dev/null - so you get silence and no clue why.
# Resolve a real path here rather than trusting a bare voice name.
_voice_name="${PIPER_VOICE_NAME:-en_GB-jenny_dioco-medium}"
_voice=""
for _c in "$_here/voices/$_voice_name.onnx" \
          "$_here/$_voice_name.onnx" \
          "$PWD/$_voice_name.onnx" \
          "$HOME/.local/share/piper/$_voice_name.onnx"; do
    [ -f "$_c" ] && { _voice="$_c"; break; }
done
if [ -z "$_voice" ]; then
    _voice="$(find "$_here" "$HOME/.local/share/piper" "$PWD" \
              -maxdepth 3 -name "$_voice_name.onnx" 2>/dev/null | head -1)"
fi
export PIPER_VOICE="$_voice"
export PIPER_BIN="${PIPER_BIN:-piper}"

# --- memory paths ----------------------------------------------------------
# Absolute, so seeding from poc/ and quizzing from the repo root hit the same
# file. Relative paths here cost you a 0/20 and twenty minutes of confusion.
export MEM_FILE="$_here/memory.md"
export FACTS_FILE="$_here/facts.md"
export MEM_DIR="$_here/memory"

# --- warm ------------------------------------------------------------------
# Without this the first call of a session pays ~3.5s of VRAM load and skews
# every median you record.
curl -s "$OLLAMA_URL/api/generate" \
     -d "{\"model\":\"$OLLAMA_MODEL\",\"keep_alive\":\"1h\"}" >/dev/null 2>&1

# --- check -----------------------------------------------------------------
echo "venv   : $(python -c 'import sys; print(sys.prefix)')"
echo "model  : $OLLAMA_MODEL"
echo "vlm    : $VLM_MODEL"
_ringcheck="$(python - <<'PYEOF' 2>/dev/null
import glob, os
try:
    from evdev import InputDevice
except ImportError:
    print("evdev not installed"); raise SystemExit
want = os.environ.get("RING_NODE_NAME", "Anko43559336")
hits = []
for p in sorted(glob.glob("/dev/input/event*")):
    try:
        d = InputDevice(p)
    except Exception:
        continue
    if d.name.startswith(want):
        hits.append(f"{p} ({d.name})")
print("  ".join(hits) if hits
      else f"{want} NOT FOUND - shake it to wake it; claims fall back to speech")
PYEOF
)"
echo "ring   : ${_ringcheck:-check skipped}"
echo "memory : $MEM_DIR"

_fail=0

# Piper: prove it makes audio, don't just assert the path exists.
if ! command -v "$PIPER_BIN" >/dev/null; then
    echo "piper  : !! NOT FOUND on PATH"
    _fail=1
elif [ -z "$PIPER_VOICE" ]; then
    echo "piper  : !! NO VOICE FOUND for '$_voice_name'"
    echo "         python -m piper.download_voices $_voice_name"
    echo "         (run it from $_here so this file can find it)"
    _fail=1
elif ! echo "test" | "$PIPER_BIN" --model "$PIPER_VOICE" --output-raw 2>/dev/null \
        | head -c 100 | grep -q .; then
    echo "piper  : !! voice found but produced NO AUDIO"
    echo "         $PIPER_VOICE"
    _fail=1
else
    echo "piper  : OK  $(basename "$PIPER_VOICE") @ ${PIPER_RATE}Hz"
fi

_have="$(curl -sf "$OLLAMA_URL/api/tags" 2>/dev/null | python -c "
import json,sys
try:
    for m in json.load(sys.stdin).get('models', []):
        print(m.get('name',''))
except Exception:
    pass
" 2>/dev/null)"
for _m in "$OLLAMA_MODEL" "$VLM_MODEL"; do
    if echo "$_have" | grep -qx "$_m"; then
        echo "model  : OK  $_m"
    else
        echo "model  : !! NOT PULLED  $_m"
        # Ollama runs in a container here, so there is no `ollama` binary on
        # the host - which is also why the old `ollama list` check reported
        # everything as missing. This check goes over HTTP instead and does
        # not care where ollama lives.
        if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx ollama; then
            echo "         docker exec -it ollama ollama pull $_m"
        else
            echo "         ollama pull $_m   (or: docker exec -it <container> ollama pull $_m)"
        fi
        _fail=1
    fi
done
unset _have

if command -v nvidia-smi >/dev/null; then
    echo "vram   : $(nvidia-smi --query-gpu=memory.used,memory.total \
        --format=csv,noheader 2>/dev/null | head -1)"
    echo "         q8 chat + 7b vlm overcommits 16GB deliberately - expect swapping."
fi

if command -v wpctl >/dev/null; then
    echo "sink   : $(wpctl status 2>/dev/null | awk '/Sinks:/,/Sink endpoints:/' \
        | grep '\*' | sed 's/.*[0-9]\+\. //;s/\[vol.*//' | xargs)"
    echo "source : $(wpctl status 2>/dev/null | awk '/Sources:/,/Source endpoints:/' \
        | grep '\*' | sed 's/.*[0-9]\+\. //;s/\[vol.*//' | xargs)"
fi

# CUDA: a CPU fallback is usable but every timing you record is then wrong.
if python -c "import ctranslate2" 2>/dev/null; then
    _cuda="$(python -c 'import ctranslate2; print(ctranslate2.get_cuda_device_count())' 2>/dev/null)"
    if [ "$_cuda" = "0" ] || [ -z "$_cuda" ]; then
        echo "cuda   : !! NO DEVICES - whisper will run on CPU"
        echo "         libcublas: $(ls "$_sp"/nvidia/cublas/lib/libcublas.so.12 2>/dev/null || echo MISSING)"
        _fail=1
    else
        echo "cuda   : OK  $_cuda device(s), libs on path"
    fi
else
    echo "cuda   : ctranslate2 not importable"
    _fail=1
fi

if ! curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    echo "ollama : !! not responding at $OLLAMA_URL"
    _fail=1
else
    for _m in "$OLLAMA_MODEL" "$VLM_MODEL"; do
        curl -s "$OLLAMA_URL/api/tags" | grep -q "\"${_m%%:*}" \
            || echo "ollama : !! $_m not pulled - ollama pull $_m"
    done
    echo "ollama : OK"
fi

if [ "$_fail" = "1" ]; then
    echo
    echo "!! Something above will fail SILENTLY at runtime. Fix it before you"
    echo "!! record any result - a silent failure looks like a design problem."
fi

# --- input permissions (poc5 only) -----------------------------------------
groups | grep -q '\binput\b' \
    || echo "input  : !! not in the 'input' group - poc5 cannot read buttons"
[ -e /dev/uinput ] || echo "uinput : not present (only needed for --key)"

unset _here _venv _sp _cudalibs _jabra_sink _jabra_src _shokz_card \
      _voice _voice_name _c _fail _cuda _m