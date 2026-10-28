"""Touchstone web app. Run locally: .venv/bin/uvicorn app:app"""
import hashlib
import hmac
import ipaddress
import json
import logging
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
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse, PlainTextResponse,
                               StreamingResponse)
from fastapi.exception_handlers import http_exception_handler
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from check_numbers import segments
from pacing import TokenPacer
from providers import make_client, make_provider, provider_name
from touchstone import audit

MAX_REPORT_CHARS = 20_000
MAX_BODY_BYTES = 200_000       # reject before parsing; 20K chars of UTF-8 + JSON fits easily
RATE_LIMIT, RATE_WINDOW = 5, 3600   # audits per IP per hour
FREE_LIMIT = 30                # per IP per hour: link-less reports (no fetch, no model call)
AUDIT_SECONDS = 300            # hard wall clock per audit: fetches, PDF parsing, model calls
HEARTBEAT_SECONDS = 15         # idle stream -> {"type":"heartbeat"} (Cloudflare cuts idle at ~100 s)
# Behind a proxy (Railway), the socket peer is the proxy. CLIENT_IP_HEADER names the one header
# the proxy sets to the real visitor IP (Railway: X-Real-IP; Cloudflare: CF-Connecting-IP). Never the
# leftmost X-Forwarded-For entry: the client can set it, which would dodge the rate limit.
PRUNE_EVERY = 300              # seconds between sweeps of the rate-limit tables
# Daily cap across all visitors, matched to Groq's free budget (~200K tokens/day; a 10-claim
# audit is up to ~20K). New audits are refused up front once it's reached, rather than failing
# mid-audit when Groq runs out. Counts audits that call the model at all (CountingClient): an
# audit whose links are all unreachable costs nothing and must not use up the day for everyone.
HERE = Path(__file__).parent
load_dotenv(HERE / ".env")
CLIENT_IP_HEADER = os.environ.get("CLIENT_IP_HEADER", "").strip()   # after .env (local runs)
# Public traffic goes through a Cloudflare Worker (Ooredoo can't reach Railway), so X-Real-IP is
# the Worker's egress IP. The Worker sends the visitor's IP in X-Touchstone-Client-IP plus a
# shared secret; that header is trusted only when the secret matches. Unset = header ignored.
PROXY_SECRET = os.environ.get("PROXY_SECRET", "").strip()
# Refusing every request without the Worker's secret is opt-in (2026-10-11 incident: enforced
# on deploy, it answered 403 to the whole site while /healthz kept the deploy "healthy").
# Turn it on only after /healthz/proxy shows via_worker true through the Worker (DEPLOY.md).
REQUIRE_PROXY_SECRET = os.environ.get("REQUIRE_PROXY_SECRET", "").strip() == "1"
if REQUIRE_PROXY_SECRET and not PROXY_SECRET:
    # Enforcing with no secret would refuse everyone: fail the deploy instead (the platform
    # keeps the previous one running).
    raise SystemExit("REQUIRE_PROXY_SECRET=1 needs PROXY_SECRET")
