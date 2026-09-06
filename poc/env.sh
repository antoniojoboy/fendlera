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
_sp="$(python -c 'import site; print(site.getsitepackages()[0])' 2>/dev/null)"
if [ -d "$_sp/nvidia" ]; then
    _cudalibs="$(find "$_sp/nvidia" -name 'lib' -type d 2>/dev/null | tr '\n' ':')"
    export LD_LIBRARY_PATH="${_cudalibs}${LD_LIBRARY_PATH}"
fi

# --- audio -----------------------------------------------------------------
export AUDIO_OUT=default        # aplay -> ALSA default -> pipewire -> your sink
unset AUDIO_IN                  # sounddevice default -> pipewire -> your source

# The bluetooth speaker steals both default sink and source when it reconnects.
# Pin the headset if it is present.
if command -v wpctl >/dev/null && command -v pactl >/dev/null; then
    _jabra_sink="$(pactl list short sinks | grep -i jabra | head -1 | cut -f1)"
    _jabra_src="$(pactl list short sources | grep -i jabra | grep -v monitor | head -1 | cut -f1)"
    [ -n "$_jabra_sink" ] && wpctl set-default "$_jabra_sink" 2>/dev/null
    [ -n "$_jabra_src" ]  && wpctl set-default "$_jabra_src"  2>/dev/null
fi

# --- models ----------------------------------------------------------------
export OLLAMA_URL=http://localhost:11434
export OLLAMA_MODEL=llama3.1:8b   # NOT deepseek-r1: those emit <think> blocks
export WHISPER_SIZE=base.en
export WHISPER_DEVICE=cuda        # 'auto' silently picks CPU; be explicit

export PIPER_VOICE=en_GB-jenny_dioco-medium
export PIPER_RATE=22050           # medium/high 22050, low/x_low 16000

# Absolute, so seeding from poc/ and quizzing from the repo root hit the same
# file. Relative paths here cost you a 0/20 and twenty minutes of confusion.
export MEM_FILE="$_here/memory.md"
export FACTS_FILE="$_here/facts.md"

# --- warm ------------------------------------------------------------------
# Without this the first call of a session pays ~3.5s of VRAM load and skews
# every median you record.
curl -s "$OLLAMA_URL/api/generate" \
     -d "{\"model\":\"$OLLAMA_MODEL\",\"keep_alive\":\"1h\"}" >/dev/null 2>&1

# --- check -----------------------------------------------------------------
echo "venv   : $(python -c 'import sys; print(sys.prefix)')"
echo "piper  : $(command -v piper || echo 'NOT FOUND')"
echo "voice  : $PIPER_VOICE @ ${PIPER_RATE}Hz"
echo "model  : $OLLAMA_MODEL"
echo "memory : $MEM_FILE"

if command -v wpctl >/dev/null; then
    echo "sink   : $(wpctl status 2>/dev/null | awk '/Sinks:/,/Sink endpoints:/' \
        | grep '\*' | sed 's/.*[0-9]\+\. //;s/\[vol.*//' | xargs)"
    echo "source : $(wpctl status 2>/dev/null | awk '/Sources:/,/Source endpoints:/' \
        | grep '\*' | sed 's/.*[0-9]\+\. //;s/\[vol.*//' | xargs)"
fi

python - <<'PY' 2>/dev/null || echo "cuda   : check failed"
import ctranslate2
n = ctranslate2.get_cuda_device_count()
print(f"cuda   : {n} device(s), libs on path" if n else "cuda   : NO DEVICES - will fall back to CPU")
PY

if ! curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    echo "!! ollama not responding at $OLLAMA_URL"
fi

unset _here _venv _sp _cudalibs _jabra_sink _jabra_src
