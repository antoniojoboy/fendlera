#!/usr/bin/env python3
"""
POC 6 - Memory on ADR-0058 and ADR-0060 to ADR-0064.
Question: does memory split by provenance, kept in plain files and routed by
code, stay safe and flat as it grows - where POC 2's single resident facts
file stopped at ~530 facts?

    source poc/env.sh
    python poc/poc6_memory.py chat                 # talk to it as the owner
    python poc/poc6_memory.py chat --speaker tv    # feed it as another source
    python poc/poc6_memory.py inspect              # files, inbox, read-backs

    MEM_SYSTEM=poc6_memory python poc/eval/eval.py run poc/eval/configs/poc6.yaml

Same interface as poc2_memory (extract / xask / xask_facts / read_facts /
CALLS / STRICT_PARSE), so the suite runs both head to head.

THE FILES ARE THE MEMORY. Nothing else holds truth.
  log/YYYY/MM/DD.jsonl     every utterance, every speaker, one checksummed line
                           each; corrections and file edits are appended here too
  me/<topic>.md            the owner's facts, one file per topic (fixed shelf list)
  people/<name>.md         people and pets, one file each, id in the header
  areas/<name>.md          projects and topics he talks about
  observations/DAY.jsonl   what non-principals said, verbatim, with source
  inbox.jsonl, readback.jsonl, routing.jsonl   decisions, for him and the suite
  .state/                  hashes, shadow copies, session - disposable, rebuilt

  He can edit any .md file. Every write is version-checked: if the file changed
  since she last wrote it, his change is logged as an owner edit and hers is
  applied on top of it. Nothing of his is ever overwritten.

WHAT CODE DECIDES (never the model)
  - Who may write facts: principals only (ADR-0060). Everyone else is an
    observation, no model call at all.
  - Which file a fact lands in: an entity's id via the alias table, or a shelf
    from a fixed list for his own facts.
  - Whether a new person or area may exist: only if the name is in his words.
  - Ambiguity (two Sams): qualifier in his words, then who is in this
    conversation, else the inbox. Never a guess.
  - Whether an answer stands: its quote must be found in the lines retrieved.

WHAT THE MODEL DOES
  - Extraction: fills ops about "self", an id, or a new named entity. Validated.
  - Selection: picks which files to read from the listing - a closed choice,
    like Claude choosing memory files from their descriptions.
  - The answer, from what code retrieved.

NOT IN THIS VERSION
  real speaker ID, the bridge, screenshots, git commits, detecting hand edits
  to log files (use :fix / :void), folding unused provisional areas.
"""

from __future__ import annotations

import datetime as dt
import difflib
import hashlib
import json
import os
import re
import sys
import threading
import time
import zlib
from pathlib import Path

import requests

# ---------------------------------------------------------------- switches
OLLAMA_URL    = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EXTRACT_MODEL = os.environ.get("EXTRACT_MODEL") or "qwen3:8b"
ANSWER_MODEL  = os.environ.get("ANSWER_MODEL") or "qwen3:14b"
SELECT_MODEL  = os.environ.get("SELECT_MODEL") or EXTRACT_MODEL
NUM_CTX       = int(os.environ["NUM_CTX"]) if os.environ.get("NUM_CTX") else 8192
NUM_PREDICT   = int(os.environ["NUM_PREDICT"]) if os.environ.get("NUM_PREDICT") else 1024
TEMPERATURE   = float(os.environ.get("TEMPERATURE") or 0)
QUOTE_CHECK   = os.environ.get("QUOTE_CHECK", "1") != "0"
STRICT_PARSE  = os.environ.get("STRICT_PARSE", "0") == "1"
SPEAKER_AWARE = True          # always: triage is in code. Accepted for the suite.
CHAT_TIMEOUT  = float(os.environ.get("CHAT_TIMEOUT", "180"))

_here = Path(__file__).resolve().parent
# Under the suite, FACTS_FILE names the working directory. By hand, poc/memory6.
ROOT = Path(os.environ["FACTS_FILE"]).parent if os.environ.get("FACTS_FILE") \
    else _here / "memory6"

PRINCIPALS = [p.strip() for p in os.environ.get("PRINCIPALS", "owner,partner").split(",") if p.strip()]
OWNER = PRINCIPALS[0]

# The owner's shelves. Fixed and owned by code; the model picks one, code
# validates it, anything unrecognised lands on "other". Projects and topics
# that need their own place are areas, not shelves.
ME_TOPICS = {
    "profile":     "who he is: name, age, background, where he is from",
    "home":        "the house, address, household, security and alarm codes, utilities",
    "work":        "job, employer, colleagues, career",
    "schedule":    "routines, appointments, dates, recurring events",
    "food":        "food and drink he likes or dislikes, diet",
    "health":      "his health, fitness, medical",
    "money":       "bills, budgets, accounts, purchases",
    "vehicles":    "cars, bikes, transport",
    "tech":        "devices, computers, software, online accounts",
    "hobbies":     "pastimes, interests, sport, collections",
    "travel":      "trips, places visited or planned",
    "preferences": "how he likes things done, opinions",
    "other":       "anything that fits no other shelf",
}

SESSION_TURNS = 10      # "in this conversation" = mentioned in the last N principal turns
SESSION_GAP = 30 * 60   # a gap this long (seconds) between principal lines starts a new session
K_LOG, K_OBS, K_KNOWN = 8, 6, 12
FACT_BUDGET = 80        # facts per answer, after selection
SOURCE_LINES = 30       # source log lines of retrieved facts, for the quote check
LISTING_CAP = 80        # listing lines before it is narrowed to what the words point at

CALLS: list = []        # one record per model call, read by the suite
ASSISTANT = "assistant" # her own replies: logged, never searched, never evidence


class _MemLock:
    """
    One writer at a time: a live conversation calls memory from several
    threads (the reply, the background extraction, the screen). Held by the
    public entry points, and let go while a model call is in flight, so a
    slow extraction never blocks her from recalling for the next reply.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._owner, self._depth = None, 0

    def __enter__(self):
        self._lock.acquire()
        self._owner = threading.get_ident()
        self._depth += 1
        return self

    def __exit__(self, *exc):
        self._depth -= 1
        if self._depth == 0:
            self._owner = None
        self._lock.release()

    def suspended(self):
        lock = self

        class _S:
            def __enter__(self):
                self.n = lock._depth if lock._owner == threading.get_ident() else 0
                for _ in range(self.n):
                    lock.__exit__()

            def __exit__(self, *exc):
                for _ in range(self.n):
                    lock.__enter__()
        return _S()


LOCK = _MemLock()


def _locked(fn):
    def wrapper(*a, **k):
        with LOCK:
            return fn(*a, **k)
    wrapper.__name__, wrapper.__doc__ = fn.__name__, fn.__doc__
    wrapper.__wrapped__ = fn
    return wrapper


class ContextOverflow(RuntimeError):
    """A prompt that will not fit. Refused loudly, never silently cut."""


class ParseError(ValueError):
    """The model's reply could not be read as the required JSON."""


