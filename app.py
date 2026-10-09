"""Touchstone web app. Run locally: .venv/bin/uvicorn app:app"""
import hashlib
import hmac
import ipaddress
import json
import queue
import math
import os
import re
import threading
import time
import types
from datetime import datetime, timezone
from collections import defaultdict, deque
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from groq import Groq
from starlette.concurrency import run_in_threadpool

from check_numbers import segments
from pacing import TokenPacer
from touchstone import audit

MAX_REPORT_CHARS = 20_000
MAX_CLAIMS = 10               # ~1.5-2K Groq tokens per claim
MAX_BODY_BYTES = 200_000       # reject before parsing; 20K chars of UTF-8 + JSON fits easily
RATE_LIMIT, RATE_WINDOW = 5, 3600   # audits per IP per hour
FREE_LIMIT = 30                # per IP per hour: link-less reports (no fetch, no model call)
AUDIT_SECONDS = 300            # claims not started by then are marked NOT CHECKED
HEARTBEAT_SECONDS = 15         # idle stream -> {"type":"heartbeat"} (Cloudflare cuts idle at ~100 s)
# Behind a proxy (Railway), the socket peer is the proxy. CLIENT_IP_HEADER names the one header
# the proxy sets to the real visitor IP (Railway: X-Real-IP; Cloudflare: CF-Connecting-IP). Never the
# leftmost X-Forwarded-For entry: the client can set it, which would dodge the rate limit.
CLIENT_IP_HEADER = os.environ.get("CLIENT_IP_HEADER", "").strip()
# Public traffic goes through a Cloudflare Worker (Ooredoo can't reach Railway), so X-Real-IP is
# the Worker's egress IP. The Worker sends the visitor's IP in X-Touchstone-Client-IP plus a
# shared secret; that header is trusted only when the secret matches. Unset = header ignored.
PROXY_SECRET = os.environ.get("PROXY_SECRET", "").strip()
PRUNE_EVERY = 300              # seconds between sweeps of the rate-limit tables
# Daily cap across all visitors, matched to Groq's free budget (~200K tokens/day; a 10-claim
# audit is up to ~20K). New audits are refused up front once it's reached, rather than failing
# mid-audit when Groq runs out. Counts audits that call the model at all (CountingClient): an
# audit whose links are all unreachable costs nothing and must not use up the day for everyone.
DAILY_LIMIT = int(os.environ.get("GLOBAL_AUDITS_PER_DAY", "7"))
DAILY_FULL = "Touchstone's free daily capacity is used up, try again tomorrow."
MINUTE_FULL = "Touchstone is at its per-minute capacity right now. Try again in a minute."
HEARTBEAT = json.dumps({"type": "heartbeat"}) + "\n"
HERE = Path(__file__).parent

load_dotenv(HERE / ".env")
if not os.environ.get("GROQ_API_KEY"):
    raise SystemExit("GROQ_API_KEY missing from .env")
# max_retries=0: audit() does the retrying, so a per-minute 429 becomes a visible "waiting
# for capacity" pause (the SDK would sleep silently, then give up), and timeouts/5xx get the
# same 2 retries the SDK gave them.
client = Groq(api_key=os.environ["GROQ_API_KEY"], timeout=30, max_retries=0)
PACER = TokenPacer()           # Groq's tokens-per-minute window, shared by consecutive audits

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

# Cache-busting: index.html references each asset as /static/<name>?v=<content hash>, so a
# browser holding an old app.js gets the new one on the next page load. Versioned asset URLs
# never change content, so they're cached for a year; index.html and unversioned asset URLs
# are revalidated every time (no-cache).
ASSET_REF = re.compile(r'(\b(?:src|href)=")/static/([\w.\-]+)(")')


def asset_versions(static_dir):
    """{file name: first 12 hex chars of its SHA-256} for every file in static_dir."""
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:12]
            for p in sorted(static_dir.iterdir()) if p.is_file()}


