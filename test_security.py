"""Token-free security checks (needs network). Run: .venv/bin/python test_security.py"""
import ipaddress
import socket
import time

import fetch_links as F

# 1. DNS rebinding: a host that resolves public on the check and to 127.0.0.1 afterwards
#    must be fetched from the checked IP, with exactly one DNS lookup.
public_ip = socket.getaddrinfo("example.com", 80, type=socket.SOCK_STREAM)[0][4][0]
real_getaddrinfo, lookups, peers = socket.getaddrinfo, [], []


def rebinding(host, *a, **k):
    if host == "rebind.example":
        lookups.append(host)
        ip = public_ip if len(lookups) == 1 else "127.0.0.1"
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (ip, 80))]
    return real_getaddrinfo(host, *a, **k)


real_peer_ok = F.peer_ok


def spy(r):
    stream = r.extensions.get("network_stream")
    peers.append(stream.get_extra_info("server_addr")[0] if stream else None)
    return real_peer_ok(r)


socket.getaddrinfo, F.peer_ok = rebinding, spy
F.fetch("http://rebind.example/path?q=1")
socket.getaddrinfo, F.peer_ok = real_getaddrinfo, real_peer_ok
assert lookups == ["rebind.example"] and peers == [public_ip], (lookups, peers)

# 2. TLS is still verified against the hostname, not the pinned IP: 8.8.8.8's certificate
#    covers the IP 8.8.8.8 but not example.com, so this must fail.
real_check = F.check_url


async def wrong_ip(url):
    return True, "", ipaddress.ip_address("8.8.8.8")


F.check_url = wrong_ip
assert F.fetch("https://example.com/")["status"] == "ERROR"
F.check_url = real_check

# 3. Private targets stay blocked, directly and through redirects or IPv6 forms.
for url in ("http://127.0.0.1/", "http://[::ffff:127.0.0.1]/", "http://10.0.0.1/",
            "http://httpbin.org/redirect-to?url=http://169.254.169.254/"):
    assert F.fetch(url)["status"] == "BLOCKED", url

# 4. Client IP: only the configured header counts, junk falls back, tables get pruned.
import app as A

A.CLIENT_IP_HEADER = "True-Client-IP"
from starlette.datastructures import Headers

Req = lambda h, peer="10.0.0.5": type("R", (), {"headers": Headers(h), "client": type("C", (), {"host": peer})})()
assert A.client_ip(Req({"true-client-ip": "203.0.113.7", "x-forwarded-for": "1.2.3.4"})) == "203.0.113.7"
assert A.client_ip(Req({"true-client-ip": "<script>"})) == "10.0.0.5"
A.CLIENT_IP_HEADER = ""
assert A.client_ip(Req({"true-client-ip": "203.0.113.7"})) == "10.0.0.5"
A.hits["198.51.100.1"].append(time.time() - 4000)
A.last_prune = time.time() - A.PRUNE_EVERY - 1
A.rate_limited("192.0.2.1")
assert "198.51.100.1" not in A.hits and "192.0.2.1" in A.hits

# 4b. Worker header: trusted only with the right PROXY_SECRET; otherwise the old logic.
A.CLIENT_IP_HEADER, A.PROXY_SECRET = "X-Real-IP", "s3cret-test-value"
W = lambda secret=None, ip="203.0.113.50": Req({"x-real-ip": "198.51.100.9", "x-touchstone-client-ip": ip,
                                                **({"x-touchstone-proxy-secret": secret} if secret is not None else {})})
assert A.client_ip(W("s3cret-test-value")) == "203.0.113.50"          # correct secret
assert A.client_ip(W("wrong")) == "198.51.100.9"                      # wrong secret
assert A.client_ip(W("s3cret-test-valuex")) == "198.51.100.9"
assert A.client_ip(W()) == "198.51.100.9"                             # no secret header
assert A.client_ip(W("")) == "198.51.100.9"
assert A.client_ip(W("s3cret-test-value", "not-an-ip")) == "198.51.100.9"   # invalid IP: fallback
assert A.client_ip(W("s3cret-test-value", "")) == "198.51.100.9"
A.PROXY_SECRET = ""                                                   # unset: header ignored
assert A.client_ip(W("")) == A.client_ip(W("s3cret-test-value")) == "198.51.100.9"
A.PROXY_SECRET = "s3cret-test-value"
a, b = (A.rate_key(A.client_ip(W("s3cret-test-value", ip))) for ip in ("203.0.113.61", "203.0.113.62"))
assert a != b
A.hits.clear()
for _ in range(A.RATE_LIMIT):
    assert not A.rate_limited(a)
