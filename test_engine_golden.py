"""Golden test for the engine (no tokens, no network): the exact event streams audit() yields
on fixed reports, fake pages and fake models, hashed. Written before the audit_segments split
so the split is proven to change nothing; any later engine change that moves an event moves
the hash. If it changes on purpose, run with --print and pin the new hashes.
Run: .venv/bin/python test_engine_golden.py [--print]"""
import hashlib
import json
import sys
import types as T
import zlib

import providers as PV
import touchstone
from check_numbers import blocks_meta
from pacing import TokenPacer

REPORTS = ["report3.txt", "report4.txt", "report5.txt", "examples/demo.txt",
           "samples/chatgpt_chips.txt", "samples/footnotes_perplexity.txt"]
DEAD = [{"status": "HTTP_ERR", "detail": "404"}, {"status": "TIMEOUT"}, {"status": "BLOCKED", "detail": "DNS failed"},
        {"status": "NO_TEXT"}, {"status": touchstone.LATE}, {"status": "PDF_ERROR", "detail": "PDF is password-protected"},
        {"status": "HTTP_ERR", "detail": "403"}, {"status": "BLOCKED", "detail": touchstone.BOT_BLOCKED}]


def crc(s):
    return zlib.crc32(s.encode())


def shift(text):
    """Every digit +1: the page then gives other figures than the claim (value conflicts)."""
    return "".join(str((int(c) + 1) % 10) if c.isdigit() else c for c in text)


