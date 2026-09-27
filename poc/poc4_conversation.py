#!/usr/bin/env python3
"""
POC 4 - Hands-free conversation
Question: can she hold a conversation with no keyboard, no wake-word model,
and without hearing herself?

    pip install pysilero-vad
    source poc/env.sh
    python poc/poc4_conversation.py

NO WAKE-WORD MODEL. Everything is transcribed continuously; opening the
conversation is a deterministic name match in the TEXT.

That is only affordable because STT here runs in ~0.02s on GPU. Wake-word
models exist because a Raspberry Pi cannot transcribe continuously. This
machine can, so the constraint does not apply - and dropping the model gets us
any name we want (including "Desiree", which no pre-trained model covers), no
CC-BY-NC-SA licensing exposure, and one fewer recogniser to tune.

DELIBERATELY NOT: "let the LLM decide when to respond." That puts a model in a
gate position, which is the same shape as LLM-as-safety-judge (see ADR-0001).
A string match cannot be argued into opening. It is also free, whereas asking
the model about every utterance in the room is an LLM call per utterance.

THE STATE MACHINE - this is the whole POC.

    IDLE ---- name heard ----> OPEN
      ^                          |
      |                     speech ends
      |                          v
      +---- window expires --- THINKING/SPEAKING
                                 |
                                 v
                            OPEN (window reset)

In IDLE everything is still transcribed, but nothing is sent to the model,
nothing is logged, and nothing is remembered unless the name appears. An
always-open mic is a microphone you have to trust; a window is a capability
boundary with a timer on it.

THREE STORES, because they have opposite requirements.

    facts.md      resident. loaded every turn. superseding. small.
    log/DATE.md   append-only. BOTH speakers. never loaded wholesale.
    decisions/    ADRs. retrieved by keyword, not resident.

The log keeps the assistant's turns - that is where architectural reasoning
lives and it is the reason to keep a transcript at all. But it is not loaded
into context, so it cannot poison recall the way POC 2 did. Only extracted
facts are resident, and the extraction pass emits `skip` for non-facts, which
is what stops "I don't know" ever being filed as a belief.

BARS - set before running, do not move them afterwards:
    1. Name opens the conversation >= 8/10 at normal speaking volume.
    2. <= 1 false open in 30 min of ordinary desk noise and phone calls.
    3. Five consecutive follow-up turns without saying the name.
    4. ZERO self-triggers. She must never transcribe her own voice.
    5. End-of-speech never cuts you off mid-sentence in 10 turns.
    6. Median first-audio under 2.0s.

Bar 1 is now a TRANSCRIPTION problem, not an acoustics one. Whisper will hear
"Desiree" as desiray / desree / daisy ray / the ziree, so NAME_VARIANTS plus a
fuzzy ratio does the matching, and initial_prompt biases Whisper toward the
spelling. Run `--tune` to see what it actually hears before setting a
threshold - guessing here is how you end up with a name that works for you and
nobody else.

Bar 4 will fail first on speakers. On the Jabra headset it should be trivial,
which is itself the finding: it tells you whether this needs echo cancellation
or just a headset.
"""

import os
import re
import sys
import json
import time
import queue
import datetime as dt
import subprocess
import threading
import difflib
import collections

import numpy as np
import sounddevice as sd
import requests

# ---------------------------------------------------------------- config
OLLAMA_URL   = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
WHISPER_SIZE = os.environ.get("WHISPER_SIZE", "base.en")
WHISPER_DEV  = os.environ.get("WHISPER_DEVICE", "auto")
PIPER_BIN    = os.environ.get("PIPER_BIN", "piper")
PIPER_VOICE  = os.environ.get("PIPER_VOICE", "")
PIPER_RATE   = int(os.environ.get("PIPER_RATE", "22050"))
OUT_DEVICE   = os.environ.get("AUDIO_OUT") or None
IN_DEVICE    = os.environ.get("AUDIO_IN") or None

MEM_DIR   = os.environ.get("MEM_DIR", os.path.join(os.path.dirname(__file__), "memory"))
FACTS     = os.path.join(MEM_DIR, "facts.md")
LOG_DIR   = os.path.join(MEM_DIR, "log")
DEC_DIR   = os.path.join(MEM_DIR, "decisions")

NAME         = os.environ.get("ASSISTANT_NAME", "Desiree")
NAME_RATIO   = float(os.environ.get("NAME_RATIO", "0.80"))
CONV_WINDOW  = float(os.environ.get("CONVERSATION_WINDOW", "25"))  # seconds
LOG_IDLE     = os.environ.get("LOG_IDLE", "") == "1"   # log un-addressed speech