# ---------------------------------------------------------------- text helpers
_STOP = set("""a an the and or but if of to in on at for with by from as is are was were be been
being do does did have has had i me my mine you your yours we our ours us he him his she her it its
they them their what which who whom whose when where why how that this these those there here not no
yes can could would should will shall may might must just about into over under again than then so
too very also any some all each every much many more most other such only own same up down out off
tell told know say said please don doesn didn isn aren wasn weren won get got""".split())


def norm(s: str) -> str:
    """Lower case, possessives and apostrophes dropped: "Sam's" -> "sam"."""
    s = s.lower().replace("\u2019", "'")
    s = re.sub(r"(\w)'s\b", r"\1", s).replace("'", "")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", " ", s)).strip()


def has_phrase(text: str, phrase: str) -> bool:
    phrase = norm(phrase)
    return bool(phrase) and re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", norm(text)) is not None


def slug(s: str) -> str:
    s = s.lower().replace("'", "").replace("\u2019", "")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-") or "unnamed"


def clean_alias(s: str) -> str:
    return re.sub(r"^(my|our|the|his|her|their)\s+", "", norm(s))


def stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "ly", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def stems(text: str) -> set:
    return {stem(w) for w in norm(text).split() if len(w) >= 3 and w not in _STOP}


def is_idk(answer: str) -> bool:
    return bool(re.match(r"\s*i (don'?t|do not) know\b", answer.lower()))


