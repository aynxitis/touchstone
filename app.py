"""Touchstone web app. Run locally: .venv/bin/uvicorn app:app"""
import json
import math
import os
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from groq import Groq
from starlette.background import BackgroundTask

from check_numbers import segments
from touchstone import audit

MAX_REPORT_CHARS = 20_000
MAX_CLAIMS = 15
MAX_BODY_BYTES = 200_000       # reject before parsing; 20K chars of UTF-8 + JSON fits easily
RATE_LIMIT, RATE_WINDOW = 5, 3600   # audits per IP per hour
AUDIT_SECONDS = 300            # claims not started by then are marked NOT CHECKED
HERE = Path(__file__).parent

load_dotenv(HERE / ".env")
if not os.environ.get("GROQ_API_KEY"):
    raise SystemExit("GROQ_API_KEY missing from .env")
client = Groq(api_key=os.environ["GROQ_API_KEY"], timeout=30, max_retries=2)

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

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
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"   # revalidate: users get updates at once
    return response


# One audit at a time: Groq's free tier (8K tokens/minute) can't serve two in parallel.
busy = threading.Lock()
hits = defaultdict(deque)      # ip -> start times of recent audits (in memory, local only)


def rate_limited(ip):
    now, q = time.time(), hits[ip]
    while q and now - q[0] > RATE_WINDOW:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        return math.ceil((RATE_WINDOW - (now - q[0])) / 60)   # minutes to wait
    q.append(now)
    return 0


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


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
    if not any(url for _, url in segments(report)):
        # Nothing to fetch or check: answer at once, without using up the rate limit.
        events = audit(report, client)
        return StreamingResponse((json.dumps(ev, ensure_ascii=False) + "\n" for ev in events),
                                 media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store"})
    if not busy.acquire(blocking=False):
        return JSONResponse({"error": "Another audit is running. Try again in a minute."},
                            status_code=503)
    wait = rate_limited(request.client.host if request.client else "?")
    if wait:
        busy.release()
        return JSONResponse({"error": f"Limit of {RATE_LIMIT} audits per hour reached. "
                                      f"Try again in {wait} minute{'s' if wait > 1 else ''}."}, status_code=429)

    once = threading.Lock()

    def release():             # runs when the stream ends, including client disconnects
        if once.acquire(blocking=False):
            busy.release()

    def stream():
        try:
            deadline = time.monotonic() + AUDIT_SECONDS
            for ev in audit(report, client, max_claims=MAX_CLAIMS, deadline=deadline):
                if ev["type"] != "skipped":
                    yield json.dumps(ev, ensure_ascii=False) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "error": f"Audit failed ({type(e).__name__})."}) + "\n"
        finally:
            release()

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
                             background=BackgroundTask(release))