UNGUARDED = {"/healthz", "/healthz/proxy"}       # platform health checks, never refused
log = logging.getLogger("touchstone")
if not log.handlers:                             # uvicorn configures only its own loggers
    _h = logging.StreamHandler()                 # stderr: Railway's deploy log
    _h.setFormatter(logging.Formatter("touchstone %(levelname)s %(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)
# PROVIDER=groq (default) | gemini: see providers.py. Each has its own daily audit cap:
# Groq GLOBAL_AUDITS_PER_DAY (7: ~20K tokens per audit vs 200K tokens/day); Gemini
# GEMINI_AUDITS_PER_DAY (40: an audit sends one request per cited page and 10 claims, at most
# 8 pages: usually <= 8 requests, 40 x 8 = 320 of the pacer's 450/day. Worst case, 25 claims x
# 3 sources piled on 3 pages, 14 requests: 40 x 14 = 560, so the pacer's RPD stop (450, under
# Google's 500) is what holds the day then, not this cap).
PROVIDER = provider_name()
DAILY_LIMIT = int(os.environ.get("GLOBAL_AUDITS_PER_DAY" if PROVIDER == "groq" else "GEMINI_AUDITS_PER_DAY",
                                 "7" if PROVIDER == "groq" else "40"))
# Per-audit caps. Groq: 10 claims (~1.5-2K tokens each, one call per claim and source).
# Gemini: cost scales with distinct source URLs (one call per page, up to 10 claims per call),
# so 25 claims but at most 8 URLs, counted in report order.
CAPS = {"groq": (10, None), "gemini": (25, 8)}   # provider -> (claims, distinct URLs) per audit
MAX_CLAIMS, MAX_URLS = CAPS[PROVIDER]
DAILY_FULL = "Touchstone's free daily capacity is used up, try again tomorrow."
MINUTE_FULL = "Touchstone is at its per-minute capacity right now. Try again in a minute."
BUSY_MSG = ("Another check is running (it can take up to 5 minutes). "
            "Your check will start automatically when it's free.")
HEARTBEAT = json.dumps({"type": "heartbeat"}) + "\n"

# Groq: max_retries=0, audit() does the retrying, so a per-minute 429 becomes a visible
# "waiting for capacity" pause and timeouts/5xx get 2 retries. Keys come from the
# environment only and are never logged. The Groq client is built at its first call.
client = make_client(PROVIDER)
PACER = TokenPacer.for_provider(PROVIDER)   # the provider's minute/day, shared by audits
def limits_line(max_claims, max_urls):
    """The page's statement of the per-check limits, for the active provider."""
    if max_urls is None:
        what = f"Up to {max_claims} cited claims per check (the first {max_claims}, in report order)."
    else:
        what = (f"Up to {max_claims} cited claims and {max_urls} distinct source links per check "
                "(the first ones, in report order).")
    return f'<p class="meta">{what} {RATE_LIMIT} checks per hour.</p>'


PROVIDER_NOTE = {"gemini": '<p class="notice">Reports are processed by Google Gemini (free tier), which may use '
                           "inputs to improve Google's products. Don't paste anything private.</p>"}

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

# The landing page lives at "/" (landing/index.html); the app itself is /app. The landing page
# keeps its old flat layout (landing.css, tokens.css, landing.js, favicon.svg at the root,
# fonts/ and vendor/ beside them), so its subfolders are mounted here and its root files are
# served by landing_asset() below: no engine, no build step, and its relative URLs just work.
LANDING = HERE / "landing"
app.mount("/fonts", StaticFiles(directory=LANDING / "fonts"), name="landing-fonts")
app.mount("/vendor", StaticFiles(directory=LANDING / "vendor"), name="landing-vendor")

# Cache-busting: index.html references each asset as /static/<name>?v=<content hash>, so a
# browser holding an old app.js gets the new one on the next page load. Versioned asset URLs
# never change content, so they're cached for a year; index.html and unversioned asset URLs
# are revalidated every time (no-cache).
ASSET_REF = re.compile(r'(\b(?:src|href)=")/static/([\w.\-]+)(")')


def asset_versions(static_dir):
    """{file name: first 12 hex chars of its SHA-256} for every file in static_dir."""
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:12]
            for p in sorted(static_dir.iterdir()) if p.is_file()}


def versioned_index(static_dir, versions, provider="groq"):
    """index.html with each /static/<name> reference rewritten to /static/<name>?v=<hash>.
    Same-origin URLs, so script-src 'self' / style-src 'self' still cover them. The
    <!--provider-note--> marker becomes the provider's data-use line (Gemini), or nothing;
    <!--limits--> the provider's per-audit limits."""
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    html = html.replace("<!--provider-note-->", PROVIDER_NOTE.get(provider, ""))
    html = html.replace("<!--limits-->", limits_line(*CAPS[provider]))
    return ASSET_REF.sub(lambda m: f"{m[1]}/static/{m[2]}?v={versions[m[2]]}{m[3]}"
                         if m[2] in versions else m[0], html)


# Live, not frozen at startup. uvicorn --reload only restarts on Python changes, so a
# stylesheet edited while the server runs used to keep the startup hash: index.html stamped
# the old ?v=, and the browser's year-long immutable copy of that URL won out over every
# reload. Rehashing on a stat() change means a CSS edit shows up on the next page load.
ASSET_VERSIONS = {}
_index_state = {"sig": None, "html": ""}


def static_versions():
    """Current {file: hash}, rehashed only when a static file's name/mtime/size changes."""
    files = [p for p in sorted((HERE / "static").iterdir()) if p.is_file()]
    sig = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in files)
    if sig != _index_state["sig"]:
        ASSET_VERSIONS.clear()
        ASSET_VERSIONS.update({p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:12]
                               for p in files})
        _index_state["html"] = versioned_index(HERE / "static", ASSET_VERSIONS, PROVIDER)
        _index_state["sig"] = sig
    return ASSET_VERSIONS


def current_index():
    static_versions()
    return _index_state["html"]


static_versions()

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
SECURITY_HEADERS = {"Content-Security-Policy": CSP,
                    "X-Content-Type-Options": "nosniff",
                    "Referrer-Policy": "no-referrer"}


