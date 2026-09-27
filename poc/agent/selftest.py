#!/usr/bin/env python3
"""
selftest.py - exercises every deterministic part without hardware.

    python3 selftest.py

No GPU, no X server, no tesseract, no network. Runs in a second. If this
fails, nothing above it is worth running. It is also the record of what each
module is supposed to do.
"""

import json
import os
import sys
import tempfile
import time

os.environ["OBS_DIR"] = tempfile.mkdtemp()      # never touch real memory

import windows as W          # noqa: E402
import screenread as S       # noqa: E402
import recall as R           # noqa: E402
import research as X         # noqa: E402
import watcher as T          # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(f"  {'ok  ' if cond else 'FAIL'} {name}{('  ' + str(detail)) if not cond and detail else ''}")
    if not cond:
        fails += 1


# ------------------------------------------------------------------ windows
print("windows.py")
WMCTRL = """0x05000007  0 0    0    1720 1440 Navigator.firefox sakura PLE Infinite RTX 5090 - Mozilla Firefox
0x03400003  0 1720 0    1000 1440 code.Code        sakura poc5.py - fendlera - Visual Studio Code
0x02a00004  0 2720 0    720  1440 gnome-terminal-server.Gnome-terminal sakura antonio@sakura: ~/poc
0x01000001 -1 0    1400 3440 40   gnome-shell.Gnome-shell sakura Top Bar
0x04000002  1 0    0    1720 1440 Navigator.firefox sakura Other Desktop - Mozilla Firefox
0x05500009  0 100  100  120  60   Navigator.firefox sakura tooltip
0x06000001  0 0    0    1720 1440 evince.Evince    sakura manual.pdf
"""
rows = W.parse_wmctrl(WMCTRL, desktop="0")
check("skips sticky (-1) and other desktops", {r["wid"] for r in rows} ==
      {"0x5000007", "0x3400003", "0x2a00004", "0x5500009", "0x6000001"},
      {r["wid"] for r in rows})
check("id normalised (leading zeros dropped)", rows[0]["wid"] == "0x5000007")
stack = ["0x6000001", "0x5000007", "0x3400003", "0x2a00004"]   # evince at BACK
wins = W.resolve(rows, stack, active="0x3400003", screen_w=3440, screen_h=1440)
ids = [w.wid for w in wins]
check("tiny tooltip dropped", "0x5500009" not in ids)
check("evince fully behind firefox dropped", "0x6000001" not in ids, ids)
check("three visible windows, back to front", ids == ["0x5000007", "0x3400003", "0x2a00004"], ids)
check("active flagged", [w.active for w in wins] == [False, True, False])
check("roles", [w.role for w in wins] == ["browser", "editor", "terminal"])
check("app names from class, not instance", [w.app for w in wins] == ["firefox", "code", "gnome-terminal"],
      [w.app for w in wins])
check("reverse-DNS class -> last segment",
      W.Win("0x9", 0, 0, 500, 500, "org.gnome.Nautilus.Org.gnome.Nautilus", "Home").app == "nautilus")
check("pick 'the web page' -> firefox", W.pick(wins, "what does the web page say").app == "firefox")
check("pick 'terminal'", W.pick(wins, "read me the terminal").role == "terminal")
check("pick 'vs code'", W.pick(wins, "what does it say in vs code").role == "editor")
check("pick by title word", W.pick(wins, "the fendlera thing").role == "editor")
check("pick 'this' -> active", W.pick(wins, "summarise this").active)
check("pick nothing", W.pick(wins, "hello there") is None)

# ------------------------------------------------------------------ screenread
print("screenread.py")
def tsvrow(left, top, text, w=None, h=20, conf=95):
    w = w or 11 * len(text)
    return f"5\t1\t1\t1\t1\t1\t{left}\t{top}\t{w}\t{h}\t{conf}\t{text}\n"

HDR = "level\tpage\tblock\tpar\tline\tword\tleft\ttop\twidth\theight\tconf\ttext\n"
# Two spec cards side by side (PLE layout), then a card below the left one.
TSV = HDR
TSV += tsvrow(140, 430, "CPU")                                   # left card label
TSV += tsvrow(140, 450, "AMD") + tsvrow(190, 450, "Ryzen") + tsvrow(260, 450, "7")
TSV += tsvrow(800, 440, "CPU") + tsvrow(845, 440, "Cooler")      # right card label, same row
TSV += tsvrow(800, 462, "Jonsbo") + tsvrow(880, 462, "TF3")
TSV += tsvrow(140, 560, "Motherboard")                          # next left card
TSV += tsvrow(140, 582, "Gigabyte") + tsvrow(240, 582, "X870E")
TSV += tsvrow(10, 900, "$674.10") + tsvrow(100, 900, "ASUS") + tsvrow(160, 900, "PN53")
TSV += tsvrow(10, 950, "junk", conf=20)
TSV += tsvrow(10, 990, "|", conf=90)
text, blocks = S.parse_tsv(TSV)
tl = text.splitlines()
check("column gap splits a visual row into two lines",
      "CPU" in tl and "CPU Cooler" in tl and not any("CPU CPU" in l for l in tl), tl)
check("reading order top then left", tl[:2] == ["CPU", "CPU Cooler"], tl[:2])
check("low-confidence and noise dropped", "junk" not in text and "|" not in text)
pairs = [b.spec_pair() for b in blocks]
check("left card grouped as label + value", ("CPU", "AMD Ryzen 7") in pairs, pairs)
check("right card grouped separately", ("CPU Cooler", "Jonsbo TF3") in pairs, pairs)
check("next card down is its own block", ("Motherboard", "Gigabyte X870E") in pairs, pairs)
priced = [b for b in blocks if b.prices]
check("priced block parsed, no spec pair", len(priced) == 1 and priced[0].prices == [674.10]
      and priced[0].spec_pair() is None, [(b.lines, b.prices) for b in priced])
# side-by-side panels at the same height must not merge
TSV2 = HDR + tsvrow(100, 300, "total") + tsvrow(160, 300, "1.85") + \
       tsvrow(1200, 300, "-") + tsvrow(1220, 300, "libreoffice-writer:") + tsvrow(1420, 300, "Untitled")
text2, _ = S.parse_tsv(TSV2)
check("terminal and editor at the same height stay separate lines",
      text2.splitlines() == ["total 1.85", "- libreoffice-writer: Untitled"], text2.splitlines())
# occlusion geometry
back = W.Win("0xa", 57, 70, 3076, 1202, "libreoffice.libreoffice-writer", "Untitled 1")
front = W.Win("0xb", 1326, 32, 2114, 1342, "code.Code", "VS Code")
cov = S.occluders(back, [front])
check("occluder rect in window coords", cov == [(1269, 0, 3076, 1202)], cov)
vf = S.visible_fraction(back, cov)
check("libreoffice ~41% visible behind vs code", 0.40 < vf < 0.42, vf)
tiny = W.Win("0xc", 1400, 600, 584, 212, "soffice.Soffice", "Tip of the Day")
check("dialog fully behind vs code -> 0% visible", S.visible_fraction(tiny, S.occluders(tiny, [front])) == 0.0)
check("nothing in front -> fully visible", S.visible_fraction(front, S.occluders(front, [])) == 1.0)
w_bank = W.Win("0x1", 0, 0, 800, 600, "Navigator.firefox", "NetBank - Log on")
w_ok = W.Win("0x2", 0, 0, 800, 600, "Navigator.firefox", "PLE Computers")
check("exclusion by title, not focus", S.excluded(w_bank, S.EXCLUDE_DEFAULT) and
      not S.excluded(w_ok, S.EXCLUDE_DEFAULT))
rd = [S.WindowText(win=w_ok, text="short line\nA proper first content line here"),
      S.WindowText(win=w_bank, excluded=True),
      S.WindowText(win=tiny, hidden=True)]
sv = S.survey(rd)
check("survey names excluded window without content",
      "[not read - excluded window]" in sv and "PLE Computers" in sv and "proper first" in sv, sv)
check("survey marks a hidden window", "[mostly behind other windows]" in sv)

# ------------------------------------------------------------------ recall
print("recall.py")
m = R.Memory()
t = 1_000_000.0
page = "PLE Computers Graphics Cards | Gigabyte GeForce RTX 5090 AORUS MASTER $4,299 Add to Cart | " \
       "MSI RTX 5080 Gaming Trio $1,399 Add to Cart"
e1, new1 = m.see(page, now=t)
e2, new2 = m.see(page + " ASUS TUF RTX 5080 $1,799 In stock Perth", now=t + 20)
check("first screen is a new episode", new1)
check("scrolled page merges into same episode", not new2 and e2["id"] == e1["id"] and e2["screens"] == 2,
      (new2, e2["screens"]))
e3, new3 = m.see("Skyscanner Flights Perth PER to Manila MNL Economy 1 adult from $1,342", now=t + 40)
check("different page is a new episode", new3 and len(m.episodes) == 2)
hits = m.search("rtx 5080", now=t + 60)
check("search finds the GPU episode", hits and hits[0]["id"] == e1["id"], [h["id"] for h in hits])
check("search misses what was never seen", m.search("scuba diving", now=t + 60) == [])
check("phrase carries time and confidence",
      "minute" in m.phrase("skyscanner manila", now=t + 600) and "clearly" in m.phrase("skyscanner manila", now=t + 600),
      m.phrase("skyscanner manila", now=t + 600))
check("old memory rejects a half-matching cue", m.search("perth weather", now=t + 3 * 86400) == [])
check("recent memory accepts the same half-matching cue", len(m.search("perth weather", now=t + 60)) >= 1)
check("old memory found with a strong cue", len(m.search("skyscanner manila", now=t + 3 * 86400)) == 1)

i = R.Interests()
check("bare noun refused", i.add("car") is None)
check("single word refused", i.add("graphics") is None)
x = i.add("rtx 5080 under 1500")
check("real want filed", x is not None and x["phrase"] == "rtx 5080 under 1500")
check("duplicate refused", i.add("RTX 5080 under 1500") is None)
fired = i.check(e1)
check("interest fires on matching episode under the ceiling", len(fired) == 1, fired)
check("ceiling parsed", x["terms"] == ["rtx", "5080"] and x["ceiling"] == 1500.0, (x["terms"], x["ceiling"]))
y = i.add("rtx 5090 under 2k")
check("'2k' ceiling parsed", y and y["ceiling"] == 2000.0 and y["terms"] == ["rtx", "5090"])
check("5090 at $4,299 does not fire 'under 2k' despite a cheap 5080 on the same page",
      i.check(m.episodes[0]) == [], i.check(m.episodes[0]))
i.forget("5090")
check("fires once per episode", i.check(e1) == [])
check("does not fire on unrelated episode", i.check(e3) == [])
check("word boundary: 'cart' does not match 'car'", R.has_terms("add to cart", ["car"]) == [])
check("forget by phrase", i.forget("5080") and i.all() == [])

# ------------------------------------------------------------------ research
print("research.py")
src = X.Source(1, "GPU page", "https://www.ple.com.au/x",
               text="Gigabyte AORUS GeForce RTX 5090 MASTER 32G. Price: $7,999.00 inc GST. In stock.")
src2 = X.Source(2, "US review", "https://www.tomshardware.com/x",
                text="The RTX 5090 launched at an MSRP of $1,999 in the US.")
raw = json.dumps({"points": [
    {"aspect": "price", "point": "Listed at $7,999", "value": 7999, "currency": None,
     "quote": "Price: $7,999.00 inc GST"},
    {"aspect": "stock", "point": "It is in stock", "value": None, "quote": "In stock."},
    {"aspect": "price", "point": "Costs $6,500", "value": 6500, "quote": "only $6,500 today"},
]})
pts = X.parse_points(raw, src)
check("three points parsed", len(pts) == 3)
check("quote verified against page", pts[0].verified and pts[1].verified)
check("fabricated quote rejected", not pts[2].verified)
check("currency inferred from .au", pts[0].currency == "AUD")
pts2 = X.parse_points(json.dumps({"points": [{"aspect": "price", "point": "US MSRP $1,999",
                                              "value": 1999, "currency": "USD",
                                              "quote": "MSRP of $1,999 in the US"}]}), src2)
res = X.reconcile(pts + pts2, want_ccy="AUD")
check("rejected counted", len(res["rejected"]) == 1)
n = res["numeric"]
check("USD dropped when AUD requested", n is None or all(p.currency != "USD" for p in n["inliers"]))
res_any = X.reconcile(pts + pts2, want_ccy=None)
n2 = res_any["numeric"]
check("numeric summary from two verified values", n2 is not None and n2["total"] == 2, n2 and n2["total"])
check("outlier flagged, not averaged", n2 is not None and len(n2["outliers"]) == 1 and n2["agree"] == 1,
      n2 and (n2["agree"], len(n2["outliers"])))
cl = X.cluster([p for p in pts + pts2 if p.verified])
check("price points cluster by aspect across domains",
      any(c["aspect"] == "price" and len(c["domains"]) == 2 for c in cl), [(c["aspect"], len(c["domains"])) for c in cl])
check("garbage json -> no points", X.parse_points("not json", src) == [])
check("markdown fences stripped", len(X.parse_points("```json\n" + raw + "\n```", src)) == 3)

# ------------------------------------------------------------------ watcher
print("watcher.py")
r = T.redact("card 4111 1111 1111 1111 key sk-abcdefghijklmnopqrstuvwxyz mail a@b.com password: hunter2")
check("redaction", "[card]" in r and "[key]" in r and "[email]" in r and "hunter2" not in r, r)
import numpy as np
a = np.zeros((32, 64), dtype=np.float32)
b = a.copy(); b[0, 0] = 255          # one pixel - an animated cursor
c = a + 40                           # whole screen shifted - a scroll
check("one-pixel change ignored", not T.changed(a, b))
check("scroll detected", T.changed(a, c))

# ------------------------------------------------------------------ agent
print("agent.py")
os.environ["AGENT_LOG"] = os.path.join(os.environ["OBS_DIR"], "agent_log.jsonl")
import agent as A            # noqa: E402

class _Stub(A.Tools):
    def __init__(self):
        self.calls = []; self.mem, self.ints = R.Memory(), R.Interests()
        self._frame = self._reads = None
    def new_turn(self): pass
    def read_screen(self):
        self.calls.append("read_screen")
        return {"source": "[read] screen OCR", "content": "- firefox: PLE Pyro prebuilt, only price $13,499"}
    def research(self, question, depth="quick"):
        self.calls.append(("research", question))
        return {"source": "[web] 9 pages", "content": "NUMERIC: AUD 7,899.00"}

def _call(name, **a):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": a}}]}
def _ans(text):
    return {"role": "assistant", "content": text}

_s = iter([_call("read_screen"), _call("research", question="5090 price"),
           _ans("Screen shows a 5090; web says AUD 7,899, so the GPU.")])
_tt = _Stub(); _ag = A.Agent(tools=_tt, chat_fn=lambda m, use_tools=True: next(_s))
_t = _ag.ask("which part is most expensive?")
check("two-step chain: read -> research -> answer",
      _t["steps"] == 2 and _tt.calls[0] == "read_screen" and _tt.calls[1][0] == "research", _tt.calls)
_ctx = json.dumps(_ag.context)
check("her prose is NOT carried into the next turn", "so the GPU" not in _ctx)
check("user turn and tool results ARE carried", "most expensive" in _ctx and "[web]" in _ctx)
_seen = []
_s2 = iter([_call("read_screen"), _ans("From the screen: PLE.")])
def _spy(m, use_tools=True):
    _seen.append([x for x in m if x["role"] == "tool"]); return next(_s2)
A.Agent(tools=_Stub(), chat_fn=_spy).ask("screen?")
check("tool results reach the model tagged with source", _seen[-1][0]["content"].startswith("[read]"))
_flags = []
def _m1(m, use_tools=True):
    _flags.append(use_tools); return _call("read_screen") if use_tools else _ans("giving up")
_t3 = A.Agent(tools=_Stub(), chat_fn=_m1).ask("x")
check("runaway tool loop capped and forced to answer",
      _t3["steps"] == A.MAX_STEPS and _t3["answer"] == "giving up", (_t3["steps"], _t3["answer"]))
def _m2(m, use_tools=True):
    return _call("read_screen") if use_tools else _ans("")
_t4 = A.Agent(tools=_Stub(), chat_fn=_m2).ask("x")
check("empty answer -> honest fallback with tool digest",
      _t4["answer"].startswith("I could not") and "[read]" in _t4["answer"], _t4["answer"])
_s4 = iter([_call("hack_the_planet"), _ans("no")])
_t5 = A.Agent(tools=_Stub(), chat_fn=lambda m, use_tools=True: next(_s4)).ask("x")
check("invented tool -> error result, no crash", _t5["tools"][0]["source"] == "[error]")
_s6 = iter([_call("remember", want="rtx 5080 under 1500"), _ans("Noted.")])
_tt2 = _Stub(); A.Agent(tools=_tt2, chat_fn=lambda m, use_tools=True: next(_s6)).ask("x")
check("remember files a real interest with its ceiling", _tt2.ints.all()[0]["ceiling"] == 1500.0)
_s7 = iter([_ans("Lima.")])
_t7 = A.Agent(tools=_Stub(), chat_fn=lambda m, use_tools=True: next(_s7)).ask("capital of peru")
check("no-tool answer passes straight through", _t7["steps"] == 0 and _t7["answer"] == "Lima.")

def _fn(it):
    return lambda m, use_tools=True: next(it)
_p = iter([_ans("From the web, the price is about $30,000 to $50,000."),
           _call("research", question="gac aion price"), _ans("From the web, AUD 31,990.")])
_tp = _Stub(); _r = A.Agent(tools=_tp, chat_fn=_fn(_p)).ask("price of a gac aion")
check("fabricated 'from the web' -> forced research -> real figure",
      _r["corrected"] and _tp.calls and _tp.calls[0][0] == "research" and "31,990" in _r["answer"], _r["answer"])
_p2 = iter([_ans("From the web, about $40,000."), _ans("From the web, roughly $40,000.")])
_r2 = A.Agent(tools=_Stub(), chat_fn=_fn(_p2)).ask("price of x")
check("persistent fabrication -> honest fallback, no fake number", _r2["answer"].startswith("I claimed a source"))
_p3 = iter([_ans("The screen shows Firefox and VS Code."), _call("read_screen"), _ans("The screen says: PLE.")])
_tp3 = _Stub(); _r3 = A.Agent(tools=_tp3, chat_fn=_fn(_p3)).ask("anything interesting open right now?")
check("screen described without looking -> forced fresh look", _r3["corrected"] and _tp3.calls == ["read_screen"])
_p4 = iter([_call("read_screen"), _ans("The screen says PLE."), _call("research", question="q"), _ans("From the web, AUD 31,990.")])
_ag4 = A.Agent(tools=_Stub(), chat_fn=_fn(_p4)); _ag4.ask("what's on screen"); _ag4.ask("price of aion ut")
_c4 = json.dumps(_ag4.context)
check("perishable screen result NOT carried; durable web result carried",
      "PLE page" not in _c4 and "[used: read_screen]" in _c4 and "7,899" in _c4 and "31,990" not in _c4)
_r5 = A.Agent(tools=_Stub(), chat_fn=_fn(iter([_ans("The Aion UT is about $32,000.")]))).ask("roughly how much")
check("unbacked number flagged as own knowledge", _r5["answer"].endswith("not checked.)"), _r5["answer"])
_r6 = A.Agent(tools=_Stub(), chat_fn=_fn(iter([_call("research", question="q"), _ans("From the web, AUD 31,990.")]))).ask("x")
check("web-backed number not flagged", "not checked" not in _r6["answer"])
_r8 = A.Agent(tools=_Stub(), chat_fn=_fn(iter([_ans("Hello! How can I help?")]))).ask("hello")
check("conversation passes through unchanged", _r8["answer"] == "Hello! How can I help?" and not _r8["corrected"])

_e1 = iter([_ans("I don't have that."), _ans("From the web, the Aion UT is AUD 31,990.")])
_te = _Stub(); _re = A.Agent(tools=_te, chat_fn=_fn(_e1)).ask("research the gac aion ut price")
check("explicit 'research X' forces the call the model skipped",
      _te.calls and _te.calls[0][0] == "research" and _re["tools"][0].get("forced"), _te.calls)
_e2 = iter([_ans("I'm not sure."), _ans("I will look it up."), _ans("From the web, AUD 31,990.")])
_te2 = _Stub(); _ag = A.Agent(tools=_te2, chat_fn=_fn(_e2))
_ag.ask("whats the price of a gac aion car"); _ag.ask("look it up")
check("'look it up' researches the previous question",
      _te2.calls == [("research", "whats the price of a gac aion car")], _te2.calls)
_e3 = iter([_call("research", question="q"), _ans("From the web, AUD 7,899.")])
_te3 = _Stub(); _re3 = A.Agent(tools=_te3, chat_fn=_fn(_e3)).ask("research the aion price")
check("no double research when the model already did it", len(_te3.calls) == 1 and not _re3["tools"][0].get("forced"))
_e4 = iter([_ans("Sure."), _ans("The screen says PLE.")])
_te4 = _Stub(); A.Agent(tools=_te4, chat_fn=_fn(_e4)).ask("look at my screen")
check("'look at my screen' forces a look", _te4.calls == ["read_screen"], _te4.calls)
check("research query strips the verb and politeness",
      A.research_query("can you research the RTX 5090 price please", "") == "the RTX 5090 price",
      A.research_query("can you research the RTX 5090 price please", ""))

check("clean_query strips scaffolding and URL",
      X.clean_query("whats this persons fastest time https://www.worldcubeassociation.org/persons/2025VROS01") == "fastest time")
check("URL in a message triggers explicit research", A.explicit_tools("whats his time https://x.org/p") == {"research"})
check("echoed internal notes are a violation", bool(A.provenance_violations("[used: research]\n[web] 5 pages: NUMERIC 6.83", set())))
check("'I can see' / 'it looks like' are not screen claims",
      not A.provenance_violations("I can see no information; it looks like nothing.", {"research"}))
check("decimal number is caught by the unbacked-number flag", bool(A.NUMBER.search("6.83 seconds")))

_d1 = iter([_ans("I don't have access to your screen."), _ans("The screen says a PLE Pyro prebuilt at $13,499.")])
_td = _Stub(); _rd = A.Agent(tools=_td, chat_fn=_fn(_d1)).ask("thoughts on the pyro prebuilt?")
check("model denies screen access -> forced look -> real answer",
      _td.calls == ["read_screen"] and "13,499" in _rd["answer"] and _rd["tools"][0].get("forced"), (_td.calls, _rd["answer"]))
_d2 = iter([_ans("I can look it up. Would you like me to research this?"), _ans("From the web: Adults is a Hulu sitcom.")])
_td2 = _Stub(); _rd2 = A.Agent(tools=_td2, chat_fn=_fn(_d2)).ask("do you know the show adults?")
check("asking permission -> forced research", bool(_td2.calls) and _td2.calls[0][0] == "research" and "Hulu" in _rd2["answer"])
_d3 = iter([_ans("I don't have access to current product reviews or pricing."), _ans("From the web: mixed reviews.")])
_td3 = _Stub(); A.Agent(tools=_td3, chat_fn=_fn(_d3)).ask("is it good value?")
check("denial of web access -> forced research", bool(_td3.calls) and _td3.calls[0][0] == "research")
_d4 = iter([_ans("I don't have access to your screen."), _ans("I don't have access to your screen.")])
_rd4 = A.Agent(tools=_Stub(), chat_fn=_fn(_d4)).ask("hm")
check("a denial is never rewritten as a false confession", not _rd4["answer"].startswith("I claimed"))
check("'look on my screen' is an explicit look", A.explicit_tools("you were supposed to look on my screen?") == {"read_screen"})

print()
if fails:
    print(f"{fails} FAILED")
    sys.exit(1)
print("all self-tests passed")