def make_pages(report):
    """One fake page per cited URL, built from the claims citing it: most state them, some
    shift the digits, some are unreachable, LATE or meta-only (crc of the URL decides)."""
    by_url = {}
    for text, urls, _, _ in blocks_meta(report):
        for u in urls:
            by_url.setdefault(u, []).append(text)
    pages = {}
    for u, claims in by_url.items():
        k = crc(u)
        if k % 6 == 1:
            pages[u] = dict(DEAD[k // 6 % len(DEAD)])
            continue
        lines = [shift(c) if k % 4 == 0 else c for c in claims]
        if k % 13 == 4:
            lines = ["The harbour reopened in spring after the storm season ended."]
        text = "\n".join(lines + ["Other markets were described in the rest of the article without figures.",
                                  "Copyright 2025 Example Media. All rights reserved."])
        page = {"status": "OK", "text": text, "title": f"Page {k % 97} 2025", "headings": [[2, "Overview"]]}
        if k % 7 == 3:
            page["meta_only"] = True
        pages[u] = page
    return pages


def reply_for(claim, page_text):
    """A model reply for one claim: status from the claim's crc, quote = the page line sharing
    most words with the claim."""
    words = set(claim.lower().split())
    lines = [l for l in page_text.split("\n") if l.strip()]
    best = max(lines, key=lambda l: (len(words & set(l.lower().split())), -len(l))) if lines else ""
    k = crc(claim)
    status = ["stated", "stated", "missing", "contradicted", "stated"][k % 5]
    parts = [{"text": claim, "kind": "fact", "status": status, "quote": "" if status == "missing" else best}]
    if k % 4 == 1:
        parts.append({"text": "The total reached 4,321 units in that year.", "kind": "fact", "status": "missing", "quote": ""})
    if k % 3 == 0:
        parts.append({"text": "This is a remarkable shift.", "kind": "framing", "status": "stated", "quote": ""})
    return {"opinion": k % 17 == 5, "parts": parts}


class Err(Exception):
    def __init__(self, msg, code):
        super().__init__(msg)
        self.status_code = code


class Model:
    """Fake Groq and Gemini clients sharing one call counter and failure plan:
    fail = {call number: exception}; each call advances the fake clock by `step` seconds."""

    def __init__(self, clock, step=0.0, fail=None):
        self.clock, self.step, self.fail, self.n = clock, step, fail or {}, 0
        self.chat = T.SimpleNamespace(completions=T.SimpleNamespace(create=self._groq))
        self.models = T.SimpleNamespace(generate_content=self._gemini)

    def _tick(self):
        self.n += 1
        self.clock.t += self.step
        if self.n in self.fail:
            raise self.fail[self.n]

    def _groq(self, **k):
        self._tick()
        user = k["messages"][1]["content"]
        claim = user.split("CLAIM:\n", 1)[1].split("\n\n", 1)[0]
        page = user.split("<<<\n", 1)[1].rsplit("\n>>>", 1)[0]
        content = json.dumps(reply_for(claim, page))
        return T.SimpleNamespace(choices=[T.SimpleNamespace(message=T.SimpleNamespace(content=content))],
                                 usage=T.SimpleNamespace(total_tokens=300 + len(user) % 200))

    def _gemini(self, **k):
        self._tick()
        text = k["contents"]
        page = text.split("<<<\n", 1)[1].rsplit("\n>>>", 1)[0]
        claims = [l.split("] ", 1)[1] for l in text.split("\nEXCERPTS:")[0].split("\n")
                  if l.startswith("[") and "] " in l and l[1].isdigit()]
        out = [{"id": i, **reply_for(c, page)} for i, c in enumerate(claims, 1)]
        if len(out) > 2 and crc(text) % 4 == 0:
            out.pop(1)                                   # a claim the model left out: its ERROR
        return T.SimpleNamespace(text=json.dumps({"claims": out}),
                                 usage_metadata=T.SimpleNamespace(total_token_count=1000 + len(text) % 500))


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def run(report, provider, *, fn=None, step=0.0, fail=None, deadline=None, rpd=None, live=False, **kw):
    """One audit with fresh fakes: its events as a list."""
    clock = Clock()
    model = Model(clock, step, fail)
    prov = PV.Gemini(model) if provider == "gemini" else PV.Groq(model)
    pacer = TokenPacer.for_provider(provider, clock=clock, day=lambda: "day")
    if rpd is not None:
        pacer.rpd = rpd
    pages = make_pages(report)
    real_fetch = touchstone.fetch_many
    if live:      # the pages=None path: fetch_many gets the URLs, in order, and the time left
        touchstone.fetch_many = lambda urls, within=None: [pages.get(u, {"status": "TIMEOUT"}) for u in urls]
    try:
        events = list((fn or touchstone.audit)(
            report, model, pages=None if live else pages, deadline=None if deadline is None else clock() + deadline,
            pacer=pacer, clock=clock, sleep=clock.sleep, provider=prov, **kw))
    finally:
        touchstone.fetch_many = real_fetch
    return events


DAY_429 = Err("429 RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProjectPerModel", 429)
MIN_429 = Err("429 rate limit: tokens per minute (TPM). Please try again in 2s", 429)
E503 = Err("503 overloaded", 503)


def scenarios():
    texts = {name: open(name, encoding="utf-8").read() for name in REPORTS}
    for name, text in texts.items():
        for prov in ("groq", "gemini"):
            yield f"{name}/{prov}/all", lambda t=text, p=prov: run(t, p)
            yield f"{name}/{prov}/cap", lambda t=text, p=prov: run(t, p, max_claims=4, max_urls=5 if p == "gemini" else None)
    r4, r5, demo = texts["report4.txt"], texts["report5.txt"], texts["examples/demo.txt"]
    for prov in ("groq", "gemini"):
        yield f"r4/{prov}/only", lambda p=prov: run(r4, p, only=[2, 5, 99])
        yield f"r4/{prov}/deadline", lambda p=prov: run(r4, p, step=7.0, deadline=40.0, max_claims=10)
        yield f"r4/{prov}/rpd", lambda p=prov: run(r4, p, rpd=2)
        yield f"r5/{prov}/day429", lambda p=prov: run(r5, p, fail={3: DAY_429})
        yield f"r5/{prov}/min429", lambda p=prov: run(r5, p, fail={1: MIN_429, 2: MIN_429}, deadline=200.0)
        yield f"r5/{prov}/min429-nodeadline", lambda p=prov: run(r5, p, fail={i: MIN_429 for i in range(1, 8)})
        yield f"r5/{prov}/transient", lambda p=prov: run(r5, p, fail={1: E503, 2: E503, 3: E503, 5: E503})
        yield f"r5/{prov}/error", lambda p=prov: run(r5, p, fail={2: RuntimeError("boom")})
        yield f"demo/{prov}/live", lambda p=prov: run(demo, p, live=True, deadline=300.0)
        yield f"r4/{prov}/live-urlcap", lambda p=prov: run(r4, p, live=True, max_urls=3, max_claims=8)


def digest(events):
    return hashlib.sha256(json.dumps(events, sort_keys=True, ensure_ascii=False, default=repr)
                          .encode()).hexdigest()


GOLDEN = "e438ff086dff0c147280c1d2abf75f0f5197301bce610cbcf782bde2ed951836"

if __name__ == "__main__":
    hashes = {}
    for key, fn in scenarios():
        ev = fn()
        assert ev and ev[0]["type"] == "start" and ev[-1]["type"] == "done", key
        hashes[key] = digest(ev)
    total = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    if "--print" in sys.argv:
        for k, h in hashes.items():
            print(h[:16], k)
    print("golden hash:", total)
    assert total == GOLDEN, f"engine event streams changed: {total} != {GOLDEN}"
    # After the split: audit_segments(blocks_meta(report)) is audit(report), event for event.
    if hasattr(touchstone, "audit_segments"):
        seg = lambda report, *a, **k: touchstone.audit_segments(blocks_meta(report), *a, **k)
        for name in REPORTS:
            text = open(name, encoding="utf-8").read()
            for prov in ("groq", "gemini"):
                assert run(text, prov, fn=seg) == run(text, prov), (name, prov)
        print("audit_segments(blocks_meta(r)) == audit(r) on every report")
    print("engine golden test passed")