@app.middleware("http")
async def guard(request: Request, call_next):
    if REQUIRE_PROXY_SECRET and request.url.path not in UNGUARDED:
        # The origin answers only the Worker (and the health checks): direct requests to the
        # railway.app URL get nothing, not even the page. Every refusal is logged with its
        # reason and path, never a header value.
        if problem := proxy_problem(request):
            log.warning("proxy check refused %s %s: %s", request.method, request.url.path[:200], problem)
            return JSONResponse({"error": "Forbidden."}, status_code=403)
    if int(request.headers.get("content-length") or 0) > MAX_BODY_BYTES:
        return JSONResponse({"error": "Request too large."}, status_code=413)
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    path, v = request.url.path, request.query_params.get("v")
    if (path.startswith("/static/") and response.status_code == 200 and v
            and v == static_versions().get(path.removeprefix("/static/"))):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"   # hash in URL
    elif (path == "/" or path == "/app" or path.startswith("/static/")
          or path.startswith("/fonts/") or path.startswith("/vendor/")
          or path.lstrip("/") in LANDING_ROOT_FILES):
        response.headers["Cache-Control"] = "no-cache"   # revalidate: users get updates at once
    elif path == "/mcp":
        response.headers["Cache-Control"] = "no-store, no-transform"   # no cached results, no buffered stream
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


def proxy_problem(request):
    """Why a request doesn't prove it came through the Worker, or None if it does:
    "missing header", "mismatch" or "malformed client IP" (secret right, IP header not an IP)."""
    if not request.headers.get("x-touchstone-proxy-secret"):
        return "missing header"
    if not from_worker(request):
        return "mismatch"
    if not valid_ip(request.headers.get("x-touchstone-client-ip", "")):
        return "malformed client IP"
    return None


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
    """Wraps the provider's client for one audit: the audit counts toward the daily cap at its
    first model call ATTEMPT, before the request goes out. Counting reported tokens instead
    would fail open: a call that errors, times out, or returns no usage reports 0 tokens even
    though the provider may have spent them. Groq: chat.completions.create; Gemini:
    models.generate_content."""

    def __init__(self, inner, count=None):
        self.counted = False
        self.count = count     # None: the website's daily cap; MCP passes its own counter
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(
            create=lambda **k: self._call(lambda: inner.chat.completions.create(**k))))
        self.models = types.SimpleNamespace(
            generate_content=lambda **k: self._call(lambda: inner.models.generate_content(**k)))

    def _call(self, send):
        if not self.counted:
            self.counted = True
            (self.count or count_daily_audit)()
        return send()


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


@app.get("/healthz/proxy")
def healthz_proxy(request: Request):
    """Whether this request carried the Worker's valid secret: check it through the Worker
    before setting REQUIRE_PROXY_SECRET=1. Reveals nothing else to the caller; when false, the
    reason ("missing header" / "mismatch") goes to the server log only."""
    ok = from_worker(request)
    if not ok:
        log.info("healthz/proxy: via_worker false (%s)",
                 "PROXY_SECRET unset on the server" if not PROXY_SECRET else proxy_problem(request))
    return {"via_worker": ok}


@app.get("/")
def landing():
    """The public landing page (landing/), read per request so editing it needs no restart.
    Its own CSS, JS, fonts and vendored motion engine are mounted beside it below; the app
    itself is /app."""
    return HTMLResponse((LANDING / "index.html").read_text(encoding="utf-8"))


@app.get("/app")
def index():
    return HTMLResponse(current_index())


# The landing page's root-level files, served from landing/ as-is (it keeps its flat layout:
# landing.css, tokens.css, landing.js, favicon.svg at the root, fonts/ and vendor/ mounted above).
# Listed explicitly rather than mounted at "/", so the app's own routes keep their behaviour
# (e.g. GET /mcp stays 405 with Allow: POST) and nothing else in landing/ becomes public.
LANDING_ROOT_FILES = ("landing.css", "tokens.css", "error.css", "error.js", "landing.js", "favicon.svg",
                      "logo.svg", "logo-app.svg",
                      "privacy.html", "terms.html")


def _landing_file(name):
    def serve():
        return FileResponse(LANDING / name)
    serve.__doc__ = f"landing/{name}"
    return serve


for _name in LANDING_ROOT_FILES:
    app.add_api_route(f"/{_name}", _landing_file(_name), include_in_schema=False,
                      name=f"landing-{_name}")


# A dead end should still look like the product: one giant number, one sentence that says
# what happened in plain words. The page lives in landing/error.html and is read per
# request (like the landing page), with the <!--marker--> runs filled in below. Its CSS is
# landing/error.css, served by LANDING_ROOT_FILES just above; there is no inline style or
# script, so it renders under the app's own CSP and over the landing's own tokens/fonts.
ERROR_COPY = {
    404: ("This page doesn’t exist.",
          "The link may be old, or the page may have moved."),
    405: ("That isn’t allowed here.",
          "This address only answers a different kind of request."),
    500: ("Something broke on our side.",
          "The page didn’t load. Try again in a minute."),
}
ERROR_MARKERS = re.compile(r"<!--(code|title|line)-->(.*?)<!--/\1-->", re.S)