def est_tokens(chars: int) -> int:
    return int(chars / 3.0)          # conservative, same as the suite


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def append_jsonl(path: Path, rec: dict, sync: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if sync:
            f.flush()
            os.fsync(f.fileno())


# ---------------------------------------------------------------- the model
def llm(model: str, system: str, user: str, json_mode: bool = True) -> str:
    est = est_tokens(len(system) + len(user))
    if NUM_CTX and est > 0.95 * NUM_CTX:
        CALLS.append({"model": model, "prompt_tokens": None, "output_tokens": None,
                      "prompt_chars": len(system) + len(user), "seconds": 0.0, "refused": True})
        raise ContextOverflow(f"prompt ~{est} tokens exceeds num_ctx {NUM_CTX}")
    body = {"model": model, "stream": False,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "options": {"temperature": TEMPERATURE, "num_ctx": NUM_CTX,
                        "num_predict": NUM_PREDICT}}
    if json_mode:
        body["format"] = "json"
    if model.startswith(("qwen3", "deepseek")):
        body["think"] = False
    t0 = time.perf_counter()
    with LOCK.suspended():
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=CHAT_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    CALLS.append({"model": model, "prompt_tokens": data.get("prompt_eval_count"),
                  "output_tokens": data.get("eval_count"),
                  "prompt_chars": len(system) + len(user),
                  "seconds": round(time.perf_counter() - t0, 3)})
    text = data.get("message", {}).get("content", "")
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def parse_json(raw: str) -> "dict | None":
    raw = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        return json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except Exception:
        return None


# ---------------------------------------------------------------- markdown files
# A fact is one bullet line. The trailing comment is how she tracks it; a line
# he adds by hand without one is still a fact (his, by edit).
#   - **lives in**: Baldivis (previously Ashby)  <!-- F000006 owner L000009 -->
#   - ~~**job**: chef~~ no longer true  <!-- F000003 owner L000005 -->
#   - loves the Fremantle markets        (hand-added: key "note")
META_RE = re.compile(r"\s*<!--\s*(F\d+)\s+(\S+)\s+(\S+)\s*-->\s*$")


def parse_md(text: str):
    fm, body = {}, text.splitlines()
    if body and body[0].strip() == "---":
        end = next((i for i in range(1, len(body)) if body[i].strip() == "---"), None)
        if end:
            for line in body[1:end]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    v = v.strip()
                    if v.startswith("[") and v.endswith("]"):
                        v = [x.strip() for x in v[1:-1].split(",") if x.strip()]
                    fm[k.strip()] = v
            body = body[end + 1:]
    return fm, body


def dump_md(fm: dict, body: list) -> str:
    head = ["---"] + [f"{k}: [{', '.join(v)}]" if isinstance(v, list) else f"{k}: {v}"
                      for k, v in fm.items()] + ["---"]
    return "\n".join(head + body).rstrip() + "\n"


def parse_fact(line: str):
    if not line.startswith("- "):
        return None
    rest, fid, author, src = line[2:], None, "owner-edit", None
    m = META_RE.search(rest)
    if m:
        fid, author, src = m.group(1), m.group(2), m.group(3)
        rest = rest[:m.start()]
    rest = rest.strip()
    status = "active"
    if rest.startswith("~~"):
        status = "retracted"
        rest = re.sub(r"~~\s*no longer true\s*$", "", rest[2:]).replace("~~", "").strip()
    km = re.match(r"\*\*(.+?)\*\*:\s*(.*)$", rest)
    key, value = (km.group(1).strip(), km.group(2).strip()) if km else ("note", rest)
    return {"fid": fid, "key": norm(key), "value": value, "status": status,
            "author": author, "src": None if src in (None, "-") else src}


def fact_line(key, value, fid, author, src, retracted=False) -> str:
    body = f"**{key}**: {value}"
    if retracted:
        body = f"~~{body}~~ no longer true"
    return f"- {body}  <!-- {fid} {author} {src or '-'} -->"


def base_value(v: str) -> str:
    return re.sub(r"\s*\(previously [^)]*\)\s*$", "", v).strip()


# ---------------------------------------------------------------- the store
class Store:
    """
    Loads everything from the files, keeps a derived index in memory, and is
    the only thing that writes. Delete .state/ at any time: it is rebuilt.
    """

    def __init__(self, root: Path):
        self.root = root
        self.state = root / ".state"
        self.state.mkdir(parents=True, exist_ok=True)
        self.hashes = self._load_state("hashes.json", {})
        self.files: dict = {}           # rel -> {"fm", "body", "facts", "mtime"}
        self.lines: dict = {}           # lid -> utterance record (corrections applied)
        self.order: list = []           # lids in order
        self.max_n = 0
        self.problems: list = []
        self._load_log()
        self.by_id, self.alias_map, self.max_f = {}, {}, 0
        self.refresh()
        self._reindex()
        self._bootstrap()

    # ---- state (disposable)
    def _load_state(self, name, default):
        p = self.state / name
        try:
            return json.loads(p.read_text()) if p.exists() else default
        except Exception:
            return default

    def _save_state(self, name, value):
        atomic_write(self.state / name, json.dumps(value))

    # ---- the log (ADR-0063)
    def _shard(self, day=None) -> Path:
        day = day or dt.date.today()
        return self.root / "log" / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}.jsonl"

    def _load_log(self):
        for shard in sorted((self.root / "log").glob("*/*/*.jsonl")):
            for i, raw in enumerate(open(shard, encoding="utf-8"), 1):
                try:
                    rec = json.loads(raw)
                except Exception:
                    self.problems.append(f"{shard.relative_to(self.root)}:{i} unreadable, skipped")
                    continue
                self._ingest(rec, f"{shard.relative_to(self.root)}:{i}")

    def _ingest(self, rec, where="new"):
        n = rec.get("n", 0)
        self.max_n = max(self.max_n, n)
        kind = rec.get("type", "utterance")
        if kind == "utterance":
            crc = rec.get("crc")
            body = {k: v for k, v in rec.items() if k != "crc"}
            if crc is not None and zlib.crc32(json.dumps(body, sort_keys=True).encode()) & 0xffffffff != crc:
                self.problems.append(f"{where} checksum mismatch, skipped")
                return
            rec = dict(rec, status="self" if rec.get("speaker") == ASSISTANT else "ok",
                       stems=stems(rec["text"]))
            self.lines[rec["id"]] = rec
            self.order.append(rec["id"])
        elif kind == "correction" and rec.get("line") in self.lines:
            ln = self.lines[rec["line"]]
            if rec.get("void"):
                ln["status"] = "void"
            else:
                ln["text"], ln["stems"], ln["corrected"] = rec["text"], stems(rec["text"]), True

    def _append(self, rec: dict) -> dict:
        self.max_n += 1
        rec = dict(rec, n=self.max_n, ts=now_iso())
        if rec.get("type", "utterance") == "utterance":
            rec["id"] = f"L{self.max_n:06d}"
            rec["crc"] = zlib.crc32(json.dumps(rec, sort_keys=True).encode()) & 0xffffffff
        append_jsonl(self._shard(), rec, sync=True)
        self._ingest(rec)
        return rec

    def log_utterance(self, speaker, text) -> str:
        rec = self._append({"speaker": speaker, "principal": speaker in PRINCIPALS, "text": text})
        if speaker not in PRINCIPALS and speaker != ASSISTANT:
            append_jsonl(self.root / "observations" / f"{dt.date.today():%Y-%m-%d}.jsonl",
                         {"id": rec["id"], "ts": rec["ts"], "source": speaker, "text": text})
        return rec["id"]

    def log_event(self, kind, **data):
        self._append(dict(data, type=kind))

    def search_lines(self, text, principal: bool, k):
        q = stems(text)
        if not q:
            return []
        scored = []
        for lid in self.order:
            ln = self.lines[lid]
            if ln["status"] != "ok" or bool(ln["principal"]) != principal:
                continue
            s = len(q & ln["stems"])
            if s:
                scored.append((s, ln["n"], lid))
        scored.sort(reverse=True)
        return [self.lines[lid] for _s, _n, lid in scored[:k]]

    def session_of(self, lid) -> int:
        """Sessions derived from the log: a long silence between principal lines starts a new one."""
        sess, last = 0, None
        for x in self.order:
            ln = self.lines[x]
            if not ln["principal"]:
                continue
            t = dt.datetime.fromisoformat(ln["ts"]).timestamp()
            if last is not None and t - last > SESSION_GAP:
                sess += 1
            last = t
            if x == lid:
                return sess
        return sess

    # ---- files: read, and the version check (ADR-0063)
    def _md_files(self):
        for p in self.root.rglob("*.md"):
            rel = p.relative_to(self.root).as_posix()
            if not rel.startswith((".state/", "log/")):
                yield rel, p

    def refresh(self) -> bool:
        """Pick up anything he changed by hand. Cheap: only files whose mtime moved."""
        changed, seen = False, set()
        for rel, p in self._md_files():
            seen.add(rel)
            mt = p.stat().st_mtime_ns
            if rel in self.files and self.files[rel]["mtime"] == mt:
                continue
            text = p.read_text(encoding="utf-8")
            self._check_edit(rel, text)
            self._parse(rel, text, mt)
            if rel not in self.hashes or self.hashes[rel] != sha(text):
                self._remember(rel, text)
            changed = True
        for rel in [r for r in self.files if r not in seen]:
            self.log_event("file_deleted", path=rel)
            del self.files[rel]
            self.hashes.pop(rel, None)
            changed = True
        if changed:
            self._save_state("hashes.json", self.hashes)
            self._reindex()
            self._adopt_new_files()
        return changed

    def _check_edit(self, rel, current: str):
        """If a file differs from what she last wrote, the change is his: log it."""
        known = self.hashes.get(rel)
        if known is None:
            if current.strip():
                self.log_event("file_created", path=rel, by="owner")
            return
        if sha(current) == known:
            return
        shadow = self.state / "shadow" / rel
        old = shadow.read_text(encoding="utf-8") if shadow.exists() else ""
        diff = "".join(difflib.unified_diff(old.splitlines(True), current.splitlines(True),
                                            f"a/{rel}", f"b/{rel}", n=0))
        self.log_event("file_edit", path=rel, by="owner", diff=diff[:4000])

    def _remember(self, rel, text):
        self.hashes[rel] = sha(text)
        atomic_write(self.state / "shadow" / rel, text)

    def _parse(self, rel, text, mtime=None):
        fm, body = parse_md(text)
        facts = []
        for i, line in enumerate(body):
            f = parse_fact(line)
            if f:
                f.update(rel=rel, index=i)
                facts.append(f)
        self.files[rel] = {"fm": fm, "body": body, "facts": facts,
                           "mtime": mtime if mtime is not None else (self.root / rel).stat().st_mtime_ns}

    def modify(self, rel, mutate, new_fm=None):
        """
        The only write path. Read the file as it is NOW, log his edits if it
        changed, apply ours on top, write atomically, remember the new hash.
        """
        path = self.root / rel
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if path.exists():
            self._check_edit(rel, current)
        if current:
            fm, body = parse_md(current)
        else:
            fm = dict(new_fm or {})
            body = [f"# {fm['name']}", ""] if fm.get("name") and fm.get("kind") == "topic" else []
        mutate(fm, body)
        text = dump_md(fm, body)
        atomic_write(path, text)
        self._remember(rel, text)
        self._parse(rel, text)
        self._save_state("hashes.json", self.hashes)
        self._reindex()

    # ---- entities (derived from the files' headers)
    def _reindex(self):
        self.by_id, self.alias_map = {}, {}
        for rel, f in self.files.items():
            eid = f["fm"].get("id")
            if not eid:
                continue
            self.by_id[eid] = rel
            names = f["fm"].get("aliases", [])
            if isinstance(names, str):
                names = [names]
            for a in names:
                self.alias_map.setdefault(clean_alias(a), set()).add(eid)
        self.max_f = max([int(x["fid"][1:]) for f in self.files.values() for x in f["facts"]
                          if x["fid"]] + [0])

    def _adopt_new_files(self):
        """A file he created in people/ or areas/ becomes an entity: it gets an id."""
        for rel, f in list(self.files.items()):
            if f["fm"].get("id"):
                continue
            folder = rel.split("/")[0]
            if folder == "me" and rel[3:-3] in ME_TOPICS:
                kind, eid = "topic", rel[:-3]
            elif folder in ("people", "areas"):
                kind = "person" if folder == "people" else "area"
                eid = self.next_id(kind)
            else:
                continue
            heading = next((l[2:].strip() for l in f["body"] if l.startswith("# ")), None)
            name = f["fm"].get("name") or heading or Path(rel).stem.replace("-", " ")

            def mutate(fm, body, eid=eid, kind=kind, name=name):
                fm.update({"id": eid, "kind": kind, "name": name,
                           "aliases": fm.get("aliases") or ([clean_alias(name)] if kind != "topic" else []),
                           "state": "permanent", "created": now_iso(), "source": "owner-edit"})
            self.modify(rel, mutate)
        self._reindex()

    def next_id(self, kind) -> str:
        nums = [int(e.split("-")[1]) for e in self.by_id if e.startswith(kind + "-") and
                e.split("-")[1].isdigit()]
        return f"{kind}-{max(nums + [0]) + 1:04d}"

    def next_fid(self) -> str:
        self.max_f += 1
        return f"F{self.max_f:06d}"

    def fm(self, eid) -> dict:
        rel = self.by_id.get(eid)
        return self.files[rel]["fm"] if rel else {}

    def rel(self, eid):
        return self.by_id.get(eid)

    def lookup(self, alias) -> list:
        return sorted(self.alias_map.get(clean_alias(alias), ()))

    def aliases_of(self, eid) -> list:
        a = self.fm(eid).get("aliases", [])
        return [a] if isinstance(a, str) else list(a)

    def relations_of(self, eid) -> list:
        r = self.fm(eid).get("relations", [])
        return [r] if isinstance(r, str) else list(r)

    def mentioned(self, text) -> "dict[str, list[str]]":
        return {a: sorted(ids) for a, ids in self.alias_map.items() if a and has_phrase(text, a)}

    def entities(self):
        return [(eid, self.by_id[eid], self.files[self.by_id[eid]]["fm"]) for eid in sorted(self.by_id)]

    def _bootstrap(self):
        """Nothing is pre-created. Nobody is assumed to live here."""
        self._reindex()

    def ensure_principal(self, speaker):
        """A principal other than the owner gets their own file when they first speak."""
        eid = f"person-{slug(speaker)}"
        if eid not in self.by_id:
            fm0 = {"id": eid, "kind": "person", "name": speaker, "aliases": [],
                   "relations": [], "principal": speaker, "state": "permanent",
                   "created": now_iso(), "source": "first spoke"}
            self.modify(f"people/{slug(speaker)}.md",
                        lambda fm, body: body.extend([f"# {speaker}", ""]), new_fm=fm0)
        return eid

    def create_entity(self, kind, name, relation, line_id, permanent) -> str:
        eid = self.next_id(kind)
        folder = "areas" if kind == "area" else "people"
        base = slug(name)
        rel = f"{folder}/{base}.md"
        if (self.root / rel).exists():
            rel = f"{folder}/{base}-{slug(relation) if relation else eid}.md"
            # the first holder of the plain name gets a descriptive name too;
            # links use ids, so nothing breaks
            old_rel = f"{folder}/{base}.md"
            oid = self.files.get(old_rel, {}).get("fm", {}).get("id")
            if oid:
                orel = self.relations_of(oid)
                new_old = f"{folder}/{base}-{slug(orel[0]) if orel else oid}.md"
                os.replace(self.root / old_rel, self.root / new_old)
                self.hashes[new_old] = self.hashes.pop(old_rel, None)
                sh_old, sh_new = self.state / "shadow" / old_rel, self.state / "shadow" / new_old
                if sh_old.exists():
                    sh_new.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(sh_old, sh_new)
                self.files.pop(old_rel, None)
                self._parse(new_old, (self.root / new_old).read_text(encoding="utf-8"))
                self.log_event("file_renamed", path=old_rel, to=new_old, reason="shared name")
        state = "permanent" if permanent or kind != "area" else "provisional"
        fm0 = {"id": eid, "kind": kind, "name": name,
               "aliases": [clean_alias(name)] + ([clean_alias(relation)] if relation else []),
               "relations": [clean_alias(relation)] if relation else [],
               "state": state, "created": now_iso(), "source": line_id or "owner"}
        self.modify(rel, lambda fm, body: body.extend([f"# {name}", ""]), new_fm=fm0)
        self._reindex()
        return eid

    def add_alias(self, eid, alias, relation=False):
        a = clean_alias(alias)

        def mutate(fm, body):
            al = fm.get("aliases", [])
            al = [al] if isinstance(al, str) else al
            if a not in al:
                fm["aliases"] = al + [a]
            if relation:
                rl = fm.get("relations", [])
                rl = [rl] if isinstance(rl, str) else rl
                if a not in rl:
                    fm["relations"] = rl + [a]
        self.modify(self.rel(eid), mutate)
        self._reindex()

    # ---- facts
    def facts(self, rels=None, statuses=("active",)):
        out = []
        for rel, f in self.files.items():
            if rels is not None and rel not in rels:
                continue
            out += [x for x in f["facts"] if x["status"] in statuses]
        return out

    def rank_facts(self, facts, text, k):
        q = stems(text)
        return sorted(facts, key=lambda x: (len(q & stems(x["key"] + " " + x["value"])),
                                            x["src"] or ""), reverse=True)[:k]

    # ---- session: who was mentioned in the last N principal turns
    def session(self) -> list:
        return [e for t in self._load_state("turns.json", []) for e in t]

    def push_turn(self, eids):
        turns = self._load_state("turns.json", [])
        turns = (turns + [sorted(set(eids))])[-SESSION_TURNS:]
        self._save_state("turns.json", turns)

    def in_session(self, eid) -> bool:
        return eid in self.session()

    def jsonl(self, name, rec):
        append_jsonl(self.root / name, dict(rec, ts=now_iso()))

    def read_jsonl(self, name):
        p = self.root / name
        return [json.loads(x) for x in open(p, encoding="utf-8")] if p.exists() else []


