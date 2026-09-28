#!/usr/bin/env python3
"""
poc/eval/eval.py - evaluation harness for the POC memory (poc2_memory.py).

It measures the REAL poc file, through switches added by hooks.py. It never
reimplements the system under test.

    python poc/eval/eval.py plan   configs/quick.yaml      # what would run, and how long
    python poc/eval/eval.py run    configs/quick.yaml      # smoke test, minutes
    python poc/eval/eval.py run    configs/default.yaml    # the full suite, hours
    python poc/eval/eval.py audit  results/<run> --n 30    # sample verdicts for a human
    python poc/eval/eval.py agree  results/<run>/audit.csv # how often the scorer is right
    python poc/eval/eval.py noisify datasets/house.yaml    # pre-build speech-noise cache

Each job seeds a memory ONCE per size (cached, reused across answer models,
switches and repeats), then quizzes it. Sizes are nested: the 100-distractor
memory is exactly the start of the 1000-distractor one, so the trend is fair.

Verdicts per question: PASS, MISS (said it didn't know) or FAB (said something
wrong). Everything is written per question to results.jsonl; summary.md holds
the tables. See README.md for what every number means.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
POC = HERE.parent
RESULTS = HERE / "results"
CACHE = RESULTS / "cache"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(POC))
from distractors import make_distractors  # noqa: E402

# ------------------------------------------------------------------ scoring
IDK_PATTERNS = [
    r"\b(i )?(do not|don't|dont) know\b",
    r"\bnot (in|stated|mentioned|specified)\b",
    r"\bno (record|information|mention)\b",
    r"\bhaven't (told|mentioned|said)\b",
]
DONT_KNOW = re.compile(
    r"\b(do not know|don't know|dont know|not sure|no (information|record|mention)|"
    r"(don't|do not) have (that|any|this) (information|info|detail)|"
    r"not (in|stated|mentioned|recorded|specified)|unknown|can't (find|tell)|"
    r"cannot (find|tell))\b", re.I)


def expand(patterns: list) -> list:
    out = []
    for p in patterns or []:
        out.extend(IDK_PATTERNS if p == "IDK" else [p])
    return out


def is_trap(q: dict) -> bool:
    return q["expect"] == ["IDK"]


# A reject word right after one of these is the answer stating a correction
# ("Dunmore now, not Carrow"), not asserting the wrong value. Found 28 Sep 2026:
# correct answers were failing on their own correction.
NEGATED = re.compile(r"(\bnot|\bno longer|\bpreviously|\bformerly|\bused to( be)?|"
                     r"\binstead of|\brather than|\bchanged from|\bmoved from|"
                     r"\bwas\b|\bnot on|\bnot in|\bnot at)\W+(\w+\W+){0,3}$")


def rejected(pattern: str, a: str) -> bool:
    """True if the pattern matches somewhere that is NOT a stated correction."""
    for m in re.finditer(pattern, a):
        if not NEGATED.search(a[max(0, m.start() - 40):m.start()]):
            return True
    return False


def skeleton(word: str) -> str:
    """
    Crude sound-alike key: first letter, then consonants, doubles collapsed.
    brenmoor/brennmore -> brnmr, noor/nor -> nr, kelpie/kelp eye -> klp, k/kay -> k.
    Approximate on purpose: it only has to stop the scorer punishing a
    spelling that would sound identical when spoken back.
    """
    w = re.sub(r"[^a-z]", "", word.lower().replace("ph", "f"))
    w = re.sub(r"ck|q", "k", w)
    w = re.sub(r"c(?=[eiy])", "s", w).replace("c", "k")
    if not w:
        return ""
    return re.sub(r"(.)\1+", r"\1", w[0] + re.sub(r"[aeiouyhw]", "", w[1:]))


def literals(pattern: str) -> list:
    """Plain-word alternatives inside a regex, e.g. 'brenmoor', 'far woods'."""
    out = []
    for alt in pattern.split("|"):
        alt = re.sub(r"\\b|\.\?|\.\{[^}]*\}|[()^$]", "", alt).strip()
        if re.fullmatch(r"[a-z][a-z' -]*", alt):
            out.append(alt)
    return out


LETTER_NAMES = {"a": "ay", "b": "bee", "c": "see", "d": "dee", "e": "ee", "f": "ef",
                "g": "gee", "h": "aitch", "i": "eye", "j": "jay", "k": "kay", "l": "el",
                "m": "em", "n": "en", "o": "oh", "p": "pee", "q": "cue", "r": "ar",
                "s": "es", "t": "tee", "u": "you", "v": "vee", "w": "double u",
                "x": "ex", "y": "why", "z": "zed"}


def sounds_in(lit: str, a: str) -> bool:
    """Does something in the answer sound like the literal? Windows of 1-3 words."""
    if len(lit) == 1 and lit in LETTER_NAMES:          # "K" is often heard as "Kay"
        return bool(re.search(rf"\b{LETTER_NAMES[lit]}\b", a))
    key = skeleton(lit)
    if len(key) < 2:
        return False
    words = re.findall(r"[a-z']+", a)
    target = len(re.sub(r"[^a-z]", "", lit))
    for n in (1, 2, 3):
        for i in range(len(words) - n + 1):
            joined = "".join(words[i:i + n])
            if abs(len(joined) - target) <= 3 and skeleton(joined) == key:
                return True
    return False


def hit(pattern: str, a: str, phonetic: bool) -> bool:
    return bool(re.search(pattern, a)) or (
        phonetic and any(sounds_in(l, a) for l in literals(pattern)))


def verdict(answer: str, q: dict, phonetic: bool = False) -> str:
    """
    PASS: matches expect and no reject. MISS: said it didn't know. FAB: anything else.
    phonetic=True (noisy-speech jobs only) also accepts a sound-alike spelling
    of an expected or rejected name, the way it would sound spoken back.
    """
    a = answer.lower()
    ok = any(hit(p, a, phonetic) for p in expand(q["expect"]))
    bad = any(rejected(p, a) or (phonetic and any(sounds_in(l, a) for l in literals(p)))
              for p in q.get("reject", []))
    if ok and not bad:
        return "PASS"
    return "MISS" if DONT_KNOW.search(answer) and not bad else "FAB"


# ------------------------------------------------------------------ data
def load_yaml(path) -> dict:
    return yaml.safe_load(open(path, encoding="utf-8"))


def load_dataset(name: str) -> dict:
    path = HERE / "datasets" / f"{name}.yaml"
    d = load_yaml(path)
    for s in d["statements"]:
        s.setdefault("speaker", "owner")
        s.setdefault("phase", "early")
    for q in d["questions"]:
        for p in expand(q["expect"]) + q.get("reject", []):
            re.compile(p)
    d["_hash"] = hashlib.sha256(json.dumps(d["statements"]).encode()).hexdigest()[:10]
    return d


def dataset_words(d: dict) -> set:
    words = set()
    for s in d["statements"]:
        words |= set(re.findall(r"[a-z]+", s["text"].lower()))
    return words


# ------------------------------------------------------------------ speech noise
def noisy_cache_path(vocab: str = "") -> Path:
    voice = os.environ.get("PIPER_VOICE", "")
    size = os.environ.get("WHISPER_SIZE", "base.en")
    tag = re.sub(r"[^a-z0-9]+", "-", (voice + "_" + size).lower())
    if vocab:
        tag += "_v" + hashlib.sha256(vocab.encode()).hexdigest()[:8]
    return CACHE / f"noisy_{tag}.json"


COMMON_CAPS = {
    "I", "I'm", "Please", "Weather", "Animal", "Hospital", "Primary", "Road", "Street",
    "Monday", "Mondays", "Tuesday", "Wednesday", "Thursday", "Friday", "Fridays",
    "Saturday", "Sunday", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"}


def dataset_vocab(d: dict) -> str:
    """
    Whisper prompt of the names in memory. OWNER statements only: a name the
    TV or a guest said is exactly what must not be trusted, so it must not be
    fed to the ear as a known word either. In the real system memory supplies it.
    """
    names = set()
    for st in d["statements"]:
        if st.get("speaker", "owner") != "owner":
            continue
        for m in re.finditer(r"\b([A-Z][A-Za-z]+)", st["text"]):
            w = m.group(1)
            if w not in COMMON_CAPS and not w.endswith("'s"):
                names.add(w)
    return "Names: " + ", ".join(sorted(names)) + "." if names else ""


def noisify(texts: "list[str]", vocab: str = "") -> "dict[str, str]":
    """
    Text -> Piper speech -> Whisper transcript, cached. Gives realistic
    transcription errors without anyone recording audio. No initial_prompt is
    given to Whisper, so the errors are the raw ones.
    """
    voice = os.environ.get("PIPER_VOICE", "")
    size = os.environ.get("WHISPER_SIZE", "base.en")
    cache_path = noisy_cache_path(vocab)
    cache = json.load(open(cache_path)) if cache_path.exists() else {}
    todo = [t for t in dict.fromkeys(texts) if t not in cache]
    if todo:
        from faster_whisper import WhisperModel
        model = WhisperModel(size, device=os.environ.get("WHISPER_DEVICE", "auto"),
                             compute_type="auto")
        tmp = CACHE / "noisy_tmp.wav"
        piper = os.environ.get("PIPER_BIN", "piper")
        print(f"  noisify: {len(todo)} statements through Piper and Whisper")
        for i, t in enumerate(todo, 1):
            cmd = [piper, "--output_file", str(tmp)] + (["--model", voice] if voice else [])
            subprocess.run(cmd, input=(t + "\n").encode(), check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            segs, _ = model.transcribe(str(tmp), language="en", beam_size=1,
                                       initial_prompt=vocab or None)
            cache[t] = " ".join(s.text for s in segs).strip()
            if i % 50 == 0:
                print(f"    {i}/{len(todo)}")
                json.dump(cache, open(cache_path, "w"))
        tmp.unlink(missing_ok=True)
        CACHE.mkdir(parents=True, exist_ok=True)
        json.dump(cache, open(cache_path, "w"))
    return cache


# ------------------------------------------------------------------ system under test
SWITCHES = ("EXTRACT_MODEL", "ANSWER_MODEL", "QUOTE_CHECK", "SPEAKER_AWARE",
            "NUM_CTX", "NUM_PREDICT", "TEMPERATURE", "STRICT_PARSE",
            "FACTS_FILE", "FACTS_LOG_FILE")


def load_system(workdir: Path, env: dict):
    """(Re)import poc2_memory with its files in workdir and switches from env."""
    workdir.mkdir(parents=True, exist_ok=True)
    for k in SWITCHES:
        os.environ.pop(k, None)
    for k, v in env.items():
        if v is not None:
            os.environ[k] = str(v)
    os.environ["FACTS_FILE"] = str(workdir / "facts.md")
    os.environ["FACTS_LOG_FILE"] = str(workdir / "facts_log.md")
    argv, sys.argv = sys.argv, ["poc2_memory"]       # it reads flags at import
    try:
        mod = importlib.reload(sys.modules["poc2_memory"]) if "poc2_memory" in sys.modules \
            else importlib.import_module("poc2_memory")
    finally:
        sys.argv = argv
    if not hasattr(mod, "STRICT_PARSE") or "speaker" not in mod.extract.__code__.co_varnames:
        sys.exit("poc2_memory.py has no eval hooks. Run:\n"
                 "  python poc/eval/hooks.py poc/poc2_memory.py")
    return mod


def switches_for(variant: dict, extract_model: str, answer_model: str = None) -> dict:
    return {
        "EXTRACT_MODEL": extract_model,
        "ANSWER_MODEL": answer_model or extract_model,
        "QUOTE_CHECK": "1" if variant.get("quote_check", True) else "0",
        "SPEAKER_AWARE": "1" if variant.get("speaker_aware", False) else "0",
        "NUM_CTX": variant.get("num_ctx"),
        "NUM_PREDICT": variant.get("num_predict"),
        "TEMPERATURE": variant.get("temperature", 0),
        "STRICT_PARSE": "1",          # an unparseable extraction is a recorded failure
    }


# ------------------------------------------------------------------ gpu memory
class VramSampler:
    """Peak GPU memory while a block runs. Silently absent without nvidia-smi."""

    def __init__(self):
        self.peak, self._stop = None, threading.Event()
        self.ok = shutil.which("nvidia-smi") is not None

    def _run(self):
        while not self._stop.is_set():
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                                      "--format=csv,noheader,nounits"],
                                     capture_output=True, text=True, timeout=5).stdout
                used = sum(int(x) for x in out.split() if x.strip().isdigit())
                self.peak = max(self.peak or 0, used)
            except Exception:
                pass
            self._stop.wait(0.5)

    def __enter__(self):
        if self.ok:
            self._t = threading.Thread(target=self._run, daemon=True)
            self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()


# ------------------------------------------------------------------ seeding
def est_tokens(chars: int) -> int:
    return int(chars / 3.0)          # conservative; 3.8 undercounted by ~13%


def seed_snapshots(ds: dict, sizes: list, variant: dict, extract_model: str,
                   dseed: int, ctx: int) -> "dict[int, dict]":
    """
    Build (or reuse) one memory snapshot per size. Order: early statements,
    then distractors up to the size, then late statements (corrections,
    forgetting) applied to a copy. Returns {size: {"dir": Path, "stats": {...}}}.
    """
    key_src = json.dumps(["harness-v2", ds["name"], ds["_hash"], extract_model,
                          variant.get("speaker_aware", False),
                          variant.get("input", "clean"), variant.get("num_ctx"),
                          variant.get("num_predict"), dseed,
                          variant.get("extract_temperature", 0),
                          variant.get("replica", 0)])
    base = CACHE / "seed" / hashlib.sha256(key_src.encode()).hexdigest()[:12]
    base.mkdir(parents=True, exist_ok=True)
    (base / "key.json").write_text(key_src)
    sizes = sorted(set(sizes))
    out = {}
    missing = [n for n in sizes if not (base / f"size_{n}" / "stats.json").exists()]
    if missing and (base / "state.json").exists():
        print(f"    seed cache partial ({base.name}): building sizes {missing}")
    if not missing:
        for n in sizes:
            out[n] = {"dir": base / f"size_{n}",
                      "stats": json.load(open(base / f"size_{n}" / "stats.json"))}
        print(f"    seed cache hit ({base.name}) for sizes {sizes}")
        return out

    early = [s for s in ds["statements"] if s["phase"] != "late"]
    late = [s for s in ds["statements"] if s["phase"] == "late"]
    distract = [{"text": t, "speaker": "owner"} for t in
                make_distractors(max(sizes), seed=dseed, exclude=dataset_words(ds))]
    mode = variant.get("input", "clean")
    vocab = dataset_vocab(ds) if mode == "noisy_vocab" else ""
    nmap = noisify([s["text"] for s in early + late + distract], vocab) \
        if mode.startswith("noisy") else {}
    env = switches_for(variant, extract_model)
    env["TEMPERATURE"] = variant.get("extract_temperature", env["TEMPERATURE"])
    # Resumable: work/ holds the memory as fed so far, state.json how far.
    work = base / "work"
    state_path = base / "state.json"
    state = json.load(open(state_path)) if state_path.exists() and work.exists() else None
    if state is None:
        shutil.rmtree(work, ignore_errors=True)
        state = {"early_done": False, "fed": 0, "statements": 0, "errors": []}
    mod = load_system(work, env)
    calls = []

    def save_state():
        json.dump(state, open(state_path, "w"), indent=1)

    def feed(stmts, label, record=True):
        """One extraction per statement. A failure is recorded, never fatal."""
        errs = []
        for i, s in enumerate(stmts, 1):
            text = nmap.get(s["text"], s["text"])
            mod.CALLS.clear()
            try:
                mod.extract(text, verbose=False, speaker=s["speaker"])
            except Exception as exc:                 # timeout, overflow, bad reply
                errs.append({"statement": s["text"][:80],
                             "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
            calls.extend(mod.CALLS)
            if record:
                state["statements"] += 1
            if len(stmts) > 40 and i % 50 == 0:
                print(f"      {label}: {i}/{len(stmts)}  ({len(errs)} errors so far)")
        return errs

    print(f"    seeding {ds['name']} with {extract_model} "
          f"(speaker_aware={env['SPEAKER_AWARE']}, input={variant.get('input', 'clean')}, "
          f"num_ctx={env['NUM_CTX'] or 'server default'})")
    t0 = time.perf_counter()
    if not state["early_done"]:
        state["errors"] += feed(early, "early")
        state["early_done"] = True
        save_state()
    elif state["fed"]:
        print(f"      resuming after {state['fed']} distractors")
    for n in sizes:
        snap = base / f"size_{n}"
        if n <= state["fed"] and (snap / "stats.json").exists():
            out[n] = {"dir": snap, "stats": json.load(open(snap / "stats.json"))}
            continue
        state["errors"] += feed(distract[state["fed"]:n], f"distractors to {n}")
        state["fed"] = max(state["fed"], n)
        save_state()
        shutil.rmtree(snap, ignore_errors=True)
        shutil.copytree(work, snap)
        mod = load_system(snap, env)
        n_calls = len(calls)
        late_errs = feed(late, "late", record=False)
        facts = len(mod.read_facts())
        secs = [c["seconds"] for c in calls]
        chars = [c["prompt_chars"] for c in calls]
        errors = state["errors"] + late_errs
        st = {"size": n, "facts": facts, "statements": state["statements"] + len(late),
              "extract_calls": len(calls),
              "extract_seconds_p50": round(statistics.median(secs), 2) if secs else None,
              "extract_prompt_tokens_est_max": est_tokens(max(chars)) if chars else None,
              "extract_over_ctx": sum(est_tokens(c) > ctx for c in chars),
              "extract_errors": len(errors),
              "extract_error_examples": errors[:5],
              "wall_seconds": round(time.perf_counter() - t0, 1)}
        json.dump(st, open(snap / "stats.json", "w"), indent=1)
        del calls[n_calls:]                          # late calls belong to this copy only
        out[n] = {"dir": snap, "stats": st}
        print(f"      size {n}: {facts} facts, extract prompt up to "
              f"~{st['extract_prompt_tokens_est_max']} tokens, "
              f"{st['extract_errors']} failed extractions")
        mod = load_system(work, env)
    return out


# ------------------------------------------------------------------ quiz
def run_quiz(ds: dict, snap: dict, variant: dict, extract_model: str,
             answer_model: str, repeat: int, run_dir: Path, ctx: int,
             job_name: str) -> list:
    work = run_dir / "stores" / f"{job_name}_{answer_model.replace(':', '-')}_" \
                                f"{snap['stats']['size']}_r{repeat}"
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(snap["dir"], work)
    mod = load_system(work, switches_for(variant, extract_model, answer_model))
    mode = variant.get("input", "clean")
    phonetic = mode.startswith("noisy")
    qmap = {}
    if phonetic:        # the question goes through the same Piper -> Whisper path
        vocab = dataset_vocab(ds) if mode == "noisy_vocab" else ""
        qmap = noisify([t for q in ds["questions"] for t in [q["q"]] + q.get("variants", [])], vocab)
    rows = []
    with VramSampler() as vram:
        for qi, q in enumerate(ds["questions"], 1):
            for vi, said in enumerate([q["q"]] + q.get("variants", [])):
                text = qmap.get(said, said)
                trace, err = {}, None
                try:
                    mod.CALLS.clear()
                    a1 = mod.xask_facts(text)
                    c1 = mod.CALLS[:]
                    mod.CALLS.clear()
                    a2 = mod.xask(text, trace)
                    c2 = mod.CALLS[:]
                except Exception as exc:          # timeout, overflow
                    err = f"{type(exc).__name__}: {str(exc)[:120]}"
                    a1 = a2 = ""
                    c1, c2 = [], mod.CALLS[:]
                chars = [c["prompt_chars"] for c in c2]
                rows.append({
                    "job": job_name, "dataset": ds["name"], "variant": variant["name"],
                    "extract_model": extract_model, "answer_model": answer_model,
                    "size": snap["stats"]["size"], "facts": snap["stats"]["facts"],
                    "repeat": repeat, "n": qi, "paraphrase": vi,
                    "question": said, "category": q["category"], "trap": is_trap(q),
                    "expect": q["expect"], "reject": q.get("reject", []),
                    "question_heard": text if text != said else None,
                    "answer": a2, "verdict": "ERROR" if err else verdict(a2, q, phonetic),
                    "facts_only_answer": a1,
                    "facts_only_verdict": "ERROR" if err else verdict(a1, q, phonetic),
                    "error": err,
                    "quote": trace.get("quote"), "quote_ok": trace.get("quote_ok"),
                    "downgraded": trace.get("downgraded"),
                    "unverified_answer": trace.get("unverified_answer"),
                    "excerpts": len(trace.get("excerpts", [])),
                    "answer_seconds": round(sum(c["seconds"] for c in c2), 3),
                    "facts_only_seconds": round(sum(c["seconds"] for c in c1), 3),
                    "prompt_tokens_reported": sum((c["prompt_tokens"] or 0) for c in c2),
                    "prompt_tokens_est": est_tokens(max(chars)) if chars else 0,
                    "over_ctx": any(est_tokens(c) > ctx for c in chars),
                })
    for r in rows:
        r["vram_peak_mib"] = vram.peak
    return rows


# ------------------------------------------------------------------ summary
def pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "-"


def summarise(rows: list) -> str:
    def group(key):
        g = {}
        for r in rows:
            g.setdefault(key(r), []).append(r)
        return g

    lines = ["# POC 2 evaluation summary", "",
             f"{len(rows)} answers. PASS = right, MISS = said it didn't know, "
             "FAB = said something wrong (fabrication). Answerable excludes traps.", ""]

    lines += ["## By job, model and size", "",
              "| job | answer model | size | facts | answerable | traps | FAB | FAB rate "
              "| errors | facts-only FAB | downgraded | answer s p50 / p95 | prompt tok max | over ctx | VRAM peak |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for (job, model, size), rs in sorted(group(lambda r: (r["job"], r["answer_model"], r["size"])).items()):
        ans = [r for r in rs if not r["trap"]]
        trp = [r for r in rs if r["trap"]]
        secs = sorted(r["answer_seconds"] for r in rs)
        p95 = secs[min(len(secs) - 1, int(0.95 * len(secs)))] if secs else 0
        reps = sorted({r["repeat"] for r in rs})
        spread = ""
        if len(reps) > 1:
            per = [sum(r["verdict"] == "PASS" for r in ans if r["repeat"] == k) /
                   max(1, sum(1 for r in ans if r["repeat"] == k)) for k in reps]
            spread = f" (range {100 * min(per):.0f}-{100 * max(per):.0f}%)"
        lines.append(
            f"| {job} | {model} | {size} | {rs[0]['facts']} "
            f"| {sum(r['verdict'] == 'PASS' for r in ans)}/{len(ans)} "
            f"{pct(sum(r['verdict'] == 'PASS' for r in ans), len(ans))}{spread} "
            f"| {sum(r['verdict'] == 'PASS' for r in trp)}/{len(trp)} "
            f"| {sum(r['verdict'] == 'FAB' for r in rs)} "
            f"| {pct(sum(r['verdict'] == 'FAB' for r in rs), len(rs))} "
            f"| {sum(r['verdict'] == 'ERROR' for r in rs)} "
            f"| {sum(r['facts_only_verdict'] == 'FAB' for r in rs)} "
            f"| {sum(bool(r['downgraded']) for r in rs)} "
            f"| {statistics.median(secs):.1f} / {p95:.1f} "
            f"| {max(r['prompt_tokens_est'] for r in rs)} "
            f"| {sum(r['over_ctx'] for r in rs)} "
            f"| {rs[0]['vram_peak_mib'] or '-'} |")

    lines += ["", "ERROR = the call failed (timeout or prompt too big for the context). "
              "It counts as not answered. Seed-time failures are in seed_stats.json.", ""]
    lines += ["", "## By category (all jobs pooled, per answer model)", "",
              "| answer model | category | n | PASS | MISS | FAB |", "|---|---|---|---|---|---|"]
    for (model, cat), rs in sorted(group(lambda r: (r["answer_model"], r["category"])).items()):
        lines.append(f"| {model} | {cat} | {len(rs)} | {pct(sum(r['verdict'] == 'PASS' for r in rs), len(rs))} "
                     f"| {sum(r['verdict'] == 'MISS' for r in rs)} | {sum(r['verdict'] == 'FAB' for r in rs)} |")

    fabs = [r for r in rows if r["verdict"] == "FAB"]
    lines += ["", f"## Every fabrication ({len(fabs)})", ""]
    for r in fabs:
        lines.append(f"- [{r['job']} / {r['answer_model']} / size {r['size']}] "
                     f"**{r['question']}** -> {r['answer'][:140]}")
    lines += ["", "Scores are provisional until the scorer is audited: "
              "`eval.py audit <run>` then `eval.py agree <run>/audit.csv`.", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------ commands
def plan(cfg: dict) -> "list[dict]":
    jobs = []
    for j in cfg["jobs"]:
        ds = load_dataset(j["dataset"])
        variant = dict(cfg["variants"][j["variant"]], name=j["variant"])
        sizes = j.get("sizes", [0])
        n_q = sum(1 + len(q.get("variants", [])) for q in ds["questions"])
        answer_models = variant.get("answer_models", [cfg["answer_model"]])
        reps = j.get("repeats", cfg.get("repeats", 1))
        extract_calls = len(ds["statements"]) + max(sizes) + len(sizes) * \
            sum(1 for s in ds["statements"] if s["phase"] == "late")
        quiz_calls = len(sizes) * len(answer_models) * reps * n_q * 2
        jobs.append({"name": f"{j['dataset']}.{j['variant']}", "dataset": ds,
                     "variant": variant, "sizes": sizes, "answer_models": answer_models,
                     "extract_model": variant.get("extract_model", cfg["extract_model"]),
                     "reps": reps, "extract_calls": extract_calls, "quiz_calls": quiz_calls})
    return jobs


def cmd_plan(args):
    cfg = load_yaml(args.config)
    jobs = plan(cfg)
    est = cfg.get("estimate_seconds", {"extract": 0.5, "answer": 0.6})
    total = 0
    print(f"{'job':<30}{'sizes':<32}{'extract calls':>14}{'quiz calls':>12}")
    for j in jobs:
        print(f"{j['name']:<30}{str(j['sizes']):<32}{j['extract_calls']:>14}{j['quiz_calls']:>12}")
        total += j["extract_calls"] * est["extract"] + j["quiz_calls"] * est["answer"]
    print(f"\nrough time, before cache hits: {total / 3600:.1f} h "
          f"(assumes {est['extract']}s per extraction, {est['answer']}s per answer; "
          f"extraction slows as memory grows)")


def ollama_truncations(container: str, since: str):
    """Count Ollama's own truncation warnings since the run started. None if unknown."""
    if not shutil.which("docker"):
        return None
    try:
        out = subprocess.run(["docker", "logs", "--since", since, container],
                             capture_output=True, text=True, timeout=60)
        return (out.stdout + out.stderr).count("truncating input prompt")
    except Exception:
        return None