# What Whisper actually produces for "Desiree". Add to this list from --tune
# output rather than lowering NAME_RATIO - a lower ratio opens on everything.
NAME_VARIANTS = [
    "desiree", "desire", "desiray", "desirae", "desree", "dezire", "dezeray",
    "daisy ray", "daisyray", "the ziree", "desi ray", "des a ray",
]

# Nudges Whisper toward the spelling instead of a phonetic guess.
STT_PROMPT = f"A conversation with an assistant named {NAME}."

RATE       = 16000
BLOCK      = 1280          # 80ms - openWakeWord's recommended chunk
VAD_CHUNK  = 512           # what pysilero wants
PREROLL    = 8             # blocks of audio kept before speech starts (~0.64s)
HANG       = 0.8           # seconds of silence that ends a turn
MIN_SPEECH = 0.3           # ignore anything shorter than this

SYSTEM = (
    "You are a concise voice assistant. Answer in at most three short "
    "sentences. Never use lists, markdown or emoji - your words are spoken "
    "aloud. If you do not know, say so plainly rather than guessing.\n\n"
    "If a fact was later changed, the most recent statement wins."
)

EXTRACT_SYSTEM = (
    "You extract durable facts for a memory store. You are given the current "
    "facts and one new statement from the user.\n"
    "Reply with ONE JSON object and nothing else. No markdown, no backticks.\n"
    '  {"action":"add","key":"<short key>","value":"<the fact>"}\n'
    '  {"action":"update","key":"<existing key>","value":"<the new fact>"}\n'
    '  {"action":"skip"}\n'
    "Use update when the statement changes a fact already in the store - reuse "
    "that fact's exact key. Use skip for questions, chit-chat, or anything not "
    "worth remembering. Keys are lowercase, two or three words, no punctuation."
)


# ---------------------------------------------------------------- name match
_PUNCT = re.compile(r"[^\w\s]")


def _norm(text: str) -> str:
    return _PUNCT.sub(" ", text.lower()).strip()


def heard_name(text: str) -> bool:
    """
    Deterministic. No model involved, so nothing can talk it into opening.
    Exact variant match first, then a fuzzy ratio over single words and
    adjacent pairs (Whisper often splits the name in two).
    """
    norm = _norm(text)
    for v in NAME_VARIANTS:
        if v in norm:
            return True
    words = norm.split()
    cands = words + [f"{a} {b}" for a, b in zip(words, words[1:])]
    target = NAME.lower()
    for c in cands:
        if difflib.SequenceMatcher(None, c, target).ratio() >= NAME_RATIO:
            return True
    return False


def strip_name(text: str) -> str:
    """Remove the address so 'Desiree, what time is it' asks a clean question."""
    out = text
    for v in sorted(NAME_VARIANTS + [NAME.lower()], key=len, reverse=True):
        out = re.sub(rf"\b{re.escape(v)}\b", "", out, flags=re.I)
    return re.sub(r"^[\s,.:;!?-]+", "", re.sub(r"\s{2,}", " ", out)).strip()


# ---------------------------------------------------------------- memory
def _ensure_dirs():
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(DEC_DIR, exist_ok=True)


_FACT_LINE = re.compile(r"^- ([^:]+): (.*)$")


def read_facts() -> "dict[str, str]":
    facts = {}
    if os.path.exists(FACTS):
        for line in open(FACTS, encoding="utf-8"):
            m = _FACT_LINE.match(line.rstrip())
            if m:
                facts[m.group(1).strip()] = m.group(2).strip()
    return facts


def write_facts(facts: "dict[str, str]"):
    with open(FACTS, "w", encoding="utf-8") as f:
        f.write("# facts\n\n")
        for k, v in facts.items():
            f.write(f"- {k}: {v}\n")


def facts_block() -> str:
    facts = read_facts()
    return "\n".join(f"- {k}: {v}" for k, v in facts.items()) or "(empty)"


def append_log(role: str, text: str):
    """Everything, both speakers, forever. Never loaded into context."""
    path = os.path.join(LOG_DIR, dt.date.today().isoformat() + ".md")
    stamp = dt.datetime.now().strftime("%H:%M:%S")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n[{stamp}] {role}: {text.strip()}\n")


def search_decisions(query: str, limit: int = 2) -> str:
    """
    Retrieved, not resident. Deliberately dumb - word overlap on the title and
    body. If this turns out to matter, THAT is when you reach for embeddings,
    not before.
    """
    if not os.path.isdir(DEC_DIR):
        return ""
    words = {w for w in re.findall(r"\w+", query.lower()) if len(w) > 3}
    if not words:
        return ""
    scored = []
    for name in sorted(os.listdir(DEC_DIR)):
        if not name.endswith(".md"):
            continue
        body = open(os.path.join(DEC_DIR, name), encoding="utf-8").read()
        hits = sum(1 for w in words if w in body.lower())
        if hits:
            scored.append((hits, name, body))
    scored.sort(reverse=True)
    if not scored:
        return ""
    return "\n\n".join(f"[{n}]\n{b[:1200]}" for _s, n, b in scored[:limit])


