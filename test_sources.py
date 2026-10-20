"""Multi-source claims, vague citations and unreachable reasons (no tokens).
Run: .venv/bin/python test_sources.py"""
import json
import os
import tempfile
import types as T

import providers as PV
import rescore
from quote_check import judge, merge, same_fact
from touchstone import HOMEPAGE, LISTING, audit, combine, unreachable, vague_note

A, B, C = "https://a.example/report", "https://b.example/news", "https://c.example/data"
PAGE_A = ("Coffee exports reached 10.15 million bags in December 2025, up 9.2% year on year.\n"
          "Certified stocks stayed low through the month in every market.")
PAGE_B = ("The composite price averaged 304.68 cents per pound in December 2025.\n"
          "Exports were reported at 11.40 million bags in December 2025 by another tally.")
PAGE_C = "Nothing about coffee here. The weather was mild and the harbour reopened in spring."
CLAIM = "Exports rose to 10.15 million bags in December 2025, and the price averaged 304.68 cents per pound"
F1, F2 = "Exports rose to 10.15 million bags in December 2025", "The price averaged 304.68 cents per pound"
Q_A1 = "Coffee exports reached 10.15 million bags in December 2025, up 9.2% year on year."
Q_B2 = "The composite price averaged 304.68 cents per pound in December 2025."
Q_B1 = "Exports were reported at 11.40 million bags in December 2025 by another tally."
P = lambda text, status, quote="": {"text": text, "kind": "fact", "status": status, "quote": quote}

# 1. A fact is "stated" if ANY source states it with a verified quote.
ra = judge({"parts": [P(F1, "stated", Q_A1), P(F2, "missing")]}, CLAIM, PAGE_A, A)
rb = judge({"parts": [P(F1, "missing"), P(F2, "stated", Q_B2)]}, CLAIM, PAGE_B, B)
assert ra["label"] == "PARTIAL" and rb["label"] == "PARTIAL"
m = merge(CLAIM, [(A, ra), (B, rb)], [PAGE_A, PAGE_B])
assert m["label"] == "SOURCED", m
assert [(f["status"], f["source"]) for f in m["facts"]] == [("stated", A), ("stated", B)], m["facts"]

# 2. "contradicted" only if a source contradicts it and no source states it.
rb_c = judge({"parts": [P(F1, "contradicted", Q_B1), P(F2, "stated", Q_B2)]}, CLAIM, PAGE_B, B)
assert [f["status"] for f in rb_c["facts"]] == ["contradicted", "stated"] and rb_c["label"] == "CONTRADICTED"
m = merge(CLAIM, [(A, ra), (B, rb_c)], [PAGE_A, PAGE_B])           # A states F1: not contradicted
assert m["facts"][0]["status"] == "stated" and m["facts"][0]["source"] == A, m
# ...but B contradicts what A states: never silently SOURCED (review L6), amber + a note.
assert m["label"] == "COULDN'T CONFIRM" and "Sources disagree" in m["reason"], m
assert "a.example states it, b.example contradicts it" in m["reason"], m
ra_m = judge({"parts": [P(F1, "missing"), P(F2, "missing")]}, CLAIM, PAGE_A, A)
m = merge(CLAIM, [(A, ra_m), (B, rb_c)], [PAGE_A, PAGE_B])        # nobody states F1: contradicted
assert m["label"] == "CONTRADICTED" and m["facts"][0]["source"] == B, m
# A fake quote never counts as "stated" from any source.
ra_fake = judge({"parts": [P(F1, "stated", "Exports hit 10.15 million bags, a record for December 2025."),
                           P(F2, "missing")]}, CLAIM, PAGE_A, A)
m = merge(CLAIM, [(A, ra_fake), (B, rb)], [PAGE_A, PAGE_B])
assert m["facts"][0]["status"] != "stated" and m["label"] != "SOURCED", m
# Differently worded facts with different numbers never merge.
assert not same_fact(F1, "Exports were 11.40 million bags in December 2025")
assert same_fact(F1, "Exports rose to 10.15 million bags in Dec 2025".replace("Dec", "December"))
assert same_fact(F1, "Coffee exports rose to 10.15 million bags in December 2025")

# 3. Some sources unreachable: label from the reachable ones, "1 of 3 sources couldn't be read";
#    all unreachable -> SOURCE UNREACHABLE. The card lists every source with its outcome.
pages = {A: {"status": "OK", "text": PAGE_A}, B: {"status": "OK", "text": PAGE_B},
         C: {"status": "HTTP_ERR", "detail": "403"}}