def versioned_index(static_dir, versions):
    """index.html with each /static/<name> reference rewritten to /static/<name>?v=<hash>.
    Same-origin URLs, so script-src 'self' / style-src 'self' still cover them."""
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    return ASSET_REF.sub(lambda m: f"{m[1]}/static/{m[2]}?v={versions[m[2]]}{m[3]}"
                         if m[2] in versions else m[0], html)


ASSET_VERSIONS = asset_versions(HERE / "static")      # computed once at startup
INDEX_HTML = versioned_index(HERE / "static", ASSET_VERSIONS)

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


@app.middleware("http")
async def guard(request: Request, call_next):
    if int(request.headers.get("content-length") or 0) > MAX_BODY_BYTES:
        return JSONResponse({"error": "Request too large."}, status_code=413)
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    path, v = request.url.path, request.query_params.get("v")
    if (path.startswith("/static/") and response.status_code == 200 and v
            and v == ASSET_VERSIONS.get(path.removeprefix("/static/"))):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"   # hash in URL
    elif path == "/" or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"   # revalidate: users get updates at once
    return response


# One audit at a time: Groq's free tier (8K tokens/minute) can't serve two in parallel.
busy = threading.Lock()
hits = defaultdict(deque)      # ip -> start times of recent audits (in memory: 1 worker only)
free_hits = defaultdict(deque) # ip -> times of recent link-less requests
last_prune = time.time()


def valid_ip(value):
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None            # missing or malformed: fall back rather than trust junk


def from_worker(request):
    sent = request.headers.get("x-touchstone-proxy-secret", "")
    return bool(PROXY_SECRET) and hmac.compare_digest(sent.encode(), PROXY_SECRET.encode())


def client_ip(request):
    """The visitor's IP: the Worker's header if it proved the secret, else the trusted proxy
    header if configured and valid, else the socket."""
    if from_worker(request) and (ip := valid_ip(request.headers.get("x-touchstone-client-ip", ""))):
        return ip
    if CLIENT_IP_HEADER:
        if ip := valid_ip(request.headers.get(CLIENT_IP_HEADER, "")):
            return ip
    return request.client.host if request.client else "?"


def rate_key(ip):
    """What a limit counts: an IPv4 address, or an IPv6 /64 (one subscriber usually holds a
    whole /64, so per-address limits could be dodged by rotating addresses)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.version == 6 and addr.ipv4_mapped:
        return str(addr.ipv4_mapped)
    if addr.version == 6:
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


daily = {"day": None, "count": 0}   # UTC date -> audits that called the model


def utc_today():
    return datetime.now(timezone.utc).date()


def daily_used_up():
    if daily["day"] != utc_today():
        daily.update(day=utc_today(), count=0)
    return daily["count"] >= DAILY_LIMIT


def count_daily_audit():
    daily_used_up()            # roll over to a new UTC day first
    daily["count"] += 1


class CountingClient:
    """Wraps the Groq client for one audit: the audit counts toward the daily cap at its first
    model call ATTEMPT, before the request goes out. Counting reported tokens instead would
    fail open: a call that errors, times out, or returns no usage reports 0 tokens even
    though Groq may have spent them."""

    def __init__(self, inner):
        self.counted = False
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))
        self._inner = inner

    def _create(self, **kwargs):
        if not self.counted:
            self.counted = True
            count_daily_audit()
        return self._inner.chat.completions.create(**kwargs)


def prune(now):
    """Drop IPs with no hits inside the window, so the tables don't grow with every visitor."""
    global last_prune
    if now - last_prune < PRUNE_EVERY:
        return
    last_prune = now
    for table in (hits, free_hits):
        for ip in list(table):
            q = table[ip]
            while q and now - q[0] > RATE_WINDOW:
                q.popleft()
            if not q:
                del table[ip]


def rate_limited(ip, table=hits, limit=RATE_LIMIT):
    now = time.time()
    prune(now)
    q = table[ip]
    while q and now - q[0] > RATE_WINDOW:
        q.popleft()
    if len(q) >= limit:
        return math.ceil((RATE_WINDOW - (now - q[0])) / 60)   # minutes to wait
    q.append(now)
    return 0


