#!/usr/bin/env python3
"""
POC 1 - Voice
Question: is local voice fast enough and good enough that you'd rather talk than type?

    source poc/env.sh
    python poc/poc1_voice.py

THE THING THAT MATTERS: speak_streaming() starts synthesising on the first
complete sentence while the LLM is still generating. Do not "simplify" that
into waiting for the full response - it is the entire point of the POC. It is
the difference between ~0.2s and ~6s to first audio.

PASS: median t0->t3 under 2.0s wired, and after 10 minutes you still want to
      talk to it.
FAIL: you catch yourself typing instead.

RESULT: PASS. Median 0.15s on GPU. See poc/README.md.
"""

import os
import re
import sys
import time
import json
import queue
import subprocess
import threading

import numpy as np
import soxr
import sounddevice as sd
import requests
from faster_whisper import WhisperModel

# ---------------------------------------------------------------- config
OLLAMA_URL     = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL   = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
WHISPER_SIZE   = os.environ.get("WHISPER_SIZE", "base.en")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "auto")
PIPER_BIN      = os.environ.get("PIPER_BIN", "piper")
PIPER_VOICE    = os.environ.get("PIPER_VOICE", "")
PIPER_RATE     = int(os.environ.get("PIPER_RATE", "22050"))

# Device names live here, never inline. null/None = system default.
INPUT_DEVICE  = os.environ.get("AUDIO_IN") or None
OUTPUT_DEVICE = os.environ.get("AUDIO_OUT") or None

SYSTEM_PROMPT = (
    "You are a concise voice assistant. Answer in at most three short "
    "sentences. Never use lists, markdown, or emoji - your words are spoken "
    "aloud, not read. If you do not know something, say so plainly rather "
    "than guessing."
)

WHISPER_RATE = 16000          # what whisper wants, always


# ---------------------------------------------------------------- capture
def device_rate(device) -> int:
    """Never hardcode a sample rate - ask the device what it runs at."""
    try:
        info = sd.query_devices(device, "input")
        return int(info["default_samplerate"])
    except Exception:
        return 48000


def record_until_enter(device=INPUT_DEVICE) -> np.ndarray:
    """Press Enter to start, Enter again to stop. Returns float32 @ 16 kHz."""
    rate = device_rate(device)
    frames: list[np.ndarray] = []
    q: "queue.Queue[np.ndarray]" = queue.Queue()

    def cb(indata, _frames, _t, status):
        if status:
            print(f"  [audio] {status}", file=sys.stderr)
        q.put(indata.copy())

    input("press ENTER to speak...")
    stream = sd.InputStream(samplerate=rate, channels=1,
                            dtype="float32", device=device, callback=cb)
    with stream:
        stopper = threading.Thread(target=input, args=("",), daemon=True)
        stopper.start()
        print("  recording... ENTER to stop")
        while stopper.is_alive():
            try:
                frames.append(q.get(timeout=0.1))
            except queue.Empty:
                pass

    while not q.empty():
        frames.append(q.get())

    if not frames:
        return np.zeros(0, dtype=np.float32)

    audio = np.concatenate(frames, axis=0).flatten()
    if rate != WHISPER_RATE:
        audio = soxr.resample(audio, rate, WHISPER_RATE)
    return audio.astype(np.float32)


# ---------------------------------------------------------------- speak
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def piper_play(text: str, out_device=OUTPUT_DEVICE):
    """One sentence -> piper -> aplay. Blocking, raw PCM, no temp files."""
    text = text.strip()
    if not text:
        return
    cmd = [PIPER_BIN, "--output-raw"]
    if PIPER_VOICE:
        cmd += ["--model", PIPER_VOICE]

    aplay = ["aplay", "-q", "-r", str(PIPER_RATE), "-f", "S16_LE", "-t", "raw", "-"]
    if out_device:
        aplay += ["-D", out_device]

    piper = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL)
    player = subprocess.Popen(aplay, stdin=piper.stdout, stderr=subprocess.DEVNULL)
    piper.stdout.close()
    # piper reads stdin line-wise and produces NOTHING without the trailing
    # newline. Silent failure, no error message. Cost an hour to find.
    piper.stdin.write(text.encode() + b"\n")
    piper.stdin.close()
    piper.wait()
    player.wait()