r = combine(CLAIM, [(A, dict(ra)), (B, dict(rb)), (C, unreachable(pages[C], C))], pages)
assert r["label"] == "SOURCED" and r["reason"].endswith("1 of 3 sources couldn't be read."), r["reason"]
assert [(s["url"], s["label"]) for s in r["sources"]] == [(A, "PARTIAL"), (B, "PARTIAL"), (C, "SOURCE UNREACHABLE")]
assert r["sources"][2]["reason"] == "The site refused the checker (login, paywall or bot protection)."
assert r["sources"][2]["detail"] == "HTTP_ERR 403" and "model" in r["sources"][0]
lost = {A: {"status": "TIMEOUT"}, B: {"status": "HTTP_ERR", "detail": "404"}}
r = combine(CLAIM, [(u, unreachable(p, u)) for u, p in lost.items()], lost)
assert r["label"] == "SOURCE UNREACHABLE" and r["reason"] == "None of the 2 sources could be read.", r
assert [s["reason"] for s in r["sources"]] == ["The site took too long to respond.",
                                               "The page was not found (it may have moved or been removed)."]
# One source: exactly the single-source result (regression sets unchanged).
one = combine(CLAIM, [(A, dict(ra))], pages)
assert {k: one[k] for k in ("label", "reason", "facts", "framing", "model")} == {k: ra[k] for k in ("label", "reason", "facts", "framing", "model")}
assert len(one["sources"]) == 1 and "model" not in one["sources"][0] and one["notes"] == []

# 4. Through audit(): Groq checks each reachable source (one call per claim and source).
def fake_groq(reply_for):
    calls = []

    def create(**k):
        user = k["messages"][1]["content"]
        calls.append(user)
        reply = reply_for(user)
        return T.SimpleNamespace(choices=[T.SimpleNamespace(message=T.SimpleNamespace(content=json.dumps(reply)))],
                                 usage=T.SimpleNamespace(total_tokens=100))
    return T.SimpleNamespace(chat=T.SimpleNamespace(completions=T.SimpleNamespace(create=create))), calls


def groq_reply(user):
    if "10.15 million bags in December 2025, up" in user:
        return {"opinion": False, "parts": [P(F1, "stated", Q_A1), P(F2, "missing")]}
    return {"opinion": False, "parts": [P(F1, "missing"), P(F2, "stated", Q_B2)]}


report = f"- {CLAIM}. Sources: [A]({A}), [B]({B}) and [C]({C})\n- Certified stocks stayed low [A]({A})"
client, calls = fake_groq(groq_reply)
ev = list(audit(report, client, pages=pages))
cl = [e for e in ev if e["type"] == "claim"]
assert len(calls) == 3                                   # claim 1 x {A, B}; claim 2 x {A}; C unreachable
assert cl[0]["urls"] == [A, B, C] and cl[0]["url"] == A and cl[0]["label"] == "SOURCED", cl[0]
assert "1 of 3 sources couldn't be read." in cl[0]["reason"] and cl[0]["tokens"] == 200
assert cl[1]["urls"] == [A] and len(cl[1]["sources"]) == 1

# 5. Gemini: a claim citing two pages joins each page's group; results merged.
class FakeGemini:
    def __init__(self):
        self.calls = []
        self.models = T.SimpleNamespace(generate_content=self._gen)

    def _gen(self, **k):
        self.calls.append(k["contents"])
        claims = [l.split("] ", 1)[1] for l in k["contents"].split("\n") if l.startswith("[")
                  and "] " in l and l[1].isdigit()]
        out = []
        for i, c in enumerate(claims, 1):
            on_a = "10.15 million bags in December 2025, up" in k["contents"]
            parts = ([P(F1, "stated", Q_A1), P(F2, "missing")] if on_a else [P(F1, "missing"), P(F2, "stated", Q_B2)]) \
                if c.startswith(CLAIM) else [P(c, "stated", "Certified stocks stayed low through the month in every market.")]
            out.append({"id": i, "opinion": False, "parts": parts})
        return T.SimpleNamespace(text=json.dumps({"claims": out}), usage_metadata=T.SimpleNamespace(total_token_count=600))