assert A.rate_limited(a) and not A.rate_limited(b)                    # separate buckets
v6 = [A.rate_key(A.client_ip(W("s3cret-test-value", ip))) for ip in ("2001:db8:1:2::1", "2001:db8:1:2::9")]
assert v6[0] == v6[1] == "2001:db8:1:2::/64"                          # /64 bucketing kept
A.hits.clear()
A.CLIENT_IP_HEADER, A.PROXY_SECRET = "", ""

# 5. IPv6: one /64 is one visitor, so rotating addresses inside it doesn't reset the limit.
assert A.rate_key("2001:db8:abcd:12::1") == A.rate_key("2001:db8:abcd:12::ffff") == "2001:db8:abcd:12::/64"
assert A.rate_key("2001:db8:abcd:13::1") != A.rate_key("2001:db8:abcd:12::1")
assert A.rate_key("::ffff:203.0.113.7") == "203.0.113.7"

# 6. Daily cap: full at GLOBAL_AUDITS_PER_DAY, and a new UTC day starts from zero.
A.daily.update(day=A.utc_today(), count=A.DAILY_LIMIT)
assert A.daily_used_up()
A.daily.update(day=A.utc_today() - __import__("datetime").timedelta(days=1))
assert not A.daily_used_up() and A.daily["count"] == 0

# 7. Fail-closed accounting: an audit counts at its first model call attempt, even if the
#    call fails or reports no tokens; an audit that never calls the model doesn't count.
A.daily.update(day=A.utc_today(), count=0)
def failing(**k): raise TimeoutError("timed out")
wrapped = A.CountingClient(__import__("types").SimpleNamespace(
    chat=__import__("types").SimpleNamespace(completions=__import__("types").SimpleNamespace(create=failing))))
for _ in range(3):
    try: wrapped.chat.completions.create(model="x")
    except TimeoutError: pass
assert A.daily["count"] == 1
A.CountingClient(None)
assert A.daily["count"] == 1

# 8. Groq 429s: per-day (or unclear) means the day's capacity is gone; per-minute doesn't.
import touchstone
Err = lambda msg, code=429: type("E", (Exception,), {"status_code": code})(msg)
assert touchstone.quota_scope(Err("on tokens per day (TPD): Limit 200000")) == "day"
assert touchstone.quota_scope(Err("on requests per day (RPD)")) == "day"
assert touchstone.quota_scope(Err("Too many requests")) == "day"
assert touchstone.quota_scope(Err("on tokens per minute (TPM): Limit 8000")) == "minute"
assert touchstone.quota_scope(Err("server error", 500)) is None
assert touchstone.quota_scope(TimeoutError("x")) is None

# 9. Heartbeat: a slow model call keeps the stream alive with heartbeat lines, and the audit
#    still completes (fake model and pages: no network, no tokens).
import json, types as T, warnings
warnings.filterwarnings("ignore", message=".*httpx.*")   # starlette's TestClient deprecation notice
from fastapi.testclient import TestClient

def slow_create(**k):
    time.sleep(0.7)
    content = json.dumps({"parts": [{"text": "Yassir raised 150 million dollars", "kind": "fact",
                                     "status": "stated", "quote": "Yassir raised 150 million dollars"}]})
    return T.SimpleNamespace(choices=[T.SimpleNamespace(message=T.SimpleNamespace(content=content))],
                             usage=T.SimpleNamespace(total_tokens=10))

page = {"status": "OK", "text": "Yassir raised 150 million dollars in its Series B round. " * 6}
real_audit, real_client, real_beat = A.audit, A.client, A.HEARTBEAT_SECONDS
A.audit = lambda report, client, **k: real_audit(report, client, pages={"https://example.com/y": page}, **k)
A.client = T.SimpleNamespace(chat=T.SimpleNamespace(completions=T.SimpleNamespace(create=slow_create)))
A.HEARTBEAT_SECONDS = 0.2
A.hits.clear(); A.daily.update(day=A.utc_today(), count=0)
with TestClient(A.app) as tc:
    r = tc.post("/api/audit", json={"report": "- Yassir raised 150 million dollars https://example.com/y"})
    lines = [json.loads(x) for x in r.text.splitlines() if x]
types_seen = [x["type"] for x in lines]
assert "heartbeat" in types_seen and types_seen[-1] == "done", types_seen
assert [x["label"] for x in lines if x["type"] == "claim"] == ["SOURCED"], lines
assert A.busy.acquire(blocking=False); A.busy.release()           # lock released after the audit
A.audit, A.client, A.HEARTBEAT_SECONDS = real_audit, real_client, real_beat
A.hits.clear()