_STORE: "Store | None" = None


def S() -> Store:
    global _STORE
    if _STORE is None:
        _STORE = Store(ROOT)
    else:
        _STORE.refresh()
    return _STORE


# ---------------------------------------------------------------- listing
def describe(st: Store, eid: str) -> str:
    rel = st.rel(eid)
    f = st.files[rel]
    fm, facts = f["fm"], [x for x in f["facts"] if x["status"] == "active"]
    keys = list(dict.fromkeys(x["key"] for x in facts))[:6]
    tail = f" (facts: {', '.join(keys)})" if keys else " (no facts yet)"
    kind = fm.get("kind")
    if kind == "topic":
        return f"his {eid.split('/')[1]}: {ME_TOPICS.get(eid.split('/')[1], '')}{tail}"
    rels = st.relations_of(eid)
    if kind == "area":
        return f"{fm.get('name')}: a project or topic area ({fm.get('state')}){tail}"
    who = f", {'/'.join(rels)}" if rels else ""
    return f"{fm.get('name')}{who} ({kind}){tail}"


def listing(st: Store, text: str) -> "list[tuple[str, str]]":
    ids = [e for e, rel, fm in st.entities() if st.files[rel]["facts"] or fm.get("kind") != "topic"]
    if len(ids) > LISTING_CAP:
        keep = {e for es in st.mentioned(text).values() for e in es} | set(st.session())
        ids = [e for e in ids if e in keep or e.startswith("me/")]
    return [(e, describe(st, e)) for e in ids]