g = FakeGemini()
ev = list(audit(report, g, pages=pages, provider=PV.Gemini(g)))
cl = [e for e in ev if e["type"] == "claim"]
assert len(g.calls) == 2, len(g.calls)                   # page A (claims 1 and 2), page B (claim 1)
assert CLAIM in g.calls[0] and "Certified stocks stayed low" in g.calls[0] and CLAIM in g.calls[1]
assert cl[0]["label"] == "SOURCED" and cl[1]["label"] == "SOURCED", [(e["label"], e["reason"]) for e in cl]
assert sum(e["tokens"] for e in cl) == 1200

# 6. Vague citations: still checked, with a visible note.
assert vague_note("https://ico.org/") == HOMEPAGE and vague_note("https://ico.org") == HOMEPAGE
assert vague_note("https://ico.org/?lang=en") == HOMEPAGE
assert vague_note("https://ico.org/ico-document-library/?coffeemeeting=Monthly+Coffee+Market&coffeeyear=2025%2F2026") == LISTING
assert vague_note("https://example.com/search?q=coffee") == LISTING and vague_note("https://example.com/?s=coffee") == LISTING
assert vague_note("https://www.ico.org/documents/cy2025-26/cmr-0226-e.pdf") is None
assert vague_note("https://example.com/news/coffee-prices?utm_source=x") is None
home = {"https://ico.org/": {"status": "OK", "text": PAGE_A}}
ev = [e for e in audit("- Certified stocks stayed low https://ico.org/", fake_groq(groq_reply)[0], pages=home)
      if e["type"] == "claim"][0]
assert ev["notes"] == [HOMEPAGE] and ev["sources"][0]["note"] == HOMEPAGE and ev["label"] != "SOURCE UNREACHABLE"
r = combine(CLAIM, [(A, dict(ra)), ("https://ico.org/", dict(rb))], {**pages, **home})
assert r["notes"] == [f"{HOMEPAGE} (ico.org)"]

# 7. Friendly unreachable reasons: never a raw code as the reason (kept in "detail").
cases = {("BLOCKED", "blocked the checker (bot protection)"): "reuters.com blocked the checker (bot protection or paywall).",
         ("HTTP_ERR", "401"): "The site refused the checker (login, paywall or bot protection).",
         ("HTTP_ERR", "403"): "The site refused the checker (login, paywall or bot protection).",
         ("HTTP_ERR", "500"): "The site had a server error.",
         ("BLOCKED", "DNS failed"): "The site's address could not be found.",
         ("BLOCKED", "private address"): "The link points to a private or invalid address, so it was not fetched.",
         ("NO_TEXT", "JS page or blocked?"): "The page loaded but its content couldn't be read (it may need JavaScript).",
         ("ERROR", "ConnectError"): "The site could not be reached."}
for (status, detail), want in cases.items():
    u = unreachable({"status": status, "detail": detail}, "https://www.reuters.com/markets/x")
    assert u["reason"] == want and u["detail"] == f"{status} {detail}", (status, detail, u)
    assert not any(code in u["reason"] for code in ("401", "403", "HTTP", "ERR")), u

# reuters.com's real answer: 401 + x-datadome -> blocked (detection only, never evaded).
import ipaddress, httpx
import fetch_links as F
DD = '<html><head><title>reuters.com</title></head><body><script src="https://ct.captcha-delivery.com/c.js"></script></body></html>'
assert F.bot_blocked(401, {"x-datadome": "protected"}, "") and F.bot_blocked(401, {}, DD)
assert not F.bot_blocked(401, {}, "<html><title>Log in</title><body>Please sign in.</body></html>")


async def ok(url): return True, "", ipaddress.ip_address("93.184.215.14")
real = (F.check_url, F.peer_ok, httpx.AsyncClient)
F.check_url, F.peer_ok = ok, lambda r: True
for status, headers, body, want in ((401, {"x-datadome": "protected"}, DD, ("BLOCKED", F.BOT_BLOCKED)),
                                    (401, {}, "<html>Sign in</html>", ("HTTP_ERR", "401"))):
    F.httpx.AsyncClient = lambda **k: real[2](transport=httpx.MockTransport(
        lambda req: httpx.Response(status, headers=headers, text=body)), **k)
    got = F.fetch("https://www.reuters.com/markets/x")
    assert (got["status"], got["detail"]) == want, got
F.check_url, F.peer_ok, F.httpx.AsyncClient = real

