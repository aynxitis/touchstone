"""Token-free parsing checks. Run: .venv/bin/python test_parsing.py"""
from check_numbers import resolve_footnotes, segments


def cited(path):
    return [(t, u) for t, u in segments(open(path, encoding="utf-8").read()) if u]


# report2 is the tuning set: its 29 cited claims must never shift.
assert len(cited("report2.txt")) == 29

# [n] markers + "Sources:" list; "[1][2]," is one citation; a numbered body list stays text.
c = cited("samples/footnotes_perplexity.txt")
assert [u.rsplit("/", 1)[1] for _, u in c] == [
    "magstartup-10-startups", "magstartup-10-startups", "startup-dz-stats", "asf-capital", "volz-series-a"]
assert c[1][0] == "More than 7,800 ventures are registered on startup.dz,"
assert not any(t in (",", ".") for t, _ in segments(open("samples/footnotes_perplexity.txt").read()))
assert ("Register on startup.dz", None) in segments(open("samples/footnotes_perplexity.txt").read())

# [^1]: markdown footnotes and ChatGPT's 【1】.
c = cited("samples/footnotes_markdown.txt")
assert [u.rsplit("/", 1)[1] for _, u in c] == ["asf-portfolio", "yassir-series-b", "moustachir-ipo"]

# A source list with names only, a Sources list without markers, or no links at all:
# nothing can be checked, and source entries never become claims.
text = open("samples/names_only.txt").read()
assert cited("samples/names_only.txt") == [] and resolve_footnotes(text)[1] == 3
assert all("Wamda" not in t for t, _ in segments(text))
assert cited("samples/sources_no_markers.txt") == []
assert cited("samples/no_links.txt") == []

# Bot-protection pages are detected, never passed to the model as page text.
import ipaddress, httpx
import fetch_links as F
from touchstone import audit

CF_CHALLENGE = ('<!DOCTYPE html><html><head><title>Just a moment...</title></head><body>'
                '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script>'
                '<div id="cf-chl-widget"></div></body></html>')
CF_BLOCKED = ('<html><head><title>Attention Required! | Cloudflare</title></head><body>'
              '<div id="cf-error-details">Sorry, you have been blocked</div></body></html>')
DATADOME = ('<html><head><title>example.com</title></head><body><script>var dd={"cid":"x"}</script>'
            '<script src="https://ct.captcha-delivery.com/c.js"></script></body></html>')
AKAMAI = ('<HTML><HEAD><TITLE>Access Denied</TITLE></HEAD><BODY><H1>Access Denied</H1>'
          'Reference&#32;&#35;18.1 <P>https&#58;&#47;&#47;errors&#46;edgesuite&#46;net&#47;18.1</P></BODY></HTML>')
PERIMETERX = ('<html><head><title>Access to this page has been denied</title></head><body>'
              '<div id="px-captcha"></div><script>window._pxAppId="PXabc";</script></body></html>')
ARTICLE = ('<html><head><title>How Cloudflare bot checks work</title>'
           '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script></head><body><p>'
           'Sites behind Cloudflare sometimes show a "Just a moment..." page; its scripts load from '
           'challenge-platform and set cf-chl cookies. DataDome and PerimeterX do similar things. '
           + 'Algeria counts more than 7,800 registered startups. ' * 10 + '</p></body></html>')
NOT_FOUND = '<html><head><title>404 Not Found</title></head><body>Not Found</body></html>'

assert F.bot_blocked(200, {"cf-mitigated": "challenge"}, "")
assert F.bot_blocked(403, {}, CF_CHALLENGE) and F.bot_blocked(200, {}, CF_CHALLENGE)
assert F.bot_blocked(403, {}, CF_BLOCKED)
assert F.bot_blocked(403, {}, DATADOME) and F.bot_blocked(403, {"x-datadome": "protected"}, "")
assert F.bot_blocked(403, {"server": "AkamaiGHost"}, AKAMAI) and F.bot_blocked(403, {}, AKAMAI)
assert F.bot_blocked(403, {}, PERIMETERX)
assert not F.bot_blocked(200, {}, ARTICLE)          # a normal page that only mentions them
assert not F.bot_blocked(200, {}, DATADOME)         # markers alone need a 403/429/503
assert not F.bot_blocked(403, {}, NOT_FOUND) and not F.bot_blocked(404, {}, CF_BLOCKED.replace("Attention Required! | Cloudflare", "x"))