# ---------------------------------------------------------------- extraction
EXTRACT_SYSTEM = """You extract durable facts for a personal memory. The SPEAKER said the STATEMENT.
Reply with ONE JSON object and nothing else: {"ops": [ ... ]}

Each op is one of:
  {"op": "add",     "about": REF, "topic": SHELF, "key": "<kind of fact, 1-4 words>", "value": "<the fact>"}
  {"op": "update",  "about": REF, "topic": SHELF, "key": "<a key from KNOWN FACTS>", "value": "<the new fact>"}
  {"op": "retract", "about": REF, "key": "<a key from KNOWN FACTS>"}

REF is one of:
  "self"                                  the speaker themself
  an id from ENTITIES, e.g. "person-0003"
  "active"                                the ACTIVE AREA, when the statement is about it
  {"new": "person", "name": "<name exactly as said>", "relation": "<relation to the speaker as said, or empty>"}
  {"new": "pet",    "name": "<name exactly as said>", "relation": "<e.g. dog, cat, or empty>"}
  {"new": "area",   "name": "<project or topic name exactly as said>"}

SHELF (only for "self"): one of SHELVES.

Rules:
- Only what the speaker states as true. Questions, greetings, hypotheticals and
  sarcasm get no op. Keep negation ("does not eat pork") and uncertainty
  ("might move in March") in the value.
- Use update when the statement changes a fact in KNOWN FACTS, reusing its exact
  key. Use retract when the speaker says a known fact is no longer true, or
  asks you to forget it. Otherwise add.
- When the speaker states their own name, that is a fact about "self" (key
  "name", shelf "profile"), never a new person.
- A fact about a named person, pet or project goes to that entity, not "self".
- Only create a new entity if its name appears in the statement. Never invent a
  name, and never create one that is already in ENTITIES.
- Do not repeat a fact that is already in KNOWN FACTS unchanged.
- Nothing worth remembering: {"ops": []}"""


def _speaker_self(speaker: str) -> str:
    return "me" if speaker == OWNER else f"person-{slug(speaker)}"


NAME_KEYS = {"name", "first name", "full name", "nickname", "goes by", "called"}


def _is_owner(ids) -> bool:
    return any(i.startswith("me/") for i in ids)


def _entity_block(st: Store, text: str) -> str:
    rows = [f"- {e}: {d}" for e, d in listing(st, text) if not e.startswith("me/")]
    return "\n".join(rows) or "(none)"


def _known_block(st: Store, text: str, self_id: str) -> str:
    targets = {e for es in st.mentioned(text).values() for e in es}
    active = st._load_state("active_area.json", None)
    if active:
        targets.add(active)
    rels = {st.rel(e) for e in targets if st.rel(e)}
    seen, rows = set(), []
    for x in st.rank_facts(st.facts(rels), text, 30):
        rows.append(x)
        seen.add(x["fid"])
    own = [r for r, f in st.files.items() if (r.startswith("me/") if self_id == "me"
                                               else f["fm"].get("id") == self_id)]
    for x in st.rank_facts(st.facts(set(own)), text, K_KNOWN):
        if x["fid"] not in seen:
            rows.append(x)
    out = []
    for x in rows:
        eid = st.files[x["rel"]]["fm"].get("id", x["rel"])
        ref = "self" if (eid.startswith("me/") and self_id == "me") or eid == self_id else eid
        out.append(f"- [{ref}] {x['key']}: {x['value']}")
    return "\n".join(out) or "(none)"


def _route(st: Store, ref, text: str, speaker: str, line_id: str, created: list):
    """Resolve an op's REF to an entity id, in code. (None, reason) sends it to the inbox."""
    self_id = _speaker_self(speaker)
    if ref in ("self", self_id, "me"):
        return self_id, "self"
    if ref == "active":
        active = st._load_state("active_area.json", None)
        return (active, "active area") if active in st.by_id else (None, "no active area")

    if isinstance(ref, dict) and ref.get("new") in ("person", "pet", "area"):
        kind = ref["new"]
        name = str(ref.get("name", "")).strip()
        relation = str(ref.get("relation", "")).strip()
        if not name or not has_phrase(text, name):
            return None, f"new {kind} name {name!r} not in the speaker's words"
        if relation and not has_phrase(text, relation):
            relation = ""
        matches = st.lookup(name)
        if _is_owner(matches):
            return (self_id, "his own name") if speaker == OWNER else \
                (None, f"{name!r} is the owner; {speaker} may not write his facts")
        if not matches:
            permanent = bool(re.search(r"\b(memory area|new area|an area for|area for)\b", text.lower()))
            eid = st.create_entity(kind, name, relation, line_id, permanent)
            created.append(eid)
            return eid, f"created {kind}"
        if len(matches) == 1:
            eid = matches[0]
            rels = st.relations_of(eid)
            if relation and rels and clean_alias(relation) not in rels:
                return None, (f"{name!r} exists as {eid} ({', '.join(rels)}); "
                              f"is this a different {name} ({relation})? ask")
            if relation and not rels:
                st.add_alias(eid, relation, relation=True)
            return eid, "existing entity by name"
        return _disambiguate(st, matches, text, name)

    if isinstance(ref, str) and ref.startswith("me/"):
        return (self_id, "self") if speaker == OWNER else (None, "not the speaker's own entity")
    if isinstance(ref, str) and ref in st.by_id:
        eid = ref
        present = [a for a in st.aliases_of(eid) if has_phrase(text, a)]
        if any(len(st.lookup(a)) == 1 for a in present):
            return eid, "alias in words"
        if present:
            return _disambiguate(st, st.lookup(present[0]), text, present[0])
        others = sorted({e for es in st.mentioned(text).values() for e in es
                         if e != eid and not e.startswith("me/")})
        if others:
            # The words name someone else. The model picked the wrong entity;
            # recency must never override a name that is actually in his words.
            return None, f"model chose {eid} but the words name {', '.join(others)}"
        if st.in_session(eid):
            return eid, "no name in words; in this conversation"
        return None, f"model chose {eid} but nothing in the words or conversation points to it"

    if isinstance(ref, str):
        matches = st.lookup(ref)
        if _is_owner(matches) and speaker == OWNER:
            return self_id, "his own name"
        if len(matches) == 1:
            return matches[0], "name lookup"
        if matches:
            return _disambiguate(st, matches, text, ref)
    return None, f"unresolvable reference {json.dumps(ref)[:80]}"