# 8. rescore.py replays a multi-source claim from its saved per-source replies.
client, _ = fake_groq(groq_reply)
claim_ev = [e for e in audit(report, client, pages=pages) if e["type"] == "claim"][0]
run = {"format": "touchstone-run", "claims": [{k: v for k, v in claim_ev.items() if k not in ("type", "index")}]}
with tempfile.TemporaryDirectory() as d:
    path, cache = os.path.join(d, "run.json"), os.path.join(d, "x.pages.json")
    json.dump(run, open(path, "w"))
    json.dump([{"url": u, **p} for u, p in pages.items()], open(cache, "w"))
    c = rescore.load_run(path)[0]
    assert rescore.rescore_multi(c, rescore.get_pages([A, B, C], cache))[0] == "SOURCED"

# 9. Security: one claim with many URLs never fans out. Only MAX_SOURCES are fetched and
#    checked; the rest are listed as not checked, never fetched (SSRF / quota amplification).
import touchstone as TS
many = [f"https://s{i}.example/p" for i in range(50)]
fetched = []
real_fetch = TS.fetch_many
TS.fetch_many = lambda urls, **k: fetched.extend(urls) or [{"url": u, "status": "OK", "text": PAGE_A} for u in urls]
try:
    client, calls = fake_groq(groq_reply)
    ev = [e for e in audit(f"- {CLAIM} " + " ".join(many), client) if e["type"] == "claim"][0]
finally:
    TS.fetch_many = real_fetch
assert fetched == many[:TS.MAX_SOURCES] and len(calls) == TS.MAX_SOURCES, (len(fetched), len(calls))
assert [s["url"] for s in ev["sources"]] == many and ev["urls"] == many
assert all(s["label"] == "NOT CHECKED" for s in ev["sources"][TS.MAX_SOURCES:])
assert ev["reason"].endswith(f"47 more sources not checked (limit of {TS.MAX_SOURCES} per claim)."), ev["reason"]
assert ev["label"] == "PARTIAL"     # labelled from the 3 checked sources (all page A: F1 only)
# Checked sources all unreachable: still SOURCE UNREACHABLE, not the limit's NOT CHECKED.
dead = {u: {"status": "TIMEOUT"} for u in many[:5]}
ev = [e for e in audit(f"- {CLAIM} " + " ".join(many[:5]), None, pages=dead) if e["type"] == "claim"][0]
assert ev["label"] == "SOURCE UNREACHABLE", ev
assert ev["reason"] == "None of the 3 sources could be read. 2 more sources not checked (limit of 3 per claim).", ev
# Exactly 4 sources: "1 more source" (singular); the first 3 in report order are the checked ones.
ev = [e for e in audit(f"- {CLAIM} " + " ".join(many[:4]), None, pages=dead) if e["type"] == "claim"][0]
assert ev["reason"].endswith(" 1 more source not checked (limit of 3 per claim)."), ev["reason"]
assert [s["label"] for s in ev["sources"]] == ["SOURCE UNREACHABLE"] * 3 + ["NOT CHECKED"]

# L6 on the card: combine() puts "Sources disagree" in the claim's notes.
from touchstone import combine
out = combine(CLAIM, [(A, ra), (B, rb_c)], {A: {"text": PAGE_A}, B: {"text": PAGE_B}})
assert out["label"] == "COULDN'T CONFIRM" and out["notes"][0] == "Sources disagree", out
assert "disagree" not in out, out

# C1: a bug in the code checks is "Internal check error", never retried, tokens kept.
import quote_check as _QC
_real = _QC.judge
def _boom(*a, **k):
    raise KeyError("bug")
_QC.judge = _boom
try:
    client, calls = fake_groq(groq_reply)
    cl = [e for e in audit(f"- Certified stocks stayed low [A]({A})", client, pages=pages) if e["type"] == "claim"]
    assert len(calls) == 1 and cl[0]["label"] == "ERROR" and cl[0]["reason"] == "Internal check error.", cl
    assert cl[0]["tokens"] == 100, cl
    g = FakeGemini()
    cl = [e for e in audit(f"- Certified stocks stayed low [A]({A})", g, pages=pages, provider=PV.Gemini(g))
          if e["type"] == "claim"]
    assert len(g.calls) == 1 and cl[0]["label"] == "ERROR" and cl[0]["reason"] == "Internal check error.", cl
    assert cl[0]["tokens"] == 600, cl
finally:
    _QC.judge = _real