# ---------------------------------------------------------------- ollama
def chat(system: str, user: str, timeout: int = 180) -> str:
    r = requests.post(f"{OLLAMA_URL}/api/chat",
                      json={"model": OLLAMA_MODEL, "stream": False,
                            "options": {"temperature": 0},
                            "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": user}]},
                      timeout=timeout)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def chat_stream(system: str, user: str):
    r = requests.post(f"{OLLAMA_URL}/api/chat",
                      json={"model": OLLAMA_MODEL, "stream": True,
                            "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": user}]},
                      stream=True, timeout=120)
    r.raise_for_status()
    for line in r.iter_lines():
        if not line:
            continue
        tok = json.loads(line).get("message", {}).get("content", "")
        if tok:
            yield tok


def extract(user_text: str):
    """Second pass. Only this writes to facts.md."""
    prompt = f"CURRENT FACTS\n{facts_block()}\n\nNEW STATEMENT\n{user_text}"
    try:
        raw = chat(EXTRACT_SYSTEM, prompt, timeout=120)
    except Exception as e:
        print(f"  [extract failed: {e}]")
        return
    raw = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        op = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except Exception:
        return
    if op.get("action") not in ("add", "update"):
        return
    key, value = str(op.get("key", "")).strip(), str(op.get("value", "")).strip()
    if not key or not value:
        return
    facts = read_facts()
    was = facts.get(key)
    facts[key] = value
    write_facts(facts)
    if was and was != value:
        print(f"  [memory] {key}: {was} -> {value}")
    else:
        print(f"  [memory] {key}: {value}")


# ---------------------------------------------------------------- speech out
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
speaking = threading.Event()          # mic gate. set while audio is playing.


def piper_play(text: str):
    text = text.strip()
    if not text:
        return
    cmd = [PIPER_BIN, "--output-raw"]
    if PIPER_VOICE:
        cmd += ["--model", PIPER_VOICE]
    aplay = ["aplay", "-q", "-r", str(PIPER_RATE), "-f", "S16_LE", "-t", "raw", "-"]
    if OUT_DEVICE:
        aplay += ["-D", OUT_DEVICE]

    piper = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL)
    player = subprocess.Popen(aplay, stdin=piper.stdout, stderr=subprocess.DEVNULL)
    piper.stdout.close()
    piper.stdin.write(text.encode() + b"\n")   # piper needs the newline
    piper.stdin.close()
    piper.wait()
    player.wait()


def speak_streaming(token_iter, on_first_audio):
    """Synthesise on each sentence boundary while the model still generates."""
    q: "queue.Queue[str | None]" = queue.Queue()
    fired = threading.Event()

    def worker():
        while True:
            sentence = q.get()
            if sentence is None:
                return
            if not fired.is_set():
                fired.set()
                on_first_audio()
            piper_play(sentence)

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    buf, full = "", ""
    for tok in token_iter:
        buf += tok
        full += tok
        while len(_SENTENCE_END.split(buf)) > 1:
            parts = _SENTENCE_END.split(buf, maxsplit=1)
            q.put(parts[0])
            buf = parts[1]
    if buf.strip():
        q.put(buf)
    q.put(None)
    t.join()
    return full