def _disambiguate(st: Store, matches, text, name):
    """Several entities share the name. Qualifier in his words, then recency, else ask."""
    by_qualifier = [e for e in matches
                    if any(has_phrase(text, a) and len(st.lookup(a)) < len(matches)
                           for a in st.aliases_of(e) if a != clean_alias(name))]
    if len(by_qualifier) == 1:
        return by_qualifier[0], f"{name!r} is ambiguous; qualifier in words picks it"
    recent = [e for e in matches if st.in_session(e)]
    if len(recent) == 1:
        return recent[0], f"{name!r} is ambiguous; the one in this conversation"
    return None, f"{name!r} is ambiguous between {', '.join(matches)}: ask"


def extract(user_text: str, verbose: bool = True, speaker: str = None, _line: str = None):
    """Thread-safe entry point; the suite checks this signature, so it stays plain."""
    with LOCK:
        return _extract(user_text, verbose, speaker, _line)


def _extract(user_text: str, verbose: bool = True, speaker: str = None, _line: str = None):
    """
    Log first, always. Then triage by speaker in code: principals go to
    extraction; everyone else is an observation, with no model call at all.
    _line re-runs extraction for an existing line (a correction, or an inbox
    item re-fed after he answered), so its facts keep pointing at that line.
    """
    speaker = speaker or OWNER
    st = S()
    line_id = _line or st.log_utterance(speaker, user_text)
    if speaker not in PRINCIPALS:
        if verbose:
            print(f"        (observation from {speaker})")
        return {"line": line_id, "observation": True}

    self_id = _speaker_self(speaker)
    if speaker != OWNER:
        st.ensure_principal(speaker)
    seen_rb, seen_in = len(st.read_jsonl("readback.jsonl")), len(st.read_jsonl("inbox.jsonl"))
    active = st._load_state("active_area.json", None)
    active_desc = f"{active} {st.fm(active).get('name')}" if active in st.by_id else "none"
    prompt = (f"SPEAKER: {speaker}{' (the owner)' if speaker == OWNER else ''}\n"
              f"ACTIVE AREA: {active_desc}\n"
              f"SHELVES: {', '.join(ME_TOPICS)}\n\n"
              f"ENTITIES\n{_entity_block(st, user_text)}\n\n"
              f"KNOWN FACTS\n{_known_block(st, user_text, self_id)}\n\n"
              f"STATEMENT\n{user_text}")
    raw = llm(EXTRACT_MODEL, EXTRACT_SYSTEM, prompt)
    obj = parse_json(raw)
    if obj is None or not isinstance(obj.get("ops", None), list):
        st.jsonl("routing.jsonl", {"line": line_id, "op": raw[:300], "decision": "unparseable",
                                   "reason": "reply was not {ops:[...]}"})
        if STRICT_PARSE:
            raise ParseError(f"unparseable extraction: {raw[:120]}")
        return {"line": line_id, "ops": []}

    touched, created, applied = set(), [], []
    for op in obj["ops"][:12]:
        if not isinstance(op, dict) or op.get("op") not in ("add", "update", "retract"):
            _decide(st, line_id, op, "rejected", "malformed op")
            continue
        # Authority (ADR-0060): a household member writes only their own entity.
        if speaker != OWNER and op.get("about", "self") not in ("self", self_id):
            _decide(st, line_id, op, "observed", f"{speaker} may only write {self_id}")
            continue
        eid, reason = _route(st, op.get("about", "self"), user_text, speaker, line_id, created)
        if eid is None:
            st.jsonl("inbox.jsonl", {"line": line_id, "text": user_text, "reason": reason, "op": op})
            _decide(st, line_id, op, "inbox", reason)
            continue
        key = norm(str(op.get("key", "")))[:60]
        value = re.sub(r"\s+", " ", str(op.get("value", ""))).strip()
        if not key or (op["op"] != "retract" and not value):
            _decide(st, line_id, op, "rejected", "empty key or value")
            continue
        if eid == "me":
            topic = str(op.get("topic", "")).lower().strip()
            rel = f"me/{topic if topic in ME_TOPICS else 'other'}.md"
            scope = [r for r in st.files if r.startswith("me/")]
        else:
            rel = st.rel(eid)
            scope = [rel]
        if eid == "me" and key in NAME_KEYS:
            rel = "me/profile.md"
        result = _apply(st, rel, scope, op["op"], key, value, speaker, line_id)
        if eid == "me" and key in NAME_KEYS and op["op"] != "retract" and result:
            st.add_alias("me/profile", value)          # "Antonio collects coins" now routes to him
        if result:
            applied.append(result)
            touched.add(result[3])
        _decide(st, line_id, op, (result[3] if result else rel)[:-3], reason)
        if eid.startswith("area-"):
            _touch_area(st, eid, line_id)

    for eid in created:
        fm = st.fm(eid)
        rels = st.relations_of(eid)
        extra = f", your {rels[0]}" if rels else ""
        extra += " (provisional)" if fm.get("state") == "provisional" else ""
        _readback(st, line_id, f"New {fm.get('kind')}: {fm.get('name')}{extra}.")
    for kind, key, value, _rel in applied:
        if kind == "update":
            _readback(st, line_id, f"Got it: {key} is now {value}.")

    ment = {e for es in st.mentioned(user_text).values() for e in es}
    st.push_turn([e for e in ment | {st.files[r]["fm"].get("id") for r in touched}
                  if e and e != self_id and not e.startswith("me/")])
    readbacks = [r["text"] for r in st.read_jsonl("readback.jsonl")[seen_rb:]]
    inboxed = [r["reason"] for r in st.read_jsonl("inbox.jsonl")[seen_in:]]
    if verbose:
        for t in readbacks:
            print(f"        (read-back) {t}")
        for t in inboxed:
            print(f"        (inbox) {t}")
    return {"line": line_id, "ops": obj["ops"], "touched": sorted(touched),
            "readbacks": readbacks, "inbox": inboxed}


def _touch_area(st, eid, line_id):
    """An area used again in a later session becomes permanent. It is also now the active one."""
    st._save_state("active_area.json", eid)
    fm = st.fm(eid)
    if fm.get("state") == "provisional" and fm.get("source", "").startswith("L") \
            and fm["source"] in st.lines and st.session_of(fm["source"]) != st.session_of(line_id):
        st.modify(st.rel(eid), lambda f, b: f.update(state="permanent"))


def _decide(st, line_id, op, decision, reason):
    st.jsonl("routing.jsonl", {"line": line_id, "op": op, "decision": decision, "reason": reason})


def _readback(st, line_id, text):
    st.jsonl("readback.jsonl", {"line": line_id, "text": text})