# Through the real fetch path (mocked transport, no network): status + headers + body.
def fetch_fixture(status, html, headers=None):
    async def ok(url): return True, "", ipaddress.ip_address("93.184.215.14")
    real = (F.check_url, F.peer_ok, httpx.AsyncClient)
    transport = httpx.MockTransport(lambda req: httpx.Response(status, headers=headers or {}, text=html))
    F.check_url, F.peer_ok = ok, lambda r: True
    F.httpx.AsyncClient = lambda **k: real[2](transport=transport, **k)
    try:
        return F.fetch("https://example.com/page")
    finally:
        F.check_url, F.peer_ok, F.httpx.AsyncClient = real

for status, html, headers in ((403, CF_CHALLENGE, {"cf-mitigated": "challenge"}), (503, CF_CHALLENGE, None),
                              (200, CF_CHALLENGE, None), (403, DATADOME, None), (429, PERIMETERX, None)):
    r = fetch_fixture(status, html, headers)
    assert (r["status"], r["detail"]) == ("BLOCKED", F.BOT_BLOCKED), (status, r)
assert fetch_fixture(200, ARTICLE)["status"] == "OK"
assert fetch_fixture(403, NOT_FOUND) == {"url": "https://example.com/page", "status": "HTTP_ERR", "detail": "403"}

# <time> elements keep their text (trafilatura dropped them): French Wikipedia's date template.
DATED = ('<html><head><title>Barrage de Tichy</title></head><body><article><p>'
         + 'Le barrage de Tichy retient les eaux de la rivière pour l\'irrigation de la vallée. ' * 8
         + '</p><p>Le barrage a été inauguré le <time class="nowrap date-lien" datetime="2011-03-14" '
         'data-sort-value="2011-03-14"><a href="/wiki/14_mars">14</a> <a href="/wiki/Mars_2011">mars</a> '
         '<a href="/wiki/2011">2011</a></time> par le ministre des ressources en eau.</p><p>Mis en eau le '
         '<span class="nowrap date-lien" data-sort-value="2010-06-02"><a href="/wiki/2_juin">2</a> juin 2010</span>, '
         'il a été achevé en avance.</p><p>Report dated <TIME datetime="2012-01-09">9 January 2012</TIME>.</p></article></body></html>')
dated = fetch_fixture(200, DATED)["text"]
assert "inauguré le 14 mars 2011 par le ministre" in dated and "Mis en eau le 2 juin 2010" in dated, dated
assert "Report dated 9 January 2012." in dated, dated

# A blocked page becomes SOURCE UNREACHABLE with the reason shown, and costs no model call.
url = "https://example.com/page"
ev = [e for e in audit(f"- Algeria has 7,800 startups {url}", None,
                       pages={url: {"url": url, "status": "BLOCKED", "detail": F.BOT_BLOCKED}})
      if e["type"] == "claim"][0]
assert ev["label"] == "SOURCE UNREACHABLE" and ev["reason"] == "example.com blocked the checker (bot protection or paywall).", ev
assert ev["detail"] == "BLOCKED " + F.BOT_BLOCKED and "HTTP" not in ev["reason"]


# Claim cap: the first max_claims cited claims in report order are checked (a claim without
# numbers is not pushed back); the rest come as "skipped" events labelled NOT CHECKED.
report = "\n".join(f"- Claim {i} {'has no figures' if i == 5 else f'says {i * 11}%'} https://example.com/{i}"
                   for i in range(1, 12))
events = list(audit(report, None, pages={}, max_claims=10))
assert events[0] == {"type": "start", "cited": 11, "checked": 10, "uncited": 0, "site_only": 0, "limit": 10, "url_limit": None}, events[0]
assert [e["claim"] for e in events if e["type"] == "claim"] == list(range(1, 11))
assert [(e["claim"], e["label"], e["reason"]) for e in events if e["type"] == "skipped"] == [
    (11, "NOT CHECKED", "Limit of 10 claims per audit.")]

# report3 (regression set, labels3.json): 18 cited claims; claim 5 (transport, no digits) was
# skipped in production by the old numbers-first cap. Report order checks claims 1-10.
c = cited("report3.txt")
assert len(c) == 18 and c[4][0].startswith("The transport sector remains a weak point"), c[4]
from touchstone import select
assert select(c, 10) == set(range(10))