# L2 refinement: through audit() (Groq) and rescore, a list lead-in's numbers are context,
# not required in the parts; the bullet's own numbers are (in a part or a verified quote).
LEAD_Q = "Certified stocks stayed low through the month in every market, at 412,000 bags."
LEAD_PAGE = LEAD_Q + "\nDecember 2025 report."
lead_report = f"Top 5 coffee facts for 2025:\n\n- Certified stocks stayed low at 412,000 bags [A]({A})"
client, calls = fake_groq(lambda user: {"opinion": False, "parts": [
    P("Certified stocks stayed low at 412,000 bags", "stated", LEAD_Q)]})
cl = [e for e in audit(lead_report, client, pages={A: {"status": "OK", "text": LEAD_PAGE}}) if e["type"] == "claim"]
assert cl[0]["text"].startswith("Top 5 coffee facts for 2025:") and cl[0]["label"] == "SOURCED", cl
client, calls = fake_groq(lambda user: {"opinion": False, "parts": [
    P("Certified stocks stayed low", "stated", LEAD_Q)]})
cl = [e for e in audit(lead_report, client, pages={A: {"status": "OK", "text": LEAD_PAGE}}) if e["type"] == "claim"]
assert cl[0]["label"] == "SOURCED", cl          # 412,000 is in no part, but in the verified quote
class LeadGemini(FakeGemini):
    def _gen(self, **k):
        self.calls.append(k["contents"])
        parts = [P("Certified stocks stayed low at 412,000 bags", "stated", LEAD_Q)]
        return T.SimpleNamespace(text=json.dumps({"claims": [{"id": 1, "opinion": False, "parts": parts}]}),
                                 usage_metadata=T.SimpleNamespace(total_token_count=50))
g = LeadGemini()
cl = [e for e in audit(lead_report, g, pages={A: {"status": "OK", "text": LEAD_PAGE}}, provider=PV.Gemini(g))
      if e["type"] == "claim"]
assert len(g.calls) == 1 and cl[0]["label"] == "SOURCED", cl
import rescore as RS
with tempfile.TemporaryDirectory() as d:
    run = os.path.join(d, "run.json")
    json.dump({"report": lead_report, "claims": []}, open(run, "w"))
    assert RS.load_contexts(run) == {1: "Top 5 coffee facts for 2025:"}
    json.dump([], open(run, "w"))
    assert RS.load_contexts(run) == {}

# Coverage in merge(): a claim number in no part but in a verified quote of any source is
# covered (Q_A1 holds "9.2%"); one in neither still caps.
c92 = CLAIM + " (up 9.2%)"
m = merge(c92, [(A, judge({"parts": [P(F1, "stated", Q_A1), P(F2, "missing")]}, c92, PAGE_A, A)),
                (B, judge({"parts": [P(F1, "missing"), P(F2, "stated", Q_B2)]}, c92, PAGE_B, B))], [PAGE_A, PAGE_B])
assert m["label"] == "SOURCED", m
c77 = CLAIM + " (up 7.7%)"
m = merge(c77, [(A, judge({"parts": [P(F1, "stated", Q_A1), P(F2, "missing")]}, c77, PAGE_A, A)),
                (B, judge({"parts": [P(F1, "missing"), P(F2, "stated", Q_B2)]}, c77, PAGE_B, B))], [PAGE_A, PAGE_B])
assert m["label"] == "COULDN'T CONFIRM" and "leaves out 7.7" in m["reason"], m

# Period across sources: capped only if no source stating a fact shows the claim's quarter.
qc = "Samsung's smartphone share was 18% in Q2 2025."
qq = "Samsung's smartphone share was 18% in 2025."
pq1 = "Market tracker\n" + qq
pq2 = "Q2 2025 market tracker\n" + qq
qr = {"parts": [P("Samsung's smartphone share was 18% in Q2 2025", "stated", qq)]}
meta2 = {"title": "", "headings": [[2, "Q2 2025 market tracker"]]}
both_lack = merge(qc, [(A, judge(qr, qc, pq1, A)), (B, judge(qr, qc, pq1, B))], [pq1, pq1])
assert both_lack["label"] == "COULDN'T CONFIRM" and "the period Q2" in both_lack["reason"], both_lack
one_has = merge(qc, [(A, judge(qr, qc, pq1, A)), (B, judge(qr, qc, pq2, B, meta=meta2))], [pq1, pq2])
assert one_has["label"] == "SOURCED", one_has