def _apply(st: Store, rel, scope, op, key, value, author, line_id):
    """Change one fact line in place. Nothing is deleted; history stays in the log."""
    current = [x for x in st.facts(set(scope)) if x["key"] == key]
    if op == "add":
        if any(norm(base_value(x["value"])) == norm(value) for x in current):
            return None                                     # already known
        fid = st.next_fid()
        st.modify(rel, lambda fm, body: body.append(fact_line(key, value, fid, author, line_id)),
                  new_fm=_new_fm_for(rel))
        return ("add", key, value, rel)
    if op == "update":
        if not current:
            return _apply(st, rel, scope, "add", key, value, author, line_id)
        old = current[-1]
        if norm(base_value(old["value"])) == norm(value):
            return None
        fid = st.next_fid()
        prev = base_value(old["value"])

        def mutate(fm, body, old=old):
            body[old["index"]] = fact_line(key, f"{value} (previously {prev})", fid, author, line_id)
        st.modify(old["rel"], mutate)
        return ("update", key, value, old["rel"])
    if op == "retract":
        if not current:
            return None
        for x in current:
            def mutate(fm, body, x=x):
                body[x["index"]] = fact_line(x["key"], x["value"], x["fid"] or st.next_fid(),
                                             x["author"], x["src"], retracted=True)
            st.modify(x["rel"], mutate)
        return ("retract", key, None, current[0]["rel"])


def _new_fm_for(rel):
    if rel.startswith("me/"):
        t = rel[3:-3]
        return {"id": rel[:-3], "kind": "topic", "name": t, "description": ME_TOPICS.get(t, "")}
    return {}


# ---------------------------------------------------------------- answering
SELECT_SYSTEM = """Choose which memory files could hold the answer to the question.
Reply with ONE JSON object and nothing else: {"files": ["<id>", ...]}
Up to 3 ids, copied exactly from LISTING. {"files": []} if none could."""

ANSWER_SYSTEM = """You answer the owner's question from memory, in one or two short spoken sentences.

You are given:
  FACTS         what principals told her, from the files chosen for this question
  THEIR WORDS   what principals actually said, numbered in order. These are the
                evidence. When lines disagree, the later line wins.
  OBSERVATIONS  what others said, or what appeared on a TV or screen, with the
                source. These are NOT the owner's statements.

Reply with ONE JSON object and nothing else:
  {"answer": "...", "quote": "<words copied exactly from one line of THEIR WORDS or OBSERVATIONS>", "basis": "their_words" | "observation" | "none"}

Rules:
- Answers about the owner or household come from THEIR WORDS (and FACTS that agree).
- If only OBSERVATIONS have it, say where it came from and that he has not told
  you himself, e.g. "The TV mentioned 1234, but you've never told me your code."
- If nothing supports an answer, the answer is exactly "I don't know." with basis "none".
- Never add a detail that is not in the lines."""

_SELECTED: dict = {}


def _select(st: Store, question: str):
    """The model picks files from the listing; code keeps only real ids and adds named ones."""
    if question in _SELECTED:
        return _SELECTED[question]
    items = listing(st, question)
    valid = {e for e, _d in items}
    named = sorted({e for es in st.mentioned(question).values() for e in es})
    q = stems(question)
    overlap = sorted(((len(q & stems(d + " " + e.replace("/", " "))), e) for e, d in items), reverse=True)
    keyword = [e for n, e in overlap if n][:3]
    chosen = []
    if items:
        raw = llm(SELECT_MODEL, SELECT_SYSTEM,
                  "LISTING\n" + "\n".join(f"- {e}: {d}" for e, d in items) +
                  f"\n\nQUESTION: {question}")
        obj = parse_json(raw) or {}
        chosen = [f for f in (obj.get("files") or []) if isinstance(f, str) and f in valid][:3]
    out = (list(dict.fromkeys(named + chosen + keyword)), named, chosen)
    _SELECTED[question] = out
    return out


def _gather(question: str):
    st = S()
    files, named, chosen = _select(st, question)
    rels = {st.rel(e) for e in files if st.rel(e)}
    facts = st.facts(rels, statuses=("active", "retracted"))
    if len(facts) > FACT_BUDGET:
        facts = st.rank_facts(facts, question, FACT_BUDGET)
    words = {ln["id"]: ln for ln in st.search_lines(question, True, K_LOG)}
    for x in sorted(facts, key=lambda x: x["src"] or "", reverse=True)[:SOURCE_LINES]:
        ln = st.lines.get(x["src"] or "")
        if ln and ln["status"] == "ok":
            words[ln["id"]] = ln
    obs = st.search_lines(question, False, K_OBS)
    return (facts, sorted(words.values(), key=lambda l: l["n"]), sorted(obs, key=lambda l: l["n"]),
            {"files": files, "named": named, "chosen": chosen})


def _fact_block(facts):
    st = S()
    out = []
    for x in facts:
        fm = st.files[x["rel"]]["fm"]
        who = "the owner" if x["rel"].startswith("me/") else fm.get("name", x["rel"])
        gone = " [NO LONGER TRUE]" if x["status"] == "retracted" else ""
        out.append(f"- {who}: {x['key']}: {x['value']}{gone}")
    return "\n".join(out) or "(none)"


@_locked
def xask(question: str, trace: dict = None) -> str:
    trace = trace if trace is not None else {}
    facts, words, obs, sel = _gather(question)
    word_lines = [f"[{l['n']}] ({l['speaker']}) {l['text']}" for l in words]
    obs_lines = [f"[{l['n']}] (source: {l['speaker']}) {l['text']}" for l in obs]
    prompt = (f"FACTS\n{_fact_block(facts)}\n\n"
              f"THEIR WORDS\n{chr(10).join(word_lines) or '(none)'}\n\n"
              f"OBSERVATIONS\n{chr(10).join(obs_lines) or '(none)'}\n\n"
              f"QUESTION: {question}")
    trace.update({"excerpts": word_lines + obs_lines, "selected": sel, "facts_retrieved": len(facts)})
    raw = llm(ANSWER_MODEL, ANSWER_SYSTEM, prompt)
    obj = parse_json(raw) or {}
    answer = str(obj.get("answer") or raw).strip()
    quote = str(obj.get("quote") or "").strip()
    basis = str(obj.get("basis") or "none")
    trace.update({"quote": quote, "basis": basis, "quote_ok": None, "downgraded": False})

    if not QUOTE_CHECK or is_idk(answer):
        return answer
    pool = [l["text"] for l in words] if basis == "their_words" else \
           [l["text"] for l in obs] if basis == "observation" else []
    ok = bool(quote) and any(norm(quote) in norm(t) for t in pool)
    if ok and basis == "observation":
        # An observation must be answered as one: attributed, never as his fact.
        ok = bool(re.search(r"\b(tv|television|screen|guest|someone|heard|saw|mentioned|said|"
                            r"never told|haven't told|not told|didn't tell)\b", answer.lower()))
    trace["quote_ok"] = ok
    if not ok:
        trace.update({"downgraded": True, "unverified_answer": answer})
        return "I don't know."
    return answer