# report4 (Gemini, EV sales): "([Name](url))." links. The leftover "." is never a passage,
# "---" rules are skipped, and "(+23.9%) ([Eleport](url))" keeps its own closing parenthesis.
segs4 = segments(open("report4.txt", encoding="utf-8").read())
assert [t for t, u in segs4 if not u] == [
    "The European electric vehicle (EV) market experienced robust growth in 2025, with "
    "battery-electric vehicles (BEVs) achieving record sales and market penetration across the continent.",
    "Adoption rates varied significantly by region, heavily concentrated in Northern and Western Europe."]
c4 = [(t, u) for t, u in segs4 if u]
assert len(c4) == 22
assert c4[5] == ("United Kingdom: 473,348 EVs sold (+23.9%)", "https://eleport.com/ev-sales-in-europe/")
assert c4[3][0] == "Norway: 172,231 EVs sold (+50.6%), dominating with a 95.9% EV market share"
assert c4[0][0].endswith("(EU, EFTA, and the UK) in 2025")
assert c4[14][0].startswith("While exact percentage shares") and "Volkswagen: Reclaimed" in c4[14][0]
assert all(t.count("(") == t.count(")") for t, _ in c4), [t for t, _ in c4 if t.count("(") != t.count(")")]
seg = lambda line: segments(line)
for line, want in (("* **Spain:** 20,000 EVs sold (+3.1%) ([Eleport](https://e.com/a)).", "Spain: 20,000 EVs sold (+3.1%)"),
                   ("- Italy: 9,000 EVs (+1.0%) ([Src](https://e.com/b))", "Italy: 9,000 EVs (+1.0%)"),
                   ("- Malta sold 40 EVs (2024) https://e.com/c", "Malta sold 40 EVs (2024)"),
                   ("Sales rose sharply last year (see [chart](https://e.com/d)).", "Sales rose sharply last year (see")):
    assert seg(line) == [(want, line[line.index("https"):].split(")")[0])], (line, seg(line))
assert seg("Intro.\n\n---\n***\n___\n\nSales ended the year flat. https://e.com/x\n.\n- (\n") == [("Intro.", None), ("Sales ended the year flat.", "https://e.com/x")]

# report5 (ChatGPT copy button, coffee prices): favicon chips + captions, HTML entities,
# "Source:"/"Sources:" lines under stat blocks / tables / paragraphs, inline "Sources: [A] and
# [B]", number headings as stats. The whole claim list is pinned.
from check_numbers import blocks, copy_cleanup, stat_value
b5 = blocks(open("report5.txt", encoding="utf-8").read())
ICO = "https://www.ico.org/documents/"
cmr = lambda name: ICO + ("cy2024-25/" if name == "0225" else "cy2025-26/") + f"cmr-{name}-e.pdf"
REUT1 = "https://www.reuters.com/markets/commodities/coffee-new-york-jumps-6-new-record-amid-panic-buying-2025-02-10/"
REUT2 = "https://www.reuters.com/business/why-are-coffee-prices-trading-near-half-century-highs-2024-12-04/"
LISTING = "https://ico.org/ico-document-library/?coffeemeeting=Monthly+Coffee+Market&coffeeyear=2025%2F2026"
CAPTION = " — ICO composite indicator; US cents per pound of green coffee. Monthly averages."
want5 = [
    ("February 2025 monthly average: 354.32¢/lb — US dollars: $3.54 per pound", (cmr("0225"),)),
    ("Year-on-year change: +94.6% — Compared with February 2024", (cmr("0225"),)),
    ("The ICO reported a record-high monthly average for its composite indicator at the time.", (cmr("0225"),)),
    ("Drought and heat in Brazil.", (REUT1,)),
    ("Weather problems in Vietnam.", (REUT2,)),
    ("Tight inventories and reduced export flows.", (cmr("0225"),)),
    ("Market buying amplified the move.", (REUT1,)),
    ("Prices remained elevated through much of the year", (cmr("1125"), LISTING)),
    ("December 2025: 304.68¢/lb" + CAPTION, (cmr("0126"), cmr("0226"), cmr("0326"))),
    ("January 2026: 296.89¢/lb" + CAPTION, (cmr("0126"), cmr("0226"), cmr("0326"))),
    ("February 2026: 267.57¢/lb" + CAPTION, (cmr("0126"), cmr("0226"), cmr("0326"))),
    ("March 2026: 273.70¢/lb" + CAPTION, (cmr("0126"), cmr("0226"), cmr("0326"))),
    ("Improved Brazilian crop outlook.", (cmr("0226"),)),
    ("Better rainfall in Vietnam.", (cmr("0226"),)),
    ("More export supply.", (cmr("0126"),)),
    ("Month: March 2026; Global benchmark: 273.70¢/lb; Monthly change: +2.3%", (cmr("0326"), "https://ico.org/")),
    ("Month: April 2026; Global benchmark: 266.24¢/lb; Monthly change: −2.7%", (cmr("0326"), "https://ico.org/")),
    ("Month: August 2026; Global benchmark: 287.29¢/lb; Monthly change: Essentially unchanged", (cmr("0326"), "https://ico.org/")),
    ("Month: September 2026; Global benchmark: 262.18¢/lb; Monthly change: −8.7%", (cmr("0326"), "https://ico.org/")),
    ("Selected monthly averages of the ICO Composite Indicator Price", ("https://ico.org/resources/public-market-information/",)),
    ("Three distinctions matter:", (cmr("0226"),)),
]
got5 = [(t, u) for t, u in b5 if u]
assert len(got5) == len(want5), [t[:50] for t, _ in got5]
for (t, u), (wt, wu) in zip(got5, want5):
    assert t.startswith(wt) and u == wu, ((t, u), (wt, wu))