# ---------------------------------------------------------------- main loop
def main():
    _ensure_dirs()
    tune = "--tune" in sys.argv

    from faster_whisper import WhisperModel
    from pysilero_vad import SileroVoiceActivityDetector

    print(f"loading whisper ({WHISPER_SIZE}, {WHISPER_DEV})...")
    try:
        stt = WhisperModel(WHISPER_SIZE, device=WHISPER_DEV, compute_type="auto")
        list(stt.transcribe(np.zeros(RATE // 2, dtype=np.float32),
                            language="en", beam_size=1)[0])
    except Exception as e:
        print(f"  !! {WHISPER_DEV} failed ({e})")
        print("  !! CPU fallback. Continuous STT on CPU is viable but slower -")
        print("     fix LD_LIBRARY_PATH before you record any timings.")
        stt = WhisperModel(WHISPER_SIZE, device="cpu", compute_type="auto")

    vad = SileroVoiceActivityDetector()
    frames: "queue.Queue[np.ndarray]" = queue.Queue()

    def cb(indata, _n, _t, status):
        if status:
            print(f"  [audio] {status}", file=sys.stderr)
        # THE MIC GATE. Frames captured while she is speaking are dropped on
        # the floor, so she cannot hear herself. Cheaper and more reliable
        # than echo cancellation, and it is why bar 4 should pass.
        if not speaking.is_set():
            frames.put(indata.copy().flatten())

    if tune:
        print("\n[tune] every utterance transcribed, nothing sent to the model.")
        print("[tune] say the name ten different ways and watch what it hears.\n")
    else:
        print(f'\nsay "{NAME}" to start. window {CONV_WINDOW:.0f}s. ctrl-c to quit.\n')

    state, window_until = "IDLE", 0.0
    preroll = collections.deque(maxlen=PREROLL)
    speech: "list[np.ndarray]" = []
    residual = np.zeros(0, dtype=np.int16)
    silence_run = 0.0
    timings = []

    with sd.InputStream(samplerate=RATE, channels=1, dtype="int16",
                        blocksize=BLOCK, device=IN_DEVICE, callback=cb):
        while True:
            try:
                block = frames.get(timeout=0.5)
            except queue.Empty:
                if state == "OPEN" and not speech and time.time() > window_until:
                    print("  [window closed]\n")
                    state = "IDLE"
                continue

            # --- ONE capture path, both states. VAD segments every utterance,
            #     whether or not we are in a conversation.
            residual = np.concatenate([residual, block])
            voiced = False
            while len(residual) >= VAD_CHUNK:
                chunk, residual = residual[:VAD_CHUNK], residual[VAD_CHUNK:]
                if vad(chunk.tobytes()) >= 0.5:
                    voiced = True

            if voiced:
                if not speech:
                    speech.extend(preroll)   # or you lose the first syllable
                speech.append(block)
                silence_run = 0.0
            elif speech:
                speech.append(block)
                silence_run += BLOCK / RATE
            else:
                preroll.append(block)
                if state == "OPEN" and time.time() > window_until:
                    print("  [window closed]\n")
                    state = "IDLE"

            if not (speech and silence_run >= HANG):
                continue

            # --- utterance ended -------------------------------------------
            t0 = time.perf_counter()
            audio = np.concatenate(speech).astype(np.float32) / 32768.0
            speech, silence_run = [], 0.0
            preroll.clear()
            if audio.size < RATE * MIN_SPEECH:
                continue

            segments, _ = stt.transcribe(audio, language="en", beam_size=1,
                                         initial_prompt=STT_PROMPT)
            text = " ".join(s.text for s in segments).strip()
            t1 = time.perf_counter()
            if not text:
                continue

            named = heard_name(text)

            if tune:
                print(f"  {'MATCH ' if named else '      '}[{t1-t0:.2f}s] {text}")
                continue

            # --- the gate ---------------------------------------------------
            if state == "IDLE":
                if not named:
                    # Heard, transcribed, discarded. Not sent to the model, not
                    # logged, not remembered.
                    if LOG_IDLE:
                        append_log("ambient", text)
                    continue
                print("  [opened]")
                state = "IDLE_TO_OPEN"

            query = strip_name(text) if named else text
            print(f"  you: {text}")

            if not query:
                # Name and nothing else. Acknowledge, hold the window open.
                state, window_until = "OPEN", time.time() + CONV_WINDOW
                speaking.set()
                try:
                    piper_play("Yes?")
                finally:
                    time.sleep(0.15)
                    while not frames.empty():
                        frames.get_nowait()
                    vad.reset()
                    speaking.clear()
                continue

            append_log("user", text)
            adrs = search_decisions(query)
            context = SYSTEM + "\n\n--- FACTS ---\n" + facts_block()
            if adrs:
                context += "\n\n--- RELEVANT DECISIONS ---\n" + adrs

            marks = {}

            def gen():
                for i, tok in enumerate(chat_stream(context, query)):
                    if i == 0:
                        marks["t2"] = time.perf_counter()
                    yield tok

            speaking.set()
            try:
                reply = speak_streaming(
                    gen(), lambda: marks.__setitem__("t3", time.perf_counter()))
            finally:
                # Drain anything the mic queued during the gate, then reopen.
                time.sleep(0.15)
                while not frames.empty():
                    frames.get_nowait()
                vad.reset()
                speaking.clear()

            append_log("assistant", reply)
            threading.Thread(target=extract, args=(query,), daemon=True).start()

            t2, t3 = marks.get("t2", t1), marks.get("t3", t1)
            timings.append(t3 - t0)
            print(f"  her: {reply.strip()}")
            print(f"  [stt {t1-t0:.2f}s | first-token {t2-t1:.2f}s | "
                  f"FIRST AUDIO {t3-t0:.2f}s | median {np.median(timings):.2f}s]\n")

            state, window_until = "OPEN", time.time() + CONV_WINDOW


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye")