#!/usr/bin/env python3
"""
research.py - many sources, extracted separately, reconciled in code.

    source env.sh
    python3 research.py "price of a Gigabyte RTX 5090 AORUS MASTER in Australia" --currency AUD
    python3 research.py "difference between an emu and an ostrich"

Map-reduce over web pages. Each page is read on its own by the model and must
return points with a quote copied from THAT page; pages never share a prompt,
so a claim cannot be stitched from two pages about different things. Quotes
are checked against the page text; a point whose quote is not on its page is
rejected and counted. Reconciliation - agreement, medians, outliers - is done
in Python, not by asking a model to weigh sources.

There is no question classifier. Every page returns points; a point may carry
a numeric value. If two or more verified points on the same aspect carry
values, the numeric summary is produced; the ranked points are produced
regardless. The data decides the shape of the answer.

Fetched pages are attacker-controlled input. Extraction runs one page at a
time with no tools, no memory and no filesystem. Do not give this write access.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("RESEARCH_MODEL", os.environ.get("OLLAMA_MODEL", "qwen3:8b"))
NUM_CTX = int(os.environ.get("NUM_CTX", "8192"))
SEARX = os.environ.get("SEARX_URL", "")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/125.0 Safari/537.36")
MAX_CHARS = 9000
FETCH_TIMEOUT = 12

TIER = {
    1: ["python.org", "postgresql.org", "wikipedia.org", "ubuntu.com", "github.com",
        "ai.meta.com", "anthropic.com", "amd.com", "nvidia.com", "intel.com",
        "gov.au", "abs.gov.au", "asx.com.au"],
    2: ["ple.com.au", "scorptec.com.au", "mwave.com.au", "umart.com.au",
        "centrecom.com.au", "jbhifi.com.au", "msy.com.au", "huggingface.co",
        "tomshardware.com", "arstechnica.com"],
}

EXTRACT_SYSTEM = (
    "You read ONE web page and pull out what it says about ONE question.\n"
    "Reply with ONE JSON object and nothing else. No markdown, no backticks.\n"
    '{"points":[{"aspect":"<2-4 word topic>","point":"<one short sentence>",'
    '"value":<number or null>,"currency":"<AUD|USD|GBP|EUR|NZD or null>",'
    '"as_of":"<date or period stated on the page, or null>",'
    '"quote":"<up to 25 words copied EXACTLY from the page>"}]}\n'
    "Rules:\n"
    "- At most 6 points, only ones this page actually supports.\n"
    "- Every quote is copied character for character from the page.\n"
    "- value is the number in the quote when the point is about a quantity "
    "(a price, a count, a size); otherwise null.\n"
    "- currency only if stated or clearly implied by the site; otherwise null.\n"
    "- Never state a fact that is not on this page.\n"
    '- If the page does not address the question: {"points":[]}'
)


@dataclass
class Source:
    idx: int
    title: str
    url: str
    text: str = ""
    error: str = ""

    @property
    def domain(self) -> str:
        return urlparse(self.url).netloc.replace("www.", "")

    @property
    def tier(self) -> int:
        for t, doms in TIER.items():
            if any(d in self.domain for d in doms):
                return t
        return 3


@dataclass
class Point:
    source: Source
    aspect: str
    point: str
    quote: str
    value: float | None = None
    currency: str | None = None
    as_of: str | None = None
    verified: bool = False


# ------------------------------------------------------------------ pure
def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def verify(quote: str, page_text: str) -> bool:
    """Quote must appear on the page. Exact, or 85% of its tokens."""
    q = norm(quote)
    if len(q) < 8:
        return False
    page = norm(page_text)
    if q in page:
        return True
    toks = [t for t in re.findall(r"[a-z0-9$.,]+", q) if len(t) > 2]
    return bool(toks) and sum(t in page for t in toks) / len(toks) >= 0.85


def parse_points(raw: str, src: Source) -> list[Point]:
    raw = re.sub(r"```(?:json)?|```", "", raw or "").strip()
    try:
        d = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except Exception:
        return []
    out = []
    for p in (d.get("points") or [])[:6]:
        if not isinstance(p, dict) or not p.get("point"):
            continue
        try:
            val = float(p["value"]) if p.get("value") is not None else None
        except (TypeError, ValueError):
            val = None
        ccy = p.get("currency") or None
        if val is not None and not ccy:
            if src.domain.endswith(".au"):
                ccy = "AUD"
            elif src.domain.endswith(".uk"):
                ccy = "GBP"
        pt = Point(source=src, aspect=norm(p.get("aspect") or "general")[:40],
                   point=str(p["point"])[:220], quote=str(p.get("quote") or "")[:300],
                   value=val, currency=ccy, as_of=p.get("as_of") or None)
        pt.verified = verify(pt.quote, src.text)
        out.append(pt)
    return out


def cluster(points: list[Point]) -> list[dict]:
    """Group points saying the same thing; count independent domains."""
    clusters: list[dict] = []
    for p in points:
        toks = set(re.findall(r"[a-z]{4,}", p.point.lower()))
        for c in clusters:
            overlap = (len(toks & c["tokens"]) / max(1, min(len(toks), len(c["tokens"])))
                       if toks and c["tokens"] else 0)
            if p.aspect == c["aspect"] or overlap >= 0.45:
                c["points"].append(p)
                c["tokens"] |= toks
                c["domains"].add(p.source.domain)
                break
        else:
            clusters.append({"aspect": p.aspect, "points": [p], "tokens": set(toks),
                             "domains": {p.source.domain}})
    clusters.sort(key=lambda c: (-len(c["domains"]), c["aspect"]))
    return clusters


def numeric_summary(points: list[Point], want_ccy: str | None) -> dict | None:
    nums = [p for p in points if p.value is not None]
    dropped = []
    if want_ccy:
        dropped = [p for p in nums if p.currency and p.currency != want_ccy]
        nums = [p for p in nums if p.currency in (want_ccy, None)]
    if len(nums) < 2:
        return None
    med = statistics.median(p.value for p in nums)
    inl = [p for p in nums if med / 2 <= p.value <= med * 2]
    out = [p for p in nums if p not in inl]
    vals = sorted(p.value for p in inl) or sorted(p.value for p in nums)
    return {"median": statistics.median(vals), "low": vals[0], "high": vals[-1],
            "agree": len(inl), "total": len(nums), "inliers": inl,
            "outliers": out, "dropped_currency": dropped,
            "currency": next((p.currency for p in inl if p.currency), want_ccy)}


def reconcile(points: list[Point], want_ccy: str | None = None) -> dict:
    good = [p for p in points if p.verified]
    return {"verified": good,
            "rejected": [p for p in points if not p.verified],
            "numeric": numeric_summary(good, want_ccy),
            "clusters": cluster(good)}


# ------------------------------------------------------------------ io
def _chat(system: str, user: str, num_predict: int, temperature: float = 0) -> str:
    body = {"model": MODEL, "stream": False,
            "options": {"temperature": temperature, "num_ctx": NUM_CTX,
                        "num_predict": num_predict},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}]}
    if "qwen3" in MODEL:
        body["think"] = False
    r = requests.post(f"{OLLAMA}/api/chat", json=body, timeout=240)
    r.raise_for_status()
    return r.json()["message"]["content"]


def expand(question: str, extra: int = 3) -> list[str]:
    qs = [question]
    try:
        raw = _chat("Give search queries only, one per line, no numbering, no "
                    "commentary. Each finds the answer from a different angle.",
                    f"{extra} search queries for: {question}", 120, 0.4)
        for line in raw.splitlines():
            line = line.strip(" -*0123456789.\"'")
            if 6 < len(line) < 120:
                qs.append(line)
    except Exception:
        pass
    seen, out = set(), []
    for q in qs:
        if q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out[:5]


def search(query: str, n: int) -> list[tuple[str, str]]:
    try:
        if SEARX:
            r = requests.get(f"{SEARX}/search", params={"q": query, "format": "json"},
                             headers={"User-Agent": UA}, timeout=20)
            r.raise_for_status()
            return [(d.get("title", ""), d["url"]) for d in r.json().get("results", [])[:n]]
        from ddgs import DDGS
        with DDGS() as ddg:
            return [(d.get("title", ""), d["href"]) for d in ddg.text(query, max_results=n)]
    except Exception:
        return []


def gather(question: str, want: int, per_query: int) -> list[Source]:
    seen, out = set(), []
    for q in expand(question):
        for title, url in search(q, per_query):
            key = urlparse(url).netloc + urlparse(url).path.rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            out.append(Source(idx=len(out) + 1, title=title, url=url))
            if len(out) >= want:
                break
        if len(out) >= want:
            break
    out.sort(key=lambda s: s.tier)
    return out


def fetch(src: Source) -> Source:
    try:
        r = requests.get(src.url, timeout=FETCH_TIMEOUT,
                         headers={"User-Agent": UA, "Accept-Language": "en-AU,en;q=0.9"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "noscript", "iframe",
                         "form", "svg"]):
            tag.decompose()
        text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n"))
        src.text = re.sub(r"[ \t]{2,}", " ", text).strip()[:MAX_CHARS]
    except Exception as e:
        src.error = f"{type(e).__name__}"
    return src


def extract(question: str, src: Source) -> list[Point]:
    if not src.text:
        return []
    try:
        raw = _chat(EXTRACT_SYSTEM,
                    f"PAGE: {src.title}\nSITE: {src.domain}\n\n{src.text}\n\n"
                    f"QUESTION: {question}", 500)
    except Exception:
        return []
    return parse_points(raw, src)


URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
SCAFFOLD = re.compile(r"\b(what'?s|what is|whats|who is|who'?s|tell me|can you|could you|"
                      r"please|look up|look it up|research|search for|find out|"
                      r"this person'?s?|this|that|the following|for me|and give (me )?the)\b", re.I)


def clean_query(question: str) -> str:
    """Search engines want keywords, not sentences. 'whats this persons fastest
    time https://...' -> 'fastest time'."""
    q = URL_RE.sub(" ", question)
    q = SCAFFOLD.sub(" ", q)
    return re.sub(r"\s+", " ", q).strip(" ?.,:") or question