assert got5[7][0].endswith("as supply concerns eased and export flows strengthened."), got5[7][0]   # "Sources:" stripped
uncited5 = [t for t, u in b5 if not u]
assert len(uncited5) == 10 and uncited5[0].startswith("Global coffee prices went through")
assert "Global green coffee benchmark, 2025–2026" in uncited5
for t, _ in b5:     # chips, captions, connectors, entities, chart axes: never claims or passages
    assert t not in ("and", ", and", "Sources:", "Reuters", "icocoffee.org", "International Coffee Organization",
                     "+1", "+2", "cmr-1225-e"), t
    assert "&#x20;" not in t and "favicon" not in t and "Sources:" not in t and "¢/lb250" not in t, t
assert not any("google.com" in u for _, us in b5 for u in us)

# Copy-format rules, one at a time.
assert copy_cleanup("A&nbsp;B &amp; C&#x20;D &copy x https://e.com/?a=1&copy=2") == "A B & C D &copy x https://e.com/?a=1&copy=2"
assert blocks("Sales rose 5% [x](https://e.com/a\\&b=1).") == [("Sales rose 5%", ("https://e.com/a&b=1",))]
chip = "Revenue rose 5% [S](https://e.com/1).\n\n[image](https://www.google.com/s2/favicons?domain=https://e.com\\&sz=32)\n\nReuters\n\n+3\n\nShort tail"
assert blocks(chip) == [("Revenue rose 5%", ("https://e.com/1",)), ("Short tail", ())], blocks(chip)
assert blocks("Up 5%. Sources: [A](https://e.com/1), [B](https://e.com/2), and [C](https://e.com/3).") == [
    ("Up 5%.", ("https://e.com/1", "https://e.com/2", "https://e.com/3"))]
assert blocks("Tesla sold 9 [a](https://e.com/1) and BYD sold 7 [b](https://e.com/2)") == [
    ("Tesla sold 9", ("https://e.com/1",)), ("and BYD sold 7", ("https://e.com/2",))]
assert blocks("and\n, and\n,\nReal text.") == [("Real text.", ())]
# "Source:" under a paragraph, a list (every item) and a table without links stays as written.
assert blocks("Exports rose 9%.\n\nSource: ICO, [Jan report](https://e.com/j).") == [("Exports rose 9%.", ("https://e.com/j",))]
assert blocks("- Brazil: 66 million\n- Vietnam: 29 million\n\nSources: [A](https://e.com/a) and [B](https://e.com/b)") == [
    ("Brazil: 66 million", ("https://e.com/a", "https://e.com/b")), ("Vietnam: 29 million", ("https://e.com/a", "https://e.com/b"))]