def speak_streaming(token_iter, on_first_audio):
    """
    THE TRICK. Buffer tokens, flush on each sentence boundary, synthesise that
    sentence while the model keeps generating the next one. Playback is queued
    on a worker so generation never blocks on audio.
    """
    q: "queue.Queue[str | None]" = queue.Queue()
    fired = threading.Event()

    def worker():
        while True:
            sentence = q.get()
            if sentence is None:
                return
            if not fired.is_set():
                fired.set()
                on_first_audio()          # t3
            piper_play(sentence)

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    buf, full = "", ""
    for tok in token_iter:
        buf += tok
        full += tok
        parts = _SENTENCE_END.split(buf)
        while len(parts) > 1:
            q.put(parts.pop(0))
            buf = _SENTENCE_END.split(buf, maxsplit=1)[1]
            parts = _SENTENCE_END.split(buf)
    if buf.strip():
        q.put(buf)
    q.put(None)
    t.join()
    return full


# ---------------------------------------------------------------- llm
def ollama_stream(messages):
    r = requests.post(f"{OLLAMA_URL}/api/chat",
                      json={"model": OLLAMA_MODEL, "messages": messages,
                            "stream": True},
                      stream=True, timeout=120)
    r.raise_for_status()
    for line in r.iter_lines():
        if not line:
            continue
        chunk = json.loads(line)
        tok = chunk.get("message", {}).get("content", "")
        if tok:
            yield tok


# ---------------------------------------------------------------- stt init
def load_whisper():
    """
    CTranslate2 loads cuBLAS lazily on the first encode(), not at construction.
    So device='cuda' happily initialises and then dies mid-conversation if the
    libs aren't on LD_LIBRARY_PATH. Force one dummy transcribe here so a broken
    CUDA setup fails now, loudly, with a CPU fallback - not twenty turns in.
    """
    silence = np.zeros(WHISPER_RATE // 2, dtype=np.float32)
    try:
        print(f"loading whisper ({WHISPER_SIZE}, {WHISPER_DEVICE})...")
        m = WhisperModel(WHISPER_SIZE, device=WHISPER_DEVICE, compute_type="auto")
        list(m.transcribe(silence, language="en", beam_size=1)[0])
        return m
    except Exception as e:
        if WHISPER_DEVICE == "cpu":
            raise
        print(f"  !! {WHISPER_DEVICE} failed ({type(e).__name__}: {e})")
        print("  falling back to CPU - expect ~0.2s of STT instead of ~0.02s")
        m = WhisperModel(WHISPER_SIZE, device="cpu", compute_type="auto")
        list(m.transcribe(silence, language="en", beam_size=1)[0])
        return m


# ---------------------------------------------------------------- main
def main():
    stt = load_whisper()
    print(f"model: {OLLAMA_MODEL}   ctrl-c to quit\n")

    history = [{"role": "system", "content": SYSTEM_PROMPT}]
    timings = []

    while True:
        audio = record_until_enter()
        t0 = time.perf_counter()                       # end of speech
        if audio.size < WHISPER_RATE // 4:
            print("  (too short)\n")
            continue

        segments, _ = stt.transcribe(audio, language="en", beam_size=1)
        text = " ".join(s.text for s in segments).strip()
        t1 = time.perf_counter()
        if not text:
            print("  (nothing heard)\n")
            continue
        print(f"  you: {text}")

        history.append({"role": "user", "content": text})

        marks = {}
        def gen():
            for i, tok in enumerate(ollama_stream(history)):
                if i == 0:
                    marks["t2"] = time.perf_counter()
                yield tok

        reply = speak_streaming(gen(), lambda: marks.__setitem__("t3", time.perf_counter()))
        history.append({"role": "assistant", "content": reply})

        t2 = marks.get("t2", t1)
        t3 = marks.get("t3", t2)
        timings.append(t3 - t0)
        print(f"  her: {reply.strip()}")
        print(f"  [stt {t1-t0:.2f}s | llm-first-token {t2-t1:.2f}s | "
              f"FIRST AUDIO {t3-t0:.2f}s | median {np.median(timings):.2f}s]\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye")
