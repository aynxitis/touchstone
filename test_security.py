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
# S2 (2026-10-11 incident: enforced on deploy, production answered 403 to everything).
# Enforcement is opt-in (REQUIRE_PROXY_SECRET=1); off = exactly the pre-a40f4f4 behaviour.
import logging, warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore")                 # starlette's TestClient deprecation notice
    from fastapi.testclient import TestClient

def worker_shaped(client_ip, secret):
    """A request as cloudflare/worker.js sends it (same header names and casing), plus the
    headers Cloudflare and Railway's edge add on the way."""
    return {"Host": "example-service.up.railway.app", "X-Touchstone-Client-IP": client_ip,
            "X-Touchstone-Proxy-Secret": secret, "CF-Connecting-IP": client_ip,
            "CF-Ray": "8c1d2e3f4a5b6c7d-AMS", "CF-Worker": "aynx.dev", "X-Real-IP": "172.71.0.9",
            "X-Forwarded-For": f"{client_ip}, 172.71.0.9", "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "example-service.up.railway.app", "User-Agent": "Mozilla/5.0"}

class Logs(logging.Handler):
    def __init__(self):
        super().__init__(); self.lines = []
    def emit(self, record):
        self.lines.append(record.getMessage())
logs = Logs(); A.log.addHandler(logs)
SECRET = "s3cret-test-value"
paths = [("GET", "/"), ("GET", "/static/app.js"), ("GET", "/static/style.css?v=" + A.ASSET_VERSIONS["style.css"]),
         ("GET", "/api/example")]
with TestClient(A.app) as tc:
    # Flag off (default): nothing is refused, with or without a secret.
    A.REQUIRE_PROXY_SECRET = False
    for hdrs in ({}, {"X-Touchstone-Proxy-Secret": "wrong"}, worker_shaped("197.112.4.25", SECRET)):
        assert all(tc.request(m, p, headers=hdrs).status_code == 200 for m, p in paths)
    assert tc.get("/healthz/proxy").json() == {"via_worker": False}
    assert tc.get("/healthz/proxy", headers=worker_shaped("197.112.4.25", SECRET)).json() == {"via_worker": True}
    assert tc.get("/healthz/proxy", headers=worker_shaped("197.112.4.25", "wrong")).json() == {"via_worker": False}
    # A false answer logs why (server side only), never the value sent.
    assert logs.lines == ["healthz/proxy: via_worker false (missing header)",
                          "healthz/proxy: via_worker false (mismatch)"], logs.lines
    logs.lines.clear()
    # Flag on: a Worker-shaped request with the right secret passes, IPv6 and IPv4, every route.
    A.REQUIRE_PROXY_SECRET = True
    for ip in ("2001:db8:85a3::8a2e:370:7334", "197.112.4.25"):
        h = worker_shaped(ip, SECRET)
        for m, p in paths:
            assert tc.request(m, p, headers=h).status_code == 200, (ip, m, p)
        assert tc.post("/api/audit", headers=h, json={"report": "Algeria has 7,800 startups."}).status_code == 200
        assert tc.get("/healthz/proxy", headers=h).json() == {"via_worker": True}
    assert logs.lines == []
    # ...and anything else is refused and logged with reason + path, never a header value.
    for hdrs, why in (({}, "missing header"), (worker_shaped("197.112.4.25", ""), "missing header"),
                      (worker_shaped("197.112.4.25", "wrong-value"), "mismatch"),
                      (worker_shaped("not-an-ip", SECRET), "malformed client IP")):
        for m, p in paths:
            assert tc.request(m, p, headers=hdrs).status_code == 403, (why, p)
        assert tc.post("/api/audit", json={"report": "x"}, headers=hdrs).status_code == 403
        assert logs.lines[-1] == f"proxy check refused POST /api/audit: {why}", logs.lines[-1]
    assert all(SECRET not in l and "wrong-value" not in l and "197.112" not in l for l in logs.lines)
    # Health checks are never refused.
    assert tc.get("/healthz").status_code == 200 and tc.get("/healthz/proxy").json() == {"via_worker": False}
    A.PROXY_SECRET = ""                             # unset on the server: said so in the log
    A.REQUIRE_PROXY_SECRET = False
    assert tc.get("/healthz/proxy", headers=worker_shaped("197.112.4.25", SECRET)).json() == {"via_worker": False}
    assert logs.lines[-1] == "healthz/proxy: via_worker false (PROXY_SECRET unset on the server)"
    A.PROXY_SECRET = SECRET
A.log.removeHandler(logs)

# The same through a real uvicorn process started as railpack does, with a trailing newline
# in the env value: the incident's request shape over real HTTP.
import os as _os, subprocess as _sp, sys as _sys, socket as _sock
with _sock.socket() as _s:
    _s.bind(("127.0.0.1", 0)); port = _s.getsockname()[1]
env = {**_os.environ, "PROXY_SECRET": SECRET + "\n", "REQUIRE_PROXY_SECRET": "1", "PROVIDER": "groq"}
srv = _sp.Popen([_os.path.join(_os.path.dirname(_sys.executable), "uvicorn"), "app:app", "--host", "127.0.0.1",
                 "--port", str(port), "--workers", "1", "--no-proxy-headers"], env=env,
                stdout=_sp.DEVNULL, stderr=_sp.PIPE, text=True)
try:
    import httpx as _hx
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            _hx.get(base + "/healthz", trust_env=False); break
        except _hx.HTTPError:
            time.sleep(0.1)
    with _hx.Client(base_url=base, trust_env=False) as c:
        for ip in ("2001:db8:85a3::8a2e:370:7334", "197.112.4.25"):
            assert c.get("/", headers=worker_shaped(ip, SECRET)).status_code == 200
            assert c.post("/api/audit", headers=worker_shaped(ip, SECRET),
                          json={"report": "Algeria has 7,800 startups."}).status_code == 200
        assert c.get("/", headers={"X-Touchstone-Proxy-Secret": "nope"}).status_code == 403
        assert c.get("/healthz/proxy", headers=worker_shaped("197.112.4.25", SECRET)).json() == {"via_worker": True}
finally:
    srv.terminate(); err = srv.communicate(timeout=10)[1]
assert "proxy check refused GET /: mismatch" in err and SECRET not in err, err[-500:]
# Enforcing with no secret would lock everyone out: the app refuses to start instead.
bad = _sp.run([_sys.executable, "-c", "import app"], env={**_os.environ, "REQUIRE_PROXY_SECRET": "1", "PROXY_SECRET": ""},
              capture_output=True, text=True)
assert bad.returncode != 0 and "REQUIRE_PROXY_SECRET=1 needs PROXY_SECRET" in bad.stderr, bad.stderr[-300:]
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

# 13. Providers (providers.py): Gemini batches claims per cited page; Groq is unchanged.
import providers as PV, quote_check as QC
from quote_check import SYSTEM, SYSTEM_MULTI, PREAMBLE, TASK_ONE, RULES
assert SYSTEM == PREAMBLE + TASK_ONE + RULES and SYSTEM_MULTI.endswith(RULES)      # rules shared verbatim
import hashlib
assert hashlib.sha256(SYSTEM.encode()).hexdigest()[:16] == "84557bb787297a70"       # Groq prompt pinned
# Parts in the claim's language (cross-language coverage, L2): both providers' prompts say so.
assert "SAME language as the claim" in SYSTEM and "SAME language as the claim" in SYSTEM_MULTI

class FakeGemini:
    """google-genai lookalike: client.models.generate_content(model, contents, config)."""
    def __init__(self, reply, tokens=5000, errors=()):
        self.calls, self.reply, self.tokens, self.errors = [], reply, tokens, list(errors)
        self.models = T.SimpleNamespace(generate_content=self._gen)
    def _gen(self, **k):
        self.calls.append(k)
        if self.errors:
            raise self.errors.pop(0)
        body = self.reply(k["contents"]) if callable(self.reply) else self.reply
        return T.SimpleNamespace(text=body, usage_metadata=T.SimpleNamespace(total_token_count=self.tokens))

def claims_in(contents):
    return [l.split("] ", 1)[1] for l in contents.split("\n<<<")[0].split("\n") if l.startswith("[")]

def all_stated(contents):
    """Every claim: one fact, stated, quoting the line that holds its figure."""
    out = []
    for i, c in enumerate(claims_in(contents), 1):
        num = c.split()[-1]
        line = next(l for l in contents.split("\n") if l.startswith("Fact line") and num in l)
        out.append({"id": i, "opinion": False, "parts": [{"text": c, "kind": "fact", "status": "stated", "quote": line}]})
    return json.dumps({"claims": out})

gp = lambda n: {"status": "OK", "text": "\n".join(f"Fact line {i}: the widget count reached {1000 + i} units in the region." for i in range(n))}
gpages = {"https://a.example/1": gp(5), "https://b.example/2": gp(5)}
greport = "\n".join([
    "- Widget count reached 1001 https://a.example/1",
    "- Widget count reached 1002 https://b.example/2",
    "- Widget count reached 1003 https://a.example/1",
    "- Zzqvx flarnbeck 4242 https://a.example/1",            # no passage: never sent
    "- Widget count reached 1004 https://b.example/2"])

# 13a. Grouping by URL: one call per cited page with all its claims; results in report order.
clk = Clock()
fake = FakeGemini(all_stated)
gem = PV.Gemini(fake)
ev = list(real_audit(greport, fake, pages=gpages, clock=clk, sleep=clk.sleep, provider=gem,
                     pacer=pacing.TokenPacer.for_provider("gemini", clock=clk)))
assert len(fake.calls) == 2, len(fake.calls)
assert claims_in(fake.calls[0]["contents"]) == ["Widget count reached 1001", "Widget count reached 1003"]
assert claims_in(fake.calls[1]["contents"]) == ["Widget count reached 1002", "Widget count reached 1004"]
assert fake.calls[0]["model"] == PV.GEMINI_MODEL and fake.calls[0]["config"].temperature == 0
assert fake.calls[0]["config"].system_instruction == SYSTEM_MULTI
assert fake.calls[0]["config"].response_mime_type == "application/json"
cl = [e for e in ev if e["type"] == "claim"]
assert [e["claim"] for e in cl] == [1, 2, 3, 4, 5]
assert [e["label"] for e in cl] == ["SOURCED", "SOURCED", "SOURCED", "UNVERIFIED", "SOURCED"], [e["label"] for e in cl]
assert sum(e["tokens"] for e in cl) == 10000 and ev[-1] == {"type": "done", "tokens": 10000}

# 13b. Schema mapping: by id, malformed/missing entries become that claim's ERROR (never a
#      verdict), extra ids are ignored, code checks still decide (a fake quote is rejected).
page_a = gpages["https://a.example/1"]["text"]
bad = json.dumps({"claims": [
    {"id": 2, "opinion": False, "parts": [{"text": "Widget count reached 1003", "kind": "fact", "status": "stated",
                                           "quote": "Fact line 3: the widget count reached 1003 units in the region."}]},
    {"id": 1, "opinion": False, "parts": [{"text": "Widget count reached 1001", "kind": "fact", "status": "stated",
                                           "quote": "An invented sentence that is not on the page at all."}]},
    {"id": 9, "opinion": True, "parts": []}, "junk"]})
res = PV.map_results(bad, ["Widget count reached 1001", "Widget count reached 1003", "Third"], page_a,
                     "https://a.example/1", None, 7)
# Claim 1's invented quote is rejected; A2 then finds the page line with 1001: amber, not SOURCED.
assert [r["label"] for r in res] == ["COULDN'T CONFIRM", "SOURCED", "ERROR"], [r["label"] for r in res]
assert res[0]["facts"][0]["rejected_quote"] and res[0]["facts"][0]["status"] == "possible"
assert [r["tokens"] for r in res] == [3, 2, 2]
assert [r["label"] for r in PV.map_results("not json", ["a"], page_a, "", None, 0)] == ["ERROR"]
assert all(isinstance(r.get("model"), (dict, type(None))) for r in res)            # rescore.py replays these

# 13c. 100K-char cap: a short page goes whole; a long one keeps the claims' anchor passages
#      plus surrounding lines up to the cap, skipped stretches marked "[...]".
assert PV.page_for_model(page_a, ["x"]) == page_a
filler = [f"Filler paragraph {i} about something else entirely, nothing to see here at all." for i in range(4000)]
target = "The flagship plant produced 48,213 tonnes of output in 2025 according to the ministry."
long_page = "\n".join(filler[:2000] + [target] + filler[2000:])
assert len(long_page) > 300_000
sent = PV.page_for_model(long_page, ["The plant produced 48,213 tonnes in 2025"])
assert len(sent) <= PV.PAGE_CHARS and target in sent and "[...]" in sent
assert all(l == "[...]" or l in long_page for l in sent.split("\n"))               # lines verbatim
assert sent.index(target) > 1000                                                   # context kept above it too
assert QC.quote_on_page(target, long_page)

# 13d. Pacing per provider: Gemini RPM (13 per minute), TPM (225K), RPD (450 per day).
clk = Clock()
gpace = pacing.TokenPacer.for_provider("gemini", clock=clk)
for _ in range(13):
    gpace.note_request(); clk.t += 1                       # 13 requests in 13 s
assert gpace.wait_needed(1000) == 47.0                     # the first leaves the minute at t=1060
clk.t += 47
assert gpace.wait_needed(1000) == 0
gpace.record(220_000)
assert gpace.wait_needed(10_000) == 60.0                   # 220K + 10K > 225K: wait out the minute
day = [1]
dpace = pacing.TokenPacer(budget=10**9, rpd=3, clock=clk, day=lambda: day[0])
for _ in range(3):
    assert dpace.wait_needed(1) == 0; dpace.note_request()
assert dpace.wait_needed(1) == pacing.DAY_FULL             # today's requests used up
day[0] = 2
assert dpace.wait_needed(1) == 0                           # a new UTC day
assert pacing.TokenPacer.for_provider("groq").rpm is None and pacing.TokenPacer.for_provider("groq").budget == 7_500

# 13e. RPD exhausted mid-audit stops like a per-day quota; a Gemini per-minute 429 waits its
#      retryDelay and resends the same page's claims; a per-day 429 stops.
clk = Clock()
fake = FakeGemini(all_stated)
dpace = pacing.TokenPacer(budget=10**9, rpd=1, clock=clk)
ev = list(real_audit(greport, fake, pages=gpages, clock=clk, sleep=clk.sleep, provider=PV.Gemini(fake), pacer=dpace))
assert len(fake.calls) == 1 and {"type": "quota", "scope": "day", "checked": 1} in ev, ev
GErr = lambda code, msg: type("ClientError", (Exception,), {"code": code})(msg)
g_min = GErr(429, "429 RESOURCE_EXHAUSTED. Quota exceeded for metric generate_content_free_tier_requests, "
                  "quotaId GenerateRequestsPerMinutePerProjectPerModel-FreeTier. Please retry in 21.4s.")
g_day = GErr(429, "429 RESOURCE_EXHAUSTED. quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier")
assert touchstone.quota_scope(g_min) == "minute" and touchstone.quota_scope(g_day) == "day"
assert pacing.retry_after(g_min) == 21.9
assert pacing.retry_after(GErr(429, "{'retryDelay': '34s'}")) == 34.5
clk = Clock()
fake = FakeGemini(all_stated, errors=[g_min])
ev = list(real_audit(greport, fake, pages=gpages, clock=clk, sleep=clk.sleep, provider=PV.Gemini(fake),
                     deadline=clk() + 300, pacer=pacing.TokenPacer.for_provider("gemini", clock=clk)))
assert [e for e in ev if e["type"] == "wait"] == [{"type": "wait", "seconds": 22, "claim": 1}]
assert len(fake.calls) == 3 and [e["label"] for e in ev if e["type"] == "claim"].count("SOURCED") == 4
clk = Clock()
fake = FakeGemini(all_stated, errors=[g_day])
ev = list(real_audit(greport, fake, pages=gpages, clock=clk, sleep=clk.sleep, provider=PV.Gemini(fake),
                     pacer=pacing.TokenPacer.for_provider("gemini", clock=clk)))
assert ev[1] == {"type": "quota", "scope": "day", "checked": 0} and len(fake.calls) == 1

# 13f. The daily cap counts a Gemini audit once (first generate_content attempt), and the
#      Groq path through app.py is unchanged (one chat call per claim, as in 12b).
A.daily.update(day=A.utc_today(), count=0)
clk = Clock()
fake = FakeGemini(all_stated)
counted = A.CountingClient(fake)
list(real_audit(greport, counted, pages=gpages, clock=clk, sleep=clk.sleep, provider=PV.Gemini(counted),
                pacer=pacing.TokenPacer.for_provider("gemini", clock=clk)))
assert A.daily["count"] == 1 and len(fake.calls) == 2
A.daily.update(day=A.utc_today(), count=0)

# 13g. The provider note: only with Gemini, rendered server-side into the page.
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    (d / "index.html").write_text('<p class="meta">Limits.</p>\n<!--provider-note-->\n<script src="/static/app.js"></script>')
    (d / "app.js").write_text("x")
    v = A.asset_versions(d)
    assert "Google Gemini" in A.versioned_index(d, v, "gemini") and "provider-note" not in A.versioned_index(d, v, "gemini")
    assert "Gemini" not in A.versioned_index(d, v, "groq") and "provider-note" not in A.versioned_index(d, v, "groq")
    gem = A.versioned_index(d, v, "gemini")
    assert ("Google Gemini (free tier), which may use inputs to improve Google's products. "
            "Don't paste anything private.") in gem and 'class="notice"' in gem, gem

# S3: a private address never reaches the browser, only "private address".
r = F.fetch("http://10.0.0.1/x")
assert r["status"] == "BLOCKED" and r["detail"] == "private address", r
ev = [e for e in touchstone.audit("- Claim text here http://localhost/x", None) if e["type"] == "claim"]
assert ev[0]["label"] == "SOURCE UNREACHABLE" and "127.0.0.1" not in json.dumps(ev[0]), ev
assert ev[0]["sources"][0]["detail"] == "BLOCKED private address", ev
# S4: the fetch client ignores proxy/netrc settings from the environment.
_real_client, seen = F.httpx.AsyncClient, []
def _spy(*a, **k):
    seen.append(k.get("trust_env", True))
    return _real_client(*a, **k)
F.httpx.AsyncClient = _spy
try:
    F.fetch("http://10.0.0.1/y")
finally:
    F.httpx.AsyncClient = _real_client
assert seen == [False], seen


# 14. Fetch timeouts: a timed-out fetch is retried once with twice the read timeout, both
#     attempts inside TOTAL_SECONDS; blocks and HTTP errors are never retried.
import asyncio
def run_fetch(fake, **consts):
    saved = {k: getattr(F, k) for k in consts} | {"_get": F._get}
    for k, v in consts.items():
        setattr(F, k, v)
    F._get = fake
    try:
        t0 = time.monotonic()
        return asyncio.run(F.fetch_one("https://example.org/x")), time.monotonic() - t0
    finally:
        for k, v in saved.items():
            setattr(F, k, v)

seen = []
async def slow_then_ok(url, read_timeout=F.READ_TIMEOUT):
    seen.append(read_timeout)
    if len(seen) == 1:
        return {"url": url, "status": "TIMEOUT", "detail": ""}         # httpx read timeout
    return "<html><head><title>T</title></head><body><p>" + "Readable text. " * 40 + "</p></body></html>"
r, _ = run_fetch(slow_then_ok)
assert r["status"] == "OK" and seen == [F.READ_TIMEOUT, F.RETRY_READ_TIMEOUT], (r, seen)
assert F.RETRY_READ_TIMEOUT == 2 * F.READ_TIMEOUT

seen.clear()
async def blocked(url, read_timeout=F.READ_TIMEOUT):
    seen.append(read_timeout)
    return {"url": url, "status": "BLOCKED", "detail": F.BOT_BLOCKED}
r, _ = run_fetch(blocked)
assert r["status"] == "BLOCKED" and len(seen) == 1, (r, seen)              # never retried

seen.clear()
async def hangs(url, read_timeout=F.READ_TIMEOUT):
    seen.append(read_timeout)
    await asyncio.sleep(100)
# Scaled down: 0.6 s per attempt, 1.0 s per URL -> the retry gets the 0.4 s left, then stops.
r, took = run_fetch(hangs, MAX_SECONDS=0.6, TOTAL_SECONDS=1.0, RETRY_MIN_SECONDS=0.2)
assert r["status"] == "TIMEOUT" and len(seen) == 2 and took < 1.3, (r, seen, took)
seen.clear()
r, took = run_fetch(hangs, MAX_SECONDS=0.6, TOTAL_SECONDS=1.0, RETRY_MIN_SECONDS=0.5)
assert r["status"] == "TIMEOUT" and len(seen) == 1 and took < 0.9, (r, seen, took)  # too little left

print("security checks passed")