assert blocks("## Results\n\nSource: [A](https://e.com/a)") == []     # nothing above to attach to
# French spacing: "Source :" / "Sources :" (space, NBSP, narrow NBSP) on its own line after a
# bullet gives its link(s) to that bullet; under the last bullet of a list, to that bullet only.
for sep in (" ", "\u00a0", "\u202f"):
    fr = (f"Les marchés ont évolué.\n\n- Les ventes ont augmenté de 12 % en 2025.\n  Source{sep}: [Le Monde](https://lemonde.fr/a)\n"
          f"- Les prix ont baissé de 3 %.\n  Sources{sep}: [Insee](https://insee.fr/x), [Banque de France](https://bdf.fr/y)\n")
    assert blocks(fr) == [("Les marchés ont évolué.", ()),
                          ("Les ventes ont augmenté de 12 % en 2025.", ("https://lemonde.fr/a",)),
                          ("Les prix ont baissé de 3 %.", ("https://insee.fr/x", "https://bdf.fr/y"))], (repr(sep), blocks(fr))
    last = f"- Hausse de 5 %.\n- Baisse de 2 %.\n  Source{sep}: [X](https://x.fr/1)"
    assert blocks(last) == [("Hausse de 5 %.", ()), ("Baisse de 2 %.", ("https://x.fr/1",))], blocks(last)
# Number headings are stat values; numbered or year-led section titles are not.
assert [stat_value(x) for x in ("# 354.32¢/lb", "# +94.6%", "## $3.5B", "# 12 million bags",
                                "## 1. What happened in 2025?", "## 2026 outlook", "# Results")] == [
    "354.32¢/lb", "+94.6%", "$3.5B", "12 million bags", None, None, None]
# Footnote runs give the text every source.
fn = "Algeria has 7,800 startups [1][2].\n\nSources:\n1. A https://e.com/1\n2. B https://e.com/2"
assert blocks(fn) == [("Algeria has 7,800 startups.", ("https://e.com/1", "https://e.com/2"))], blocks(fn)
# Linear on hostile input (CLAUDE.md): 20,000-char lines of the characters these rules look at.
import time as _t
for junk in ("[" * 20000, "](" * 10000, "&#" * 10000, "a1" * 10000, "# " + "1" * 20000, "Sources:" * 2500,
             "| " * 10000, "\\&" * 10000, ("[i](https://x.com/" + "f" * 50 + ")") * 300):
    t0 = _t.time(); blocks(junk); assert _t.time() - t0 < 2, junk[:20]

# C2: a bracketed number with no matching source entry is text, kept as written.
body, _ = resolve_footnotes("Revenue grew in [2023] by 5% [1].\n\nSources\n1. https://a.example/x")
assert body.startswith("Revenue grew in [2023] by 5%. https://a.example/x"), body
body, _ = resolve_footnotes("See table [3] for details.\n\nSources\n1. https://a.example/x")
assert "table [3] for" in body, body
# A names-only source entry is still a source: its marker is dropped as before.
assert "[1]" not in resolve_footnotes("Revenue grew 5% [1].\n\nSources\n1. Reuters")[0]

# S6: MD_LINK stops at the URL; the ")" is checked separately. Same results, linear time.
from check_numbers import copy_cleanup, md_links
assert md_links("a [x](https://e.com/p) b ![i](https://g.com/favicon.ico ) c") == [
    (2, 22, "https://e.com/p"), (25, 57, "https://g.com/favicon.ico")]
assert md_links("[x](https://e.com/p no close") == []
assert copy_cleanup("Text [s](https://e.com/a).\n![i](https://g.com/s2/favicons?d=e.com)\nReuters") .strip() == \
    "Text [s](https://e.com/a)."
for junk in ("[a](https://" + "x" * 1990 + " " ) * 40, "[a](https://x" * 5000, "[](https://" * 8000:
    t0 = _t.time(); copy_cleanup(junk); assert _t.time() - t0 < 1, junk[:20]

# Table rows keep their column headers: every cell paired with its header, the citation never
# inside a cell value, empty header cells / alignment rows / short rows handled; one claim per
# cited row with all its links; headers are the claim's context (coverage doesn't ask for them).
from check_numbers import blocks_ctx
tbl = "\n".join([
    "| Brand / group | Q2 2025 shipment share | Annual trend | Source |",
    "|:--------------|------------------:|:---:|---|",
    "| Samsung | 18% | +3% year over year [src](https://a.example/1) | |",
    "| | 12% | -2% | [IDC](https://b.example/2) |",
    "| Xiaomi | 14% [x](https://c.example/3) |",
    "| Apple [a](https://d.example/4) | 15% ([note](https://e.example/5)) | — |"])