def research(question: str, want: int = 16, per_query: int = 6,
             currency: str | None = None, verbose: bool = True) -> dict:
    t0 = time.perf_counter()
    urls = URL_RE.findall(question)
    if urls:
        # A URL is an instruction to read THAT page. Searching for the URL
        # string returns nothing useful while the page sits unread.
        srcs = [Source(idx=i + 1, title=u, url=u) for i, u in enumerate(urls[:4])]
        q = clean_query(question)
        if len(re.findall(r"[a-z]{3,}", q.lower())) < 2:
            q = "what are the main facts, names, figures and dates on this page"
        question = q
    else:
        srcs = gather(clean_query(question), want, per_query)
    with ThreadPoolExecutor(max_workers=10) as pool:
        srcs = list(pool.map(fetch, srcs))
    ok = [s for s in srcs if s.text]
    if verbose:
        print(f"  {len(srcs)} sources, {len(ok)} fetched")
    points = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for f in as_completed([pool.submit(extract, question, s) for s in ok]):
            points.extend(f.result())
    res = reconcile(points, currency)
    res["seconds"] = time.perf_counter() - t0
    res["sources"] = len(ok)
    if verbose:
        print(report(question, res))
    return res


def report(question: str, res: dict) -> str:
    L = [f"\nQ: {question}"]
    n = res.get("numeric")
    if n:
        L.append(f"\n  {n['currency'] or ''} {n['median']:,.2f}   "
                 f"(median of {n['agree']} agreeing; range "
                 f"{n['low']:,.2f} - {n['high']:,.2f})")
        for p in n["outliers"]:
            L.append(f"    outlier, not averaged: {p.currency or '?'} "
                     f"{p.value:,.2f}  {p.source.domain}")
        for p in n["dropped_currency"]:
            L.append(f"    dropped, wrong currency: {p.currency} "
                     f"{p.value:,.2f}  {p.source.domain}")
    cl = res["clusters"]
    if cl:
        L.append(f"\n  {len(cl)} points, by independent sources:")
        for c in cl[:10]:
            k = len(c["domains"])
            p0 = c["points"][0]
            L.append(f"  {'***' if k >= 3 else '** ' if k == 2 else '*  '} "
                     f"[{k}] {c['aspect']}: {p0.point}")
            L.append(f"        \"{p0.quote[:80]}\"  - {p0.source.domain}"
                     + (f"{', ' + p0.as_of if p0.as_of else ''}"))
    elif not n:
        L.append("\n  NOT FOUND - nothing verifiable against its own page.")
    if res["rejected"]:
        L.append(f"\n  {len(res['rejected'])} point(s) rejected: quote not on page.")
    L.append(f"\n  {res['sources']} pages, {res['seconds']:.1f}s")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="+")
    ap.add_argument("--sources", type=int, default=16)
    ap.add_argument("--currency")
    a = ap.parse_args()
    research(" ".join(a.question), a.sources, currency=a.currency)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nstopped")