@_locked
def xask_facts(question: str) -> str:
    """Facts only, no log lines, no check. The comparison the suite reports."""
    facts, _w, _o, _s = _gather(question)
    raw = llm(ANSWER_MODEL, "Answer the owner's question from these facts only, in one short "
              "sentence. If they do not contain the answer, reply exactly: I don't know.\n"
              'Reply as JSON: {"answer": "..."}',
              f"FACTS\n{_fact_block(facts)}\n\nQUESTION: {question}")
    obj = parse_json(raw) or {}
    return str(obj.get("answer") or raw).strip()


@_locked
def recall(question: str):
    """
    For a live conversation: what she remembers that bears on this turn, as a
    prompt block. Same retrieval as xask, without the separate answer call.
    """
    facts, words, obs, sel = _gather(question)
    word_lines = [f"[{l['n']}] ({l['speaker']}) {l['text']}" for l in words]
    obs_lines = [f"[{l['n']}] (source: {l['speaker']}) {l['text']}" for l in obs]
    block = (f"FACTS\n{_fact_block(facts)}\n\n"
             f"HIS WORDS (evidence; the later line wins)\n{chr(10).join(word_lines) or '(none)'}\n\n"
             f"OBSERVATIONS (others, TV, screen, web - never his facts)\n"
             f"{chr(10).join(obs_lines) or '(none)'}")
    return block, {"files": sel["files"], "lines": len(words) + len(obs)}


@_locked
def observe(source: str, text: str):
    """Anything that is not a principal speaking: screen, web, TV, guests."""
    if text and text.strip():
        S().log_utterance(source, text.strip())


@_locked
def note_own(text: str):
    """Her own reply. Kept in the log for the record, excluded from every search."""
    if text and text.strip():
        S().log_utterance(ASSISTANT, text.strip())


@_locked
def read_facts() -> "dict[str, str]":
    return {f"{x['fid'] or x['rel'] + ':' + str(x['index'])} {x['rel']}: {x['key']}": x["value"]
            for x in S().facts()}


# ---------------------------------------------------------------- corrections (ADR-0063)
def _retract_from_line(st, line_id):
    for x in [x for x in st.facts() if x["src"] == line_id]:
        def mutate(fm, body, x=x):
            body[x["index"]] = fact_line(x["key"], x["value"], x["fid"], x["author"],
                                         x["src"], retracted=True)
        st.modify(x["rel"], mutate)


@_locked
def void_line(line_id: str):
    """Strike a line: noise or accidental speech. Kept in the log, excluded, facts from it retracted."""
    st = S()
    st.log_event("correction", line=line_id, void=True)
    _retract_from_line(st, line_id)


@_locked
def correct_line(line_id: str, text: str):
    """Fix a transcript line. The original stays in the log; facts from it are rebuilt from the fix."""
    st = S()
    if line_id not in st.lines:
        raise KeyError(line_id)
    st.log_event("correction", line=line_id, text=text)
    _retract_from_line(st, line_id)
    if st.lines[line_id]["principal"]:
        _extract(text, verbose=True, speaker=st.lines[line_id]["speaker"], _line=line_id)


@_locked
def create_person(name: str, relation: str = "", kind: str = "person") -> str:
    """His explicit answer to "a different Sam?": create the entity he named."""
    return S().create_entity(kind, name, relation, None, True)


@_locked
def refeed(line_id: str):
    """Re-run extraction for an inbox line, after he has answered its question."""
    st = S()
    ln = st.lines[line_id]
    st.jsonl("inbox.jsonl", {"line": line_id, "resolved": True, "text": ln["text"], "reason": "re-fed"})
    return _extract(ln["text"], verbose=True, speaker=ln["speaker"], _line=line_id)


# ---------------------------------------------------------------- CLI
def cmd_inspect():
    st = S()
    print(f"memory at {st.root}\n")
    print("FILES")
    for eid, rel, fm in st.entities():
        n = sum(1 for x in st.files[rel]["facts"] if x["status"] == "active")
        print(f"  {eid:<16} {rel:<30} {n:>3} facts  {describe(st, eid)[:70]}")
    print(f"\nACTIVE AREA: {st._load_state('active_area.json', None) or 'none'}")
    inbox = st.read_jsonl("inbox.jsonl")
    resolved = {r["line"] for r in inbox if r.get("resolved")}
    print("\nINBOX")
    for r in [r for r in inbox if r["line"] not in resolved][-15:]:
        print(f"  {r['line']} {r['reason']}\n        {r['text'][:90]}")
    print("\nREAD-BACKS")
    for r in st.read_jsonl("readback.jsonl")[-15:]:
        print(f"  {r['line']} {r['text']}")
    counts = {}
    for r in st.read_jsonl("routing.jsonl"):
        counts[r["decision"]] = counts.get(r["decision"], 0) + 1
    print("\nROUTING  " + ", ".join(f"{d}: {n}" for d, n in sorted(counts.items())))
    if st.problems:
        print("\nPROBLEMS\n  " + "\n  ".join(st.problems))


def cmd_chat():
    speaker = OWNER
    if "--speaker" in sys.argv:
        speaker = sys.argv[sys.argv.index("--speaker") + 1]
    print(f"poc6 memory at {ROOT}, speaking as {speaker}. Models: extract {EXTRACT_MODEL}, "
          f"answer {ANSWER_MODEL}.")
    print("Statements are remembered. End with ? to ask.  "
          "Commands: :inspect  :void L000012  :fix L000012 new text  :as <speaker>\n"
          "          :person <name> [relation]  :refeed L000012  :quit\n")
    while True:
        try:
            t = input(f"{speaker}> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not t:
            continue
        try:
            if t in (":quit", ":q"):
                return
            if t == ":inspect":
                cmd_inspect()
            elif t.startswith(":as "):
                speaker = t[4:].strip()
            elif t.startswith(":person "):
                parts = t.split()
                print(f"  created {create_person(parts[1], ' '.join(parts[2:]))}")
            elif t.startswith(":refeed "):
                refeed(t.split()[1])
            elif t.startswith(":void "):
                void_line(t.split()[1])
                print("  struck")
            elif t.startswith(":fix "):
                _c, lid, new = t.split(" ", 2)
                correct_line(lid, new)
            elif t.endswith("?"):
                trace = {}
                a = xask(t, trace)
                print(f"  her: {a}")
                print(f"       (read {', '.join(trace['selected']['files']) or 'no files'}; "
                      f"{len(trace['excerpts'])} lines)")
                if trace.get("downgraded"):
                    print(f"       (unverified, withheld: {trace.get('unverified_answer')})")
            else:
                r = extract(t, verbose=True, speaker=speaker)
                if r.get("touched"):
                    print(f"        (filed in {', '.join(r['touched'])})")
        except (ContextOverflow, ParseError, requests.RequestException, KeyError) as exc:
            print(f"  !! {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    ROOT = Path(os.environ.get("MEM6_DIR") or (_here / "memory6"))
    cmds = {"chat": cmd_chat, "inspect": cmd_inspect}
    mode = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "chat"
    if mode not in cmds:
        print(f"usage: {sys.argv[0]} [{'|'.join(cmds)}] [--speaker NAME]")
        sys.exit(1)
    cmds[mode]()