got = [(t, us) for t, us, _ in blocks_ctx(tbl)]
assert got == [
    ("Brand / group: Samsung; Q2 2025 shipment share: 18%; Annual trend: +3% year over year", ("https://a.example/1",)),
    ("Q2 2025 shipment share: 12%; Annual trend: -2%", ("https://b.example/2",)),
    ("Brand / group: Xiaomi; Q2 2025 shipment share: 14%", ("https://c.example/3",)),
    ("Brand / group: Apple; Q2 2025 shipment share: 15%", ("https://d.example/4", "https://e.example/5")),
], got
assert blocks_ctx(tbl)[0][2] == "Brand / group\nQ2 2025 shipment share\nAnnual trend"
# An empty header cell: that column's value stands alone; extra cells beyond the header too.
got = [t for t, _, _ in blocks_ctx("| | Units |\n|---|---|\n| Renault 5 | 67 625 | extra https://f.example/6 |")]
assert got == ["Renault 5; Units: 67 625; extra"], got
# No separator row: no header, the old " — " join; a blank line ends a table's header.
assert [t for t, _, _ in blocks_ctx("| Tesla | 238,656 https://g.example/7 |")] == ["Tesla \u2014 238,656"]
got = [t for t, _, _ in blocks_ctx("| Brand | Sales |\n|---|---|\n\n| Kia | 9% https://h.example/8 |")]
assert got == ["Kia \u2014 9%"], got

# ChatGPT search-mode copy (samples/chatgpt_chips.txt, invented): citation chips resolved to the
# report's own links by site, "+N" kept as meta, reference lists never claims, entities gone.
from check_numbers import CHIP_TAG, SITE_ONLY, blocks_meta
chips = open("samples/chatgpt_chips.txt", encoding="utf-8").read()
got = blocks_meta(chips)
assert got == [
    ("Morocco had 34.2 million internet users in early 2026, 90.7% of the population.",
     ("https://example-stats.com/reports/digital-2026-morocco",), "", {"hidden": 1}),       # chip -> one URL, "+1"
    ("Type: Fibre; Subscriptions: 1.2 million", ("https://www.anrt.ma/en/indicators/internet",), "", {}),  # table + "Source: X." + chip
    ("Radio X reported that mobile data prices fell 12% in 2025.",
     ("https://news.radiox.ma/fr/node/1", "https://news.radiox.ma/fr/node/2"), "", {}),       # chip -> two URLs (subdomain, www.)
    ("Mobile coverage reached 99% of the population by 2025.", (), "", {"site": "unlisted-site.org"}),  # no link on that site
    ("The regulator expects 5G to cover major cities soon.", (), "", {}),                   # no chip, no link: uncited
], got
assert not any("&#x20;" in t or "Source" in t or "—" in t or "ANRT" == t for t, *_ in got)
assert segments(chips)[3] == ("Mobile coverage reached 99% of the population by 2025.", None)   # never fetched
assert "unlisted-site.org" in SITE_ONLY.format("unlisted-site.org")
# More than 3 links on the chip's site: ambiguous, treated as a lost link.
many = "Sales grew 4% in 2025.\n\n[image](https://www.google.com/s2/favicons?domain=https://e.com\\&sz=32)\n\nE\n\n" + \
       "".join(f"- E — [r{i}](https://e.com/{i})\n" for i in range(4))
assert blocks_meta(many) == [("Sales grew 4% in 2025.", (), "", {"site": "e.com"})], blocks_meta(many)
# Reference lists: under any Sources/References/Further reading heading (EN/FR, any level), and
# name-only list lines anywhere, produce zero claims; a short real bullet still is one.
for head in ("### Sources and further reading", "## Références", "**Sources et lectures complémentaires**",
             "Bibliographie", "# Further reading"):
    ref = f"Up 5% in 2025 [a](https://a.example/1).\n\n{head}\n\n- DataReportal — [Digital 2026](https://d.example/r).\nARPCE — [Observatoire 2025](https://arpce.example/o)\n"
    assert blocks(ref) == [("Up 5% in 2025", ("https://a.example/1",))], (head, blocks(ref))
