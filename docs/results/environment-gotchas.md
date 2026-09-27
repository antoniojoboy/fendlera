# Environment gotchas

Each of these cost roughly an hour. Sakura: Ubuntu 24, Python 3.12, X11,
RTX 5070 Ti 16GB, Ollama in Docker.

## Audio and speech

- Piper reads stdin line by line and produces silence without a trailing
  newline. No error.
- Loading Piper through the CLI reloads the ONNX model per sentence. Load it
  once in-process.
- `use_cuda=True` in Piper succeeds even without the CUDA provider; onnxruntime
  warns and runs on CPU. Check which providers the session actually got.
- CTranslate2 loads cuBLAS on the first `encode()`, so a CUDA Whisper model
  initialises and then dies mid-conversation. Force a dummy transcribe at
  startup with a CPU fallback.
- Whisper echoes `initial_prompt` back on near-silence. Filter by similarity to
  the prompt itself.
- Route everything through PipeWire. Raw ALSA devices report busy because
  PipeWire holds them.
- A Bluetooth speaker can steal both default sink and source on reconnect. Pin
  the intended device in `env.sh`.
- After switching a headset profile, `arecord -D pipewire` still uses the
  default source. Set the default explicitly before judging quality.
- Never abort a PortAudio stream from another thread mid-write. Write in small
  chunks and check a flag.

## Python and CUDA

- `site.getsitepackages()[0]` can return the base interpreter's path inside a
  venv. Use `sysconfig.get_paths()["purelib"]`.
- `nvidia.cublas.lib` is a namespace package with no `__file__`. Glob the `.so`
  files instead of importing.
- The `(.venv)` prompt proves nothing. Check `python -c "import sys; print(sys.prefix)"`.
- Relative memory paths made seeding and quizzing hit different files. Export
  absolute paths.
- `${VAR:-default}` only applies when unset; a stale export from an old shell
  wins silently. Assign, do not default.

## Ollama

- Ollama runs in Docker; there is no host binary. Use the HTTP API.
- The first call of a session pays about 3.5s of model load. Warm it in `env.sh`
  and discard turn one from any median.
- Eviction is driven by VRAM, not by a loaded-model count setting.
- Container environment is fixed at creation; `docker exec ... VAR=x` sets
  nothing.
- Avoid `deepseek-r1` variants: visible thinking blocks break the sentence
  splitter and the transcript.