# ChatGPT chips through audit(): "+1" (a source hidden from the copied text) never lets the
# visible source make a claim red; a chip whose link was lost is NO SOURCE GIVEN with the fix,
# never fetched; a meta-description-only page can confirm but never refute.
from touchstone import UNREADABLE
M = "https://m.example/digital-2026"
PAGE_M = "Morocco counted 31.0 million internet users in early 2026, 85% of the population.\nMore lines here."
MC = "Morocco had 34.2 million internet users in early 2026"
chip_report = (f"{MC}.&#x20;\n\n[image](https://www.google.com/s2/favicons?domain=https://m.example\\&sz=32)\n\n"
               f"M Stats\n\n+1\n\n### Sources\n\n- M Stats — [Digital 2026]({M}).\n\n"
               "Coverage reached 99% by 2025.\n\n[image](https://www.google.com/s2/favicons?domain=https://lost.example\\&sz=32)\n\nLost\n")
for status, quote, want in (("missing", "", "COULDN'T CONFIRM"),
                            ("contradicted", "Morocco counted 31.0 million internet users in early 2026, 85% of the population.", "COULDN'T CONFIRM"),
                            ("stated", "Morocco counted 31.0 million internet users in early 2026", None)):
    client, calls = fake_groq(lambda u, s=status, q=quote: {"opinion": False, "parts": [P(MC, s, q)]})
    ev = list(audit(chip_report, client, pages={M: {"status": "OK", "text": PAGE_M}}))
    cl = [e for e in ev if e["type"] == "claim"]
    assert ev[0]["cited"] == 1 and ev[0]["site_only"] == 1 and ev[0]["uncited"] == 0, ev[0]
    assert len(calls) == 1 and cl[0]["urls"] == [M] and cl[0]["hidden"] == 1, cl[0]
    if want:
        assert cl[0]["label"] == want, (status, cl[0])
        assert cl[0]["reason"].endswith("Also cites 1 more source that wasn't included in the copied text."), cl[0]["reason"]
    assert cl[0]["label"] not in ("UNSUPPORTED", "CONTRADICTED"), cl[0]
    lost = cl[1]
    assert (lost["claim"], lost["label"], lost["site"], lost["urls"]) == (None, "NO SOURCE GIVEN", "lost.example", []), lost
    assert lost["reason"].startswith("The copied text only kept the site name (lost.example), not the page link."), lost
# The visible source confirms it: SOURCED as normal.
PAGE_OK = "Morocco had 34.2 million internet users in early 2026, according to the survey.\nOther text."
client, _ = fake_groq(lambda u: {"opinion": False, "parts": [P(MC, "stated", "Morocco had 34.2 million internet users in early 2026")]})
cl = [e for e in audit(chip_report, client, pages={M: {"status": "OK", "text": PAGE_OK}}) if e["type"] == "claim"]
assert cl[0]["label"] == "SOURCED" and "copied text" not in cl[0]["reason"], cl[0]
# Rescore replays the cap.
assert rescore.rescore({**cl[0], "label": "PARTIAL", "model": {"opinion": False, "parts": [P(MC, "missing")]}},
                       {"status": "OK", "text": PAGE_M})[0] == "COULDN'T CONFIRM"
# A name-only "claim" is never sent, never SOURCED.
client, calls = fake_groq(lambda u: {"opinion": False, "parts": [P("DataReportal", "stated", "DataReportal")]})
ev = list(audit("- DataReportal — [Digital 2026](https://d.example/r)\n\nDataReportal — https://d.example/r", client,
                pages={"https://d.example/r": {"status": "OK", "text": "DataReportal\nDigital 2026 report."}}))
assert calls == [] and not any(e.get("label") == "SOURCED" for e in ev), ev
# Meta-description-only page: nothing found there -> SOURCE UNREACHABLE, not UNSUPPORTED.
client, _ = fake_groq(lambda u: {"opinion": False, "parts": [P(MC, "missing")]})
cl = [e for e in audit(f"{MC} {M}", client, pages={M: {"status": "OK", "text": PAGE_M, "meta_only": True}})
      if e["type"] == "claim"]
assert cl[0]["label"] == "SOURCE UNREACHABLE" and cl[0]["reason"] == UNREADABLE, cl[0]

# Homepage citations (2026-10-14): a homepage that doesn't state the claim is never red.
from touchstone import HOMEPAGE_REASON
for u in ("https://www.itu.int", "https://www.arpce.dz/en/", "https://x.org/fr", "https://x.org/en-us/"):
    assert vague_note(u) == HOMEPAGE, u
