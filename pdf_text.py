"""PDF text extraction for fetch_links, treating every PDF as hostile.

pypdf (pure Python, maintained, no native dependencies) parses in a child process
(`python -I pdf_text.py`) that sets its own limits before reading a byte: address space
PDF_MEMORY_MB, CPU PDF_SECONDS. The parent kills it after PDF_SECONDS of wall clock, or at
once if the fetch is cancelled (the audit's deadline), and lets one PDF parse at a time
process-wide (PARSE_LOCK), so a PDF bomb can only crash its own child, never the single web
worker (Railway: 1 GB). Waiting for the lock is cancellable too, so no PDF can hold an audit
past its deadline. Only the first PDF_MAX_PAGES pages are read.

Text comes back per page; lines are rejoined into paragraphs (pypdf hard-wraps them), and
page_starts[i] is the character offset where page i+1 begins, so a quote can show "p. 3"."""
import asyncio
import json
import os
import sys
import threading

PDF_MAX_BYTES = 15_000_000     # download cap for a PDF (HTML pages: 3 MB)
PDF_MAX_PAGES = 60
PDF_SECONDS = 20               # wall clock and CPU for one parse
PDF_MEMORY_MB = 512            # child address space (pypdf on a 12-page report: ~45 MB RSS)
PDF_MAX_CHARS = 600_000        # text kept from one PDF
MIN_PDF_CHARS = 200            # less than this = no extractable text (scanned)
PARSE_LOCK = threading.Lock()  # one parse at a time: memory caps don't add up past 1 GB
LOCK_POLL = 0.05               # seconds between tries for PARSE_LOCK (polling stays cancellable)
LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"}

LOCKED = "PDF is password-protected"
NO_TEXT = "PDF has no extractable text (likely scanned)"
TOO_SLOW = "PDF took too long to read"
TOO_BIG = f"PDF is larger than {PDF_MAX_BYTES // 1_000_000} MB"
BROKEN = "PDF could not be read (damaged or too complex)"


def tableish(line):
    """A table row ("Robusta 73,356 71,910 71,033 75,448 6.2%"): at least as many numbers as
    words. Rows are never joined to the next line."""
    toks = line.split()
    nums = sum(any(c.isdigit() for c in t) for t in toks)
    return nums >= 3 and nums >= len(toks) - nums


def reflow(text):
    """pypdf's hard-wrapped lines -> one line per paragraph. A line joins the next when it is
    a wrapped prose line (60+ chars, not a table row) and the next line is text, not a bullet
    or a blank (pypdf's paragraph break)."""
    out, cur = [], ""
    for raw in text.split("\n"):
        line = " ".join(raw.split())
        if not line:
            if cur:
                out.append(cur)
            cur = ""
            continue
        if cur and joinable(cur, line):
            cur = cur + " " + line
        else:
            if cur:
                out.append(cur)
            cur = line
    if cur:
        out.append(cur)
    return "\n".join(out)


def joinable(prev, line):
    last = prev[-200:]
    return (len(prev) >= 60 and not tableish(last) and not tableish(line)
            and not line.startswith(("•", "- ", "* ", "▪", "●")))


def child():
    """Runs in the child process: limits first, then parse stdin, print JSON to stdout."""
    import resource
    mem = int(os.environ.get("PDF_MEMORY_MB", PDF_MEMORY_MB)) * 1024 * 1024
    cpu = int(os.environ.get("PDF_SECONDS", PDF_SECONDS))
    resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    import io
    import logging
    logging.disable(logging.CRITICAL)        # pypdf warns on stderr about every odd object
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(sys.stdin.buffer.read()))
    if reader.is_encrypted:
        try:                                 # owner-password-only PDFs open with ""
            ok = reader.decrypt("")
        except Exception:
            ok = 0
        if not ok:
            print(json.dumps({"error": LOCKED}))
            return
    pages, total = [], 0
    for page in reader.pages[:PDF_MAX_PAGES]:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        for a, b in LIGATURES.items():
            t = t.replace(a, b)
        t = reflow(t)
        pages.append(t[:PDF_MAX_CHARS - total])
        total += len(pages[-1])
        if total >= PDF_MAX_CHARS:
            break
    title = ""
    try:
        title = str((reader.metadata or {}).get("/Title") or "")[:300]
    except Exception:
        pass
    print(json.dumps({"pages": pages, "count": len(reader.pages), "title": title}))


def extract(body, seconds=PDF_SECONDS, memory_mb=PDF_MEMORY_MB):
    """extract_async() for synchronous callers (tests, scripts)."""
    return asyncio.run(extract_async(body, seconds, memory_mb))


async def extract_async(body, seconds=PDF_SECONDS, memory_mb=PDF_MEMORY_MB):
    """{"text", "page_starts", "pages", "title"} or {"error": reason}. Never raises, except
    CancelledError: a cancelled parse kills its child and releases PARSE_LOCK first."""
    if not body.lstrip()[:1024].startswith(b"%PDF") and b"%PDF-" not in body[:1024]:
        return {"error": BROKEN}
    env = {"PATH": os.environ.get("PATH", ""), "PDF_MEMORY_MB": str(memory_mb), "PDF_SECONDS": str(max(1, int(seconds)))}
    # A threading lock (one per process, every audit and thread), polled: an asyncio task
    # blocked in acquire() could not be cancelled, and a thread left waiting for it would
    # take the lock after its audit had already given up.
    while not PARSE_LOCK.acquire(blocking=False):
        await asyncio.sleep(LOCK_POLL)
    proc = None
    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-I", os.path.abspath(__file__), env=env, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        except OSError:
            return {"error": BROKEN}
        try:
            async with asyncio.timeout(seconds):
                stdout, _ = await proc.communicate(body)
        except TimeoutError:
            return {"error": TOO_SLOW}
        returncode = proc.returncode
    finally:
        if proc is not None and proc.returncode is None:
            proc.kill()                       # timed out or cancelled: never left running
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except BaseException:
                pass
        PARSE_LOCK.release()
    if returncode != 0:
        # SIGXCPU (CPU limit) reads as too slow; MemoryError / anything else as broken
        return {"error": TOO_SLOW if returncode in (-24, 152) else BROKEN}
    try:
        got = json.loads(stdout)
    except ValueError:
        return {"error": BROKEN}
    if "error" in got:
        return got
    starts, text = [], ""
    for p in got["pages"]:
        starts.append(len(text))
        text += p.strip() + "\n\n"
    text = text.strip()
    if len(text) < MIN_PDF_CHARS:
        return {"error": NO_TEXT}
    return {"text": text, "page_starts": starts, "pages": got["count"], "title": got["title"]}


def page_number(offset, starts):
    """1-based page holding the character at offset."""
    n = 0
    for i, s in enumerate(starts):
        if s <= offset:
            n = i
    return n + 1


if __name__ == "__main__":
    child()
