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

# A blocked page becomes SOURCE UNREACHABLE with the reason shown, and costs no model call.
url = "https://example.com/page"
ev = [e for e in audit(f"- Algeria has 7,800 startups {url}", None,
                       pages={url: {"url": url, "status": "BLOCKED", "detail": F.BOT_BLOCKED}})
      if e["type"] == "claim"][0]
assert ev["label"] == "SOURCE UNREACHABLE" and ev["reason"] == "The site blocked the checker (bot protection).", ev


# Claim cap: the first max_claims cited claims in report order are checked (a claim without
# numbers is not pushed back); the rest come as "skipped" events labelled NOT CHECKED.
report = "\n".join(f"- Claim {i} {'has no figures' if i == 5 else f'says {i * 11}%'} https://example.com/{i}"
                   for i in range(1, 12))
events = list(audit(report, None, pages={}, max_claims=10))
assert events[0] == {"type": "start", "cited": 11, "checked": 10, "uncited": 0, "limit": 10}, events[0]
assert [e["claim"] for e in events if e["type"] == "claim"] == list(range(1, 11))
assert [(e["claim"], e["label"]) for e in events if e["type"] == "skipped"] == [(11, "NOT CHECKED")]

# report3 (regression set, labels3.json): 18 cited claims; claim 5 (transport, no digits) was
# skipped in production by the old numbers-first cap. Report order checks claims 1-10.
c = cited("report3.txt")
assert len(c) == 18 and c[4][0].startswith("The transport sector remains a weak point"), c[4]
from touchstone import select
assert select(c, 10) == set(range(10))

print("parsing checks passed")