def error_page(code, status=None):
    """landing/error.html with the number and the plain-language copy filled in."""
    title, line = ERROR_COPY.get(code, ERROR_COPY[404])
    text = (LANDING / "error.html").read_text(encoding="utf-8")
    values = {"code": str(code), "title": title, "line": line}
    # The 500 path never reaches guard() (ServerErrorMiddleware is outermost), so the page
    # carries the security headers itself; on a 404 the middleware rewrites the same values.
    return HTMLResponse(ERROR_MARKERS.sub(lambda m: values[m[1]], text),
                        status_code=code if status is None else status,
                        headers={**SECURITY_HEADERS, "Cache-Control": "no-cache"})


@app.get("/error")
def error_preview(code: int = 404):
    """The error page itself, for checking it without breaking a link first: a 200 page."""
    return error_page(code if code in ERROR_COPY else 404, status=200)


# Pages a person can land on get the page; the machine surfaces (the audit API, MCP, the
# health checks, and static assets) keep the JSON/status/headers their clients rely on.
# GET /mcp must stay 405 with Allow: POST, so 405 and everything else fall through to
# Starlette's own handler untouched.
MACHINE_PREFIXES = ("/api/", "/mcp", "/healthz", "/static/", "/fonts/", "/vendor/")


@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    path = request.url.path
    if exc.status_code in ERROR_COPY and not path.startswith(MACHINE_PREFIXES):
        response = error_page(exc.status_code)
        for name, value in (exc.headers or {}).items():
            response.headers.setdefault(name, value)     # a 405 keeps its Allow: header
        return response
    return await http_exception_handler(request, exc)


@app.exception_handler(Exception)
async def server_error(request, exc):
    log.error("unhandled error on %s %s", request.method, request.url.path[:200], exc_info=exc)
    return error_page(500)


@app.get("/api/example")
def example():
    return PlainTextResponse((HERE / "examples" / "demo.txt").read_text(encoding="utf-8"))


def example_run(path=HERE / "examples" / "demo_run.json"):
    """The saved run of demo.txt (a "touchstone-run" v1 file from the Download button), or
    None if it is missing or not that format. Read per request: committing a new one needs
    no code change."""
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ok = (isinstance(run, dict) and run.get("format") == "touchstone-run" and run.get("version") == 1
          and isinstance(run.get("report"), str) and isinstance(run.get("claims"), list))
    return run if ok else None


@app.get("/api/example-run")
def example_replay():
    """Replayed by the page itself: no audit, no model call, no rate limit."""
    run = example_run()
    if run is None:
        return JSONResponse({"error": "No saved example run."}, status_code=404)
    return JSONResponse(run, headers={"Cache-Control": "no-cache"})


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
        # "busy": the page retries every 15 s on its own; rate_limited() hasn't run yet, so
        # these retries never count toward the per-hour limit.
        return JSONResponse({"error": BUSY_MSG, "busy": True}, status_code=503)
    if daily_used_up():        # checked under the busy lock: no audit can start in between
        busy.release()
        return JSONResponse({"error": DAILY_FULL}, status_code=429)
    wait = rate_limited(ip)
    if wait:
        busy.release()
        return JSONResponse({"error": f"Limit of {RATE_LIMIT} checks per hour reached. "
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
            counted = CountingClient(client)
            events = audit(report, counted, max_claims=MAX_CLAIMS, max_urls=MAX_URLS, deadline=deadline,
                           pacer=PACER, provider=make_provider(PROVIDER, counted))
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
            out.put(json.dumps({"type": "error", "error": f"Check failed ({type(e).__name__})."}) + "\n")
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


# Remote MCP server (mcp_server.py): POST /mcp, only with MCP_ENABLED=1. Read before importing
# mcp, so MCP_ENABLED=0 never loads it; a failed import or build only logs: the website starts
# either way.
MCP_ENABLED = os.environ.get("MCP_ENABLED", "").strip() == "1"
if MCP_ENABLED:
    try:
        import mcp_server
        mcp_routes, mcp_lifespan = mcp_server.build(mcp_server.Shared(
            busy=busy, pacer=PACER, client=client, provider=PROVIDER, counting=CountingClient))
        app.router.routes.extend(mcp_routes)         # POST /mcp; /mcp/ -> 404, never a redirect
        app.router.lifespan_context = mcp_lifespan   # a fresh session manager per start
    except Exception as e:
        log.error("MCP disabled: %s", type(e).__name__)