assert blocks("- DataReportal — [Digital 2026: Morocco](https://d.example/r).\n- ARPCE — [Observatoire](https://arpce.example/o)") == []
assert blocks("- Certified stocks stayed low [A](https://a.example/1)") == [("Certified stocks stayed low", ("https://a.example/1",))]
# Safety net: a cited "claim" that is only a name, or under 4 words with no number, is dropped.
assert blocks("DataReportal — https://d.example/r\n\nInternational Coffee Organization https://ico.example/x\n\nPrices rose https://p.example/y") == []
assert blocks("Prices rose 9% https://p.example/y") == [("Prices rose 9%", ("https://p.example/y",))]
# A chip right under an already-cited line keeps that link; "+N" rides along as meta (report5).
b5m = blocks_meta(open("report5.txt", encoding="utf-8").read())
assert [m for t, us, _, m in b5m if us][:3] == [{"hidden": 1}] * 3, [m for t, us, _, m in b5m if us][:3]
assert not any("invalid" in u for _, us, _, _ in b5m for u in us)

# A pseudo-link typed into the report is never trusted (it would hide a red label).
for typed in ("https://chip.touchstone.invalid/more/9", "HTTP://Chip.Touchstone.Invalid/site/e.com",
              "https://chip.touchst[image](https://g.com/s2/favicons?domain=x.com)one.invalid/more/9",
              "https://chip.touchstone.inv[1]alid/more/9\n\nSources\n1. Reuters"):
    got = blocks_meta(f"Sales fell 40% in 2025 https://e.com/r {typed}")
    assert got[0][1][0] == "https://e.com/r" and got[0][3] == {}, got
    assert not any(u.startswith(CHIP_TAG) for u in got[0][1]), got

# Unreadable pages (JS shell, cookie wall, ~200 chars): SOURCE UNREACHABLE, never UNSUPPORTED,
# no model call.
SHORT = "<html><head><title>T</title></head><body><p>" + "Morocco telecom news. " * 9 + "</p></body></html>"
SHELL = ("<html><head><title>T</title></head><body><p>You need to enable JavaScript to run this app. "
         + "Loading the latest internet indicators for Morocco and its regions. " * 10 + "</p></body></html>")
for html in (SHORT, SHELL):
    r = fetch_fixture(200, html)
    assert r["status"] == "NO_TEXT", r
    ev = [e for e in audit("- Morocco had 34.2 million internet users in 2026 https://example.com/page", None,
                           pages={"https://example.com/page": r}) if e["type"] == "claim"][0]
    assert ev["label"] == "SOURCE UNREACHABLE" and ev["reason"] == (
        "The page loaded but its content couldn't be read (it may need JavaScript)."), ev

# Stat-block label side (2026-10-14): labels ABOVE when the group opens with a label line,
# BELOW when it opens with a value; ambiguous groups are one verbatim claim, never paired.
src = "\n\nSource: [S](https://s.example/1)"
S1 = ("https://s.example/1",)
assert blocks("Internet users\n\n# 37.8 million\n\n79.5% of the population, late 2025" + src) == [
    ("Internet users: 37.8 million \u2014 79.5% of the population, late 2025", S1)]
assert blocks("# 41.21 Mbps\n\nMobile internet\n\n# 37.86 Mbps\n\nFixed internet" + src) == [
    ("Mobile internet: 41.21 Mbps", S1), ("Fixed internet: 37.86 Mbps", S1)]
assert blocks("Speeds\n\n# 41.21 Mbps\n\n# 37.86 Mbps\n\nFixed internet" + src) == [
    ("Speeds \u2014 41.21 Mbps \u2014 37.86 Mbps \u2014 Fixed internet", S1)]          # two values in a row
assert blocks("Social media\n\n# 24.5 million\n\nFacebook\n\n# 20.1 million\n\nYouTube" + src) == [
    ("Social media \u2014 24.5 million \u2014 Facebook \u2014 20.1 million \u2014 YouTube", S1)]  # title + below?
assert blocks("# 37.8 million\n\n79.5% of the population" + src) == [
    ("37.8 million \u2014 79.5% of the population", S1)]                              # a figure is no label
# A chip after a stat group cites every stat of the group (labels as list items, details ending in ".").
fav = "[image](https://www.google.com/s2/favicons?domain=https://datareportal.example\\&sz=32)"
refs = "\n\n## Sources\n\n- DataReportal \u2014 [Digital 2026](https://datareportal.example/r)\n"
D1 = ("https://datareportal.example/r",)
for grp in ("- Facebook\n\n# 24.5 million\n\n- YouTube\n\n# 20.1 million\n\n- TikTok\n\n# 15.2 million",
            "Facebook\n\n# 24.5 million\n\nReach.\n\nYouTube\n\n# 20.1 million\n\nReach.\n\nTikTok\n\n# 15.2 million",
            "# 24.5 million\n\nFacebook\n\n# 20.1 million\n\nYouTube\n\n# 15.2 million\n\nTikTok"):
    got = [(t, u) for t, u in blocks(copy_cleanup(grp + "\n\n" + fav + "\n\nDataReportal" + refs)) if u]
    assert got == [("Facebook: 24.5 million", D1), ("YouTube: 20.1 million", D1), ("TikTok: 15.2 million", D1)], got