# 10. examples/ui_check.txt (DEPLOY.md's zero-token UI check on production): 11 nonsense
#     claims on the live IANA page. None may reach the model (no shared keyword or anchor ->
#     UNVERIFIED before any call), so it never counts toward the daily cap; claim 11 is skipped.
import fetch_links
url = "https://www.iana.org/help/example-domains"
iana = fetch_links.fetch(url)
assert iana["status"] == "OK", iana
def no_model(**k): raise AssertionError("ui_check.txt reached the model")
boom = A.CountingClient(T.SimpleNamespace(chat=T.SimpleNamespace(completions=T.SimpleNamespace(create=no_model))))
A.daily.update(day=A.utc_today(), count=0)
ev = list(real_audit(open("examples/ui_check.txt").read(), boom, pages={url: iana}, max_claims=A.MAX_CLAIMS))
assert ev[0]["cited"] == 11 and ev[0]["checked"] == 10, ev[0]
assert [e["label"] for e in ev if e["type"] == "claim"] == ["UNVERIFIED"] * 10
assert [e["claim"] for e in ev if e["type"] == "skipped"] == [11] and ev[-1] == {"type": "done", "tokens": 0}
assert A.daily["count"] == 0

# 11. Cache-busting: index.html links each asset as /static/<name>?v=<hash of its content>;
#     the hash changes with the file. Versioned URL -> immutable for a year; plain URL and the
#     page itself -> no-cache. URLs stay same-origin, so the CSP (script-src 'self') holds.
import re, tempfile
from pathlib import Path
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    (d / "index.html").write_text('<link href="/static/style.css"><script src="/static/app.js"></script>'
                                  '<script src="/static/missing.js"></script>')
    (d / "style.css").write_text("body{}"); (d / "app.js").write_text("one")
    v1 = A.versioned_index(d, A.asset_versions(d))
    (d / "app.js").write_text("two")
    v2 = A.versioned_index(d, A.asset_versions(d))
js = lambda html: re.search(r'src="/static/app\.js\?v=([0-9a-f]{12})"', html)[1]
css = lambda html: re.search(r'href="/static/style\.css\?v=([0-9a-f]{12})"', html)[1]
assert js(v1) != js(v2) and css(v1) == css(v2)
assert 'src="/static/missing.js"' in v1                                # unknown file: left alone
with TestClient(A.app) as tc:
    page = tc.get("/")
    assert page.headers["cache-control"] == "no-cache"
    assert "script-src 'self'" in page.headers["content-security-policy"]
    refs = re.findall(r'(?:src|href)="(/static/[^"]+)"', page.text)
    assert len(refs) == 2 and all(re.search(r"\?v=[0-9a-f]{12}$", r) for r in refs), refs
    for ref in refs:
        r = tc.get(ref)
        assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=31536000, immutable", ref
        bare = tc.get(ref.split("?")[0])
        assert bare.headers["cache-control"] == "no-cache" and bare.content == r.content
        assert tc.get(ref.split("?")[0] + "?v=000000000000").headers["cache-control"] == "no-cache"
    assert tc.get("/static/nope.js?v=").status_code == 404

# 12. Groq per-minute pacing (pacing.py): fake client and fake clock, no real sleeping.
import pacing
class Clock:
    def __init__(self): self.t, self.slept = 1000.0, []
    def __call__(self): return self.t
    def sleep(self, s): self.slept.append(s); self.t += s
def reply(tokens=1700):
    content = json.dumps({"parts": [{"text": "Yassir raised 150 million dollars", "kind": "fact",
                                     "status": "stated", "quote": "Yassir raised 150 million dollars"}]})
    return T.SimpleNamespace(choices=[T.SimpleNamespace(message=T.SimpleNamespace(content=content))],
                             usage=T.SimpleNamespace(total_tokens=tokens))
def Groq429(msg, retry=None):
    e = type("RateLimitError", (Exception,), {"status_code": 429})(msg)
    e.response = T.SimpleNamespace(headers={"retry-after": retry} if retry else {})
    return e
TPM = "Rate limit reached for model on tokens per minute (TPM): Limit 8000, Used 7900. Please try again in 7.5s."
TPD = "Rate limit reached for model on tokens per day (TPD): Limit 200000. Please try again in 12m3s."
def scripted(*outcomes):
    calls = []
    def create(**k):
        calls.append(1)
        o = outcomes[min(len(calls), len(outcomes)) - 1]
        if isinstance(o, Exception): raise o
        return o
    return T.SimpleNamespace(chat=T.SimpleNamespace(completions=T.SimpleNamespace(create=create))), calls
page_y = {"status": "OK", "text": "Yassir raised 150 million dollars in its Series B round. " * 6}
pages3 = {f"https://example.com/{i}": page_y for i in range(3)}
report3 = "\n".join(f"- Yassir raised 150 million dollars https://example.com/{i}" for i in range(3))