assert vague_note("https://www.worldbank.org/en/country/algeria") is None
hp = {"https://www.itu.int": {"status": "OK", "text": "ITU news of the day."}}
for label in ("UNSUPPORTED", "CONTRADICTED", "UNVERIFIED"):
    out = combine("Algeria has 50 million lines", [("https://www.itu.int", {"label": label, "quote": "", "reason": "x", "facts": [], "tokens": 0})], hp)
    assert out["label"] == "COULDN'T CONFIRM" and out["reason"] == HOMEPAGE_REASON and "homepage" not in out, out
out = combine("Algeria has 50 million lines", [("https://www.itu.int", {"label": "SOURCED", "quote": "q", "reason": "Stated.", "facts": [], "tokens": 0})], hp)
assert out["label"] == "SOURCED"
out = combine("Algeria has 50 million lines", [("https://www.worldbank.org/en/country/algeria", {"label": "UNSUPPORTED", "quote": "", "reason": "x", "facts": [], "tokens": 0})], {})
assert out["label"] == "UNSUPPORTED"

# A source's verified contradiction that same_fact() doesn't match to the base source's facts
# (other numbers, other wording) was dropped by merge(): never SOURCED then (2026-10-20).
from quote_check import claim_names
cx = "Exports rose to 10.15 million bags in December 2025"
assert claim_names(cx, page=PAGE_A + "\n" + PAGE_B) == []                 # (a) no names: the guard can't fire
rx_a = judge({"parts": [P(cx, "stated", Q_A1)]}, cx, PAGE_A, A)
rx_b = judge({"parts": [P("Exports rose to 10.15 million bags", "contradicted", Q_B1)]}, cx, PAGE_B, B)
assert rx_a["label"] == "SOURCED" and rx_b["label"] == "CONTRADICTED", (rx_a, rx_b)
assert not same_fact(cx, "Exports rose to 10.15 million bags")
m = merge(cx, [(A, rx_a), (B, rx_b)], [PAGE_A, PAGE_B])
assert m["label"] == "COULDN'T CONFIRM", m
assert 'Sources disagree on "Exports rose to 10.15 million bags": a.example states it, b.example contradicts it.' in m["reason"], m
out = combine(cx, [(A, dict(rx_a)), (B, dict(rx_b))], {A: {"text": PAGE_A}, B: {"text": PAGE_B}})
assert out["label"] == "COULDN'T CONFIRM" and out["notes"][0] == "Sources disagree", out
# (b) with names: the Samsung case (A's table row contradicts, B states the share unnamed).
cs = "In Q2 2025, Samsung held a 19% share of Africa's smartphone shipments."
row = "| Samsung | 18% | 19% |"
ps_a = ("Africa smartphone market, Q2 2025\nIn Africa, Transsion leads while Samsung is second.\n"
        "| Brand | Q2 2025 share | Q2 2024 share |\n|---|---|---|\n" + row + "\n| Transsion | 51% | 47% |")
qs_b = "The number two vendor held a 19% share of Africa's smartphone shipments."
ps_b = "Africa smartphones Q2 2025\n" + qs_b
rs_a = judge({"parts": [P(cs.rstrip("."), "contradicted", row)]}, cs, ps_a, A)
rs_b = judge({"parts": [P("The second vendor held a 19% share of Africa's smartphone shipments", "stated", qs_b)]},
             cs, ps_b, B, meta={"title": "Africa smartphones Q2 2025"})
assert rs_a["label"] == "CONTRADICTED", rs_a
assert merge(cs, [(A, rs_a), (B, rs_b)], [ps_a, ps_b])["label"] != "SOURCED"
# (c) control: both sources state it, nothing contradicted: still SOURCED.
rx_b2 = judge({"parts": [P("Exports rose to 10.15 million bags", "stated", Q_A1)]}, cx, PAGE_A, B)
m = merge(cx, [(A, rx_a), (B, rx_b2)], [PAGE_A, PAGE_A])
assert m["label"] == "SOURCED" and "disagree" not in m, m
# (d) control: one source contradicting it stays CONTRADICTED (combine() returns it unchanged).
out = combine(cx, [(B, dict(rx_b))], {B: {"text": PAGE_B}})
assert out["label"] == "CONTRADICTED", out

print("source checks passed")