# Fragment claims (2026-10-14): leading ". " / ", " stripped; the model also gets the full sentence.
frag = ("Algeria has 50.1 million mobile lines [A](https://a.dz/x). Combined 3G and 4G networks cover "
        "98% of the population [B](https://b.dz/y), which operates alongside two rival operators [C](https://c.dz/z).")
fb = blocks_meta(frag)
assert [t for t, *_ in fb] == ["Algeria has 50.1 million mobile lines",
                               "Combined 3G and 4G networks cover 98% of the population",
                               "which operates alongside two rival operators"], fb
whole = "Combined 3G and 4G networks cover 98% of the population, which operates alongside two rival operators."
assert fb[2][3] == {"sentence": whole} and fb[0][3] == {}, fb
import quote_check as QCf
class _Resp:
    def __init__(self): self.choices = [type("C", (), {"message": type("M", (), {"content": '{"opinion": false, "parts": []}'})()})()]; self.usage = None
class _Client:
    sent = []
    class chat:
        class completions:
            @staticmethod
            def create(**kw):
                _Client.sent.append(kw["messages"][1]["content"]); return _Resp()
from touchstone import audit as _audit
fpage = {u: {"status": "OK", "text": "Two rival operators run networks alongside Mobilis in Algeria, covering 98% of the population."}
         for u in ("https://a.dz/x", "https://b.dz/y", "https://c.dz/z")}
list(_audit(frag, _Client, pages=fpage, only={3}))
assert _Client.sent and "CLAIM:\nwhich operates alongside two rival operators" in _Client.sent[0] and whole in _Client.sent[0], _Client.sent
import providers as _PV
assert whole in _PV.gemini_prompt(["which operates alongside two rival operators"], "page", [whole])

# URLs with parentheses (2026-10-16): balanced "(...)" stays in the URL, the link's own ")"
# ends it; "<url>" destinations too. Bare URLs in prose still stop at an unbalanced ")".
par = ("1. The Zephyr cluster reached 2.1 exaflops in 2026. [Wiki](https://en.wikipedia.org/wiki/Zephyr_(computer))\n"
       "2. Its hall covers 4,200 m2 in total. [Doc](<https://docs.example.org/hall_(2026).pdf>) Built in 18 months.\n"
       "3. Cooling uses 12 MW of power (see https://example.org/cooling).")
assert blocks(par) == [("The Zephyr cluster reached 2.1 exaflops in 2026.", ("https://en.wikipedia.org/wiki/Zephyr_(computer)",)),
                       ("Its hall covers 4,200 m2 in total.", ("https://docs.example.org/hall_(2026).pdf",)),
                       ("Built in 18 months.", ()),
                       ("Cooling uses 12 MW of power (see", ("https://example.org/cooling",))], blocks(par)
assert md_links("[a](https://x.org/A_(b)_c) [d](https://y.org/e)") == [
    (0, 26, "https://x.org/A_(b)_c"), (27, 47, "https://y.org/e")]
import time as _t
_t0 = _t.monotonic()
blocks("[a](https://x.org/" + "(" * 20000 + ")\n" + "https://x.org/" + "(a" * 20000)
assert _t.monotonic() - _t0 < 1
# A Total row with an empty first cell ("||19,276,767 |") keeps every value under its header.
assert blocks("| Name | 1998 census | 2008 census |\n|---|---|---|\n||19,276,767 | 24,080,030 | [W](https://x.org/a)") == [
    ("1998 census: 19,276,767; 2008 census: 24,080,030", ("https://x.org/a",))]
assert blocks("| Code | Name | 1998 | 2008 |\n|---|---|---|---|\n| Total | | 19,276 | 24,080 | [W](https://x.org/a)") == [
    ("Code: Total; 1998: 19,276; 2008: 24,080", ("https://x.org/a",))]

print("parsing checks passed")