# 12a. retry-after: header first, then Groq's message, else a fallback; capped at 60 s.
assert pacing.retry_after(Groq429(TPM, retry="3")) == 3.5
assert pacing.retry_after(Groq429(TPM)) == 8.0
assert pacing.retry_after(Groq429("try again in 1m2.5s")) == 60.0          # capped
assert pacing.retry_after(Groq429("try again in 450ms")) == 0.95
assert pacing.retry_after(Groq429("Too many requests")) == pacing.RETRY_FALLBACK + 0.5

# 12b. A per-minute 429, then success: the same claim is resent after a "wait" event and the
#      audit completes with every claim. The retry doesn't count twice toward the daily cap.
clk = Clock()
fake, calls = scripted(reply(), Groq429(TPM), reply())
A.daily.update(day=A.utc_today(), count=0)
ev = list(real_audit(report3, A.CountingClient(fake), pages=pages3, deadline=clk() + 300,
                     clock=clk, sleep=clk.sleep, pacer=pacing.TokenPacer(clock=clk)))
assert [e["label"] for e in ev if e["type"] == "claim"] == ["SOURCED"] * 3, ev
waits = [e for e in ev if e["type"] == "wait"]
assert waits == [{"type": "wait", "seconds": 8, "claim": 2}] and 8.0 in clk.slept, (waits, clk.slept)
assert len(calls) == 4 and A.daily["count"] == 1 and ev[-1]["type"] == "done"

# 12c. A per-day 429 stops the audit cleanly (claims so far kept, no retry).
clk = Clock()
fake, calls = scripted(reply(), Groq429(TPD))
ev = list(real_audit(report3, fake, pages=pages3, deadline=clk() + 300, clock=clk, sleep=clk.sleep,
                     pacer=pacing.TokenPacer(clock=clk)))
assert [e["type"] for e in ev if e["type"] != "start"] == ["claim", "quota", "done"], ev
assert ev[2] == {"type": "quota", "scope": "day", "checked": 1} and len(calls) == 2 and not clk.slept

# 12d. Proactive: with ~7.5K tokens spent in the last minute, the next call waits until the
#      oldest spend leaves the window, then goes out. No 429 needed.
clk = Clock()
pacer = pacing.TokenPacer(clock=clk)
for _ in range(4):
    pacer.record(1700); clk.t += 5                       # 6,800 tokens over 20 s
assert pacer.wait_needed() == 40.0                       # now t=1020; t=1000's spend leaves at 1060
fake, calls = scripted(reply())
ev = list(real_audit(report3.split("\n")[0], fake, pages=pages3, deadline=clk() + 300,
                     clock=clk, sleep=clk.sleep, pacer=pacer))
assert [e for e in ev if e["type"] == "wait"] == [{"type": "wait", "seconds": 40, "claim": 1}]
assert clk.slept == [40.0] and [e["label"] for e in ev if e["type"] == "claim"] == ["SOURCED"]
assert pacing.TokenPacer(clock=clk).wait_needed() == 0                 # empty window: no wait

# 12e. A wait that would pass the 5-minute deadline is not taken: that claim and the rest are
#      NOT CHECKED (time limit), nothing is slept, and the audit ends normally.
clk = Clock()
fake, calls = scripted(reply(), Groq429(TPM, retry="50"))
ev = list(real_audit(report3, fake, pages=pages3, deadline=clk() + 20, clock=clk, sleep=clk.sleep,
                     pacer=pacing.TokenPacer(clock=clk)))
assert [e["label"] for e in ev if e["type"] == "claim"] == ["SOURCED", "NOT CHECKED", "NOT CHECKED"], ev
assert "waiting for model capacity" in ev[2]["reason"] and not clk.slept and ev[-1]["type"] == "done"

# 12f. Timeouts / 5xx get 2 retries (what the SDK's own retries did), then an ERROR card.
clk = Clock()
boom = type("APITimeoutError", (Exception,), {})("timed out")
fake, calls = scripted(boom, boom, reply())
ev = list(real_audit(report3.split("\n")[0], fake, pages=pages3, clock=clk, sleep=clk.sleep,
                     pacer=pacing.TokenPacer(clock=clk)))
assert [e["label"] for e in ev if e["type"] == "claim"] == ["SOURCED"] and clk.slept == [1, 2]
fake, calls = scripted(boom)
ev = list(real_audit(report3.split("\n")[0], fake, pages=pages3, clock=clk, sleep=clk.sleep,
                     pacer=pacing.TokenPacer(clock=clk)))
assert [e["label"] for e in ev if e["type"] == "claim"] == ["ERROR"] and len(calls) == 3
A.daily.update(day=A.utc_today(), count=0)

print("security checks passed")