@app.get("/healthz")
def healthz():
    return {"ok": True}       # platform health check: no fetch, no model call


@app.get("/")
def index():
    return HTMLResponse(INDEX_HTML)


@app.get("/api/example")
def example():
    return PlainTextResponse((HERE / "report2.txt").read_text(encoding="utf-8"))


async def read_report(request):
    """Read the body with a hard cap: the Content-Length check in guard() can be skipped
    with chunked encoding, so the bytes are counted as they arrive."""
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            return None
    try:
        report = json.loads(body).get("report")
    except (ValueError, AttributeError):
        return ""
    return report if isinstance(report, str) else ""


@app.post("/api/audit")
async def run_audit(request: Request):
    report = await read_report(request)
    if report is None:
        return JSONResponse({"error": "Request too large."}, status_code=413)
    if not report.strip():
        return JSONResponse({"error": "The report is empty."}, status_code=400)
    if len(report) > MAX_REPORT_CHARS:
        return JSONResponse({"error": f"Reports are limited to {MAX_REPORT_CHARS:,} characters "
                                      f"(this one has {len(report):,})."}, status_code=413)
    ip = rate_key(client_ip(request))
    segs = await run_in_threadpool(segments, report)   # keep parsing off the event loop
    if not any(url for _, url in segs):
        # Nothing to fetch or check: answer at once, outside the 5-audit limit but under a
        # cheaper one of its own.
        if wait := rate_limited(ip, free_hits, FREE_LIMIT):
            return JSONResponse({"error": f"Too many requests. Try again in {wait} minute"
                                          f"{'s' if wait > 1 else ''}."}, status_code=429)
        events = audit(report, client)
        return StreamingResponse((json.dumps(ev, ensure_ascii=False) + "\n" for ev in events),
                                 media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store"})
    if not busy.acquire(blocking=False):
        return JSONResponse({"error": "Another audit is running. Try again in a minute."},
                            status_code=503)
    if daily_used_up():        # checked under the busy lock: no audit can start in between
        busy.release()
        return JSONResponse({"error": DAILY_FULL}, status_code=429)
    wait = rate_limited(ip)
    if wait:
        busy.release()
        return JSONResponse({"error": f"Limit of {RATE_LIMIT} audits per hour reached. "
                                      f"Try again in {wait} minute{'s' if wait > 1 else ''}."}, status_code=429)

    out, stop, started = queue.Queue(), threading.Event(), threading.Event()

    def work():
        """Runs the audit in its own thread, so the stream can send heartbeats while a model
        call or fetch is slow. Owns the busy lock: releases it when the audit really ends (not
        when the client leaves mid-claim), or at once if the stream never starts. Stops after
        the current claim if the client goes away."""
        try:
            if not started.wait(30):
                return
            deadline = time.monotonic() + AUDIT_SECONDS
            events = audit(report, CountingClient(client), max_claims=MAX_CLAIMS, deadline=deadline,
                           pacer=PACER)
            for ev in events:
                if stop.is_set():
                    events.close()
                    return
                if ev["type"] == "quota":
                    if ev["scope"] == "day":    # Groq's daily budget is gone: refuse new audits up front
                        daily_used_up()
                        daily["count"] = max(daily["count"], DAILY_LIMIT)
                    ev["message"] = DAILY_FULL if ev["scope"] == "day" else MINUTE_FULL
                out.put(json.dumps(ev, ensure_ascii=False) + "\n")
        except Exception as e:
            out.put(json.dumps({"type": "error", "error": f"Audit failed ({type(e).__name__})."}) + "\n")
        finally:
            busy.release()
            out.put(None)

    def stream():
        started.set()
        try:
            while True:
                try:
                    line = out.get(timeout=HEARTBEAT_SECONDS)
                except queue.Empty:
                    yield HEARTBEAT
                    continue
                if line is None:
                    return
                yield line
        finally:
            stop.set()

    threading.Thread(target=work, daemon=True).start()
    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