def ollama_not_on_gpu(container: str) -> list:
    """Loaded models not fully on the GPU - their timings are not comparable."""
    if not shutil.which("docker"):
        return []
    try:
        out = subprocess.run(["docker", "exec", container, "ollama", "ps"],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return []
    return [l.split()[0] + ": " + " ".join(l.split()[3:6]) for l in out.splitlines()[1:]
            if l.strip() and "100% GPU" not in l]


def cmd_run(args):
    cfg = load_yaml(args.config)
    container = cfg.get("ollama_container", "ollama")
    started = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    gpu_warnings = []
    ctx = int(cfg.get("server_context", 4096))
    jobs = plan(cfg)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    run_dir = RESULTS / f"run_{stamp}_{Path(args.config).stem}"
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(args.config, run_dir / "config.yaml")
    out = open(run_dir / "results.jsonl", "w", encoding="utf-8")
    seeds = {}
    all_rows = []
    for j in jobs:
        print(f"\n=== {j['name']}")
        jctx = int(j["variant"].get("num_ctx") or ctx)
        snaps = seed_snapshots(j["dataset"], j["sizes"], j["variant"], j["extract_model"],
                               cfg.get("distractor_seed", 7), jctx)
        seeds[j["name"]] = {n: s["stats"] for n, s in snaps.items()}
        for size in j["sizes"]:
            for model in j["answer_models"]:
                for rep in range(j["reps"]):
                    print(f"    quiz size {size} with {model} (repeat {rep + 1}/{j['reps']})")
                    rows = run_quiz(j["dataset"], snaps[size], j["variant"], j["extract_model"],
                                    model, rep, run_dir, jctx, j["name"])
                    for r in rows:
                        out.write(json.dumps(r) + "\n")
                    out.flush()
                    for w in ollama_not_on_gpu(container):
                        gpu_warnings.append(f"{j['name']} size {size}: {w}")
                        print(f"      !! not fully on GPU: {w}")
                    all_rows += rows
                    ans = [r for r in rows if not r["trap"]]
                    print(f"      answerable {pct(sum(r['verdict'] == 'PASS' for r in ans), len(ans))}"
                          f"  FAB {sum(r['verdict'] == 'FAB' for r in rows)}"
                          f"  ERROR {sum(r['verdict'] == 'ERROR' for r in rows)}")
    out.close()
    json.dump(seeds, open(run_dir / "seed_stats.json", "w"), indent=1)
    summary = summarise(all_rows)
    trunc = ollama_truncations(container, started)
    checks = ["", "## Integrity checks", "",
              f"- Ollama truncation warnings during this run: "
              f"{'unknown (no docker)' if trunc is None else trunc}"
              f"{'  <- MUST be 0; any other number means part of a prompt was silently cut' if trunc else ''}",
              f"- Models not fully on the GPU: {len(gpu_warnings)}"
              + ("".join(f"\n  - {w}" for w in gpu_warnings[:10]))]
    summary = summary.replace("\n## By category", "\n".join(checks) + "\n\n## By category", 1)
    (run_dir / "summary.md").write_text(summary)
    print("\n" + summary.split("## By category")[0])
    print(f"full results: {run_dir}")


def cmd_audit(args):
    run = Path(args.run)
    rows = [json.loads(l) for l in open(run / "results.jsonl")]
    rng = random.Random(args.seed)
    pick = rng.sample(rows, min(args.n, len(rows)))
    with open(run / "audit.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "question", "expected", "answer", "scorer", "human (right/wrong)"])
        for r in pick:
            exp = "I don't know" if r["expect"] == ["IDK"] else " | ".join(r["expect"])
            w.writerow([f"{r['job']}:{r['answer_model']}:{r['size']}:{r['repeat']}:"
                        f"{r['n']}.{r['paraphrase']}",
                        r["question"], exp, r["answer"],
                        "right" if r["verdict"] == "PASS" else "wrong", ""])
    print(f"wrote {run / 'audit.csv'} ({len(pick)} rows). Fill the last column with "
          f"right or wrong, judging the ANSWER yourself, then run: eval.py agree {run / 'audit.csv'}")


def cmd_agree(args):
    rows = list(csv.DictReader(open(args.csv)))
    judged = [r for r in rows if r["human (right/wrong)"].strip().lower() in ("right", "wrong")]
    if not judged:
        sys.exit("no rows judged yet - fill the last column with right or wrong")
    same = [r for r in judged if r["scorer"] == r["human (right/wrong)"].strip().lower()]
    print(f"scorer agrees with you on {len(same)}/{len(judged)} ({pct(len(same), len(judged))})")
    for r in judged:
        if r not in same:
            print(f"  scorer said {r['scorer']:<5}, you said {r['human (right/wrong)'].strip():<5}: "
                  f"{r['question']}  ->  {r['answer'][:80]}")


def cmd_noisify(args):
    d = load_yaml(args.dataset)
    cache = noisify([s["text"] for s in d["statements"]])
    for s in d["statements"][:5]:
        print(f"  said : {s['text'][:90]}\n  heard: {cache[s['text']][:90]}\n")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "run"):
        s = sub.add_parser(name)
        s.add_argument("config")
    s = sub.add_parser("audit")
    s.add_argument("run")
    s.add_argument("--n", type=int, default=30)
    s.add_argument("--seed", type=int, default=1)
    s = sub.add_parser("agree")
    s.add_argument("csv")
    s = sub.add_parser("noisify")
    s.add_argument("dataset")
    args = p.parse_args()
    {"plan": cmd_plan, "run": cmd_run, "audit": cmd_audit,
     "agree": cmd_agree, "noisify": cmd_noisify}[args.cmd](args)


if __name__ == "__main__":
    main()
