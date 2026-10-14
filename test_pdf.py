"""PDF checks (no tokens). Run: .venv/bin/python test_pdf.py
The real ICO report is downloaded once into testdata/ (gitignored: a copy of another site's
file); every other PDF here is generated."""
import asyncio
import io
import ipaddress
import os
import time

import httpx
from pypdf import PdfReader, PdfWriter

import fetch_links as F
import pdf_text as P
from touchstone import add_pages, unreachable

ICO_URL = "https://www.ico.org/documents/cy2025-26/cmr-0226-e.pdf"
ICO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "testdata", "cmr-0226-e.pdf")


def text_pdf(pages):
    """A minimal valid PDF with one line of Helvetica text per page."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        lines = [text[i:i + 90] for i in range(0, len(text), 90)]
        ops = "".join(f"({l.replace('(', '').replace(')', '')}) Tj 0 -14 Td " for l in lines)
        stream = f"BT /F1 10 Tf 40 760 Td {ops}ET"
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {len(objs)} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def rewrite(pdf, **encrypt):
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    if encrypt:
        w.encrypt(algorithm="RC4-128", **encrypt)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


PROSE = ("The ICO Composite Indicator Price averaged 267.57 US cents/lb in February 2026, a 9.9% "
         "decrease from January 2026, as supply expectations improved across the main producers. ")
SAMPLE = text_pdf([PROSE * 3, "Second page. Exports reached 10.85 million bags in January 2026. " * 4])

# 1. A generated text PDF: text per page, page offsets, page numbers for quotes.
got = P.extract(SAMPLE)
assert "error" not in got, got
assert got["pages"] == 2 and len(got["page_starts"]) == 2 and "267.57" in got["text"], got
assert P.page_number(got["text"].index("10.85"), got["page_starts"]) == 2
assert P.page_number(0, got["page_starts"]) == 1

# 2. Encrypted with a password -> unreachable "PDF is password-protected"; an owner-password-
#    only PDF (empty user password, common for "no copying" flags) still opens.
assert P.extract(rewrite(SAMPLE, user_password="secret", owner_password="x")) == {"error": P.LOCKED}
assert "267.57" in P.extract(rewrite(SAMPLE, user_password="", owner_password="x"))["text"]

# 3. No text layer (scanned) -> "PDF has no extractable text (likely scanned)".
w = PdfWriter()
for _ in range(3):
    w.add_blank_page(612, 792)
blank = io.BytesIO()
w.write(blank)
assert P.extract(blank.getvalue()) == {"error": P.NO_TEXT}

# 4. Hostile input never takes the worker down: garbage, a hard time limit, a memory limit.
assert P.extract(b"<html>not a pdf</html>") == {"error": P.BROKEN}
assert P.extract(b"%PDF-1.7\n" + os.urandom(5000)) in ({"error": P.BROKEN}, {"error": P.NO_TEXT})
t0 = time.time()
assert P.extract(SAMPLE, seconds=0.05) == {"error": P.TOO_SLOW}          # killed, not waited for
assert time.time() - t0 < 2
assert P.extract(SAMPLE, memory_mb=30) == {"error": P.BROKEN}           # child dies, parent fine
assert "267.57" in P.extract(SAMPLE)["text"]                            # and the next one works

# 5. Page cap: only the first PDF_MAX_PAGES pages are read.
many = P.extract(text_pdf([f"Page {i} says the count was {1000 + i} bags this month, a new figure. " * 4
                           for i in range(P.PDF_MAX_PAGES + 5)]))
assert len(many["page_starts"]) == P.PDF_MAX_PAGES and many["pages"] == P.PDF_MAX_PAGES + 5
assert "1059" in many["text"] and "1060" not in many["text"]


# 6. Through the real fetch path (mocked transport, no network).
def fetch_fixture(body, headers, url="https://example.org/report.pdf", stream=False):
    async def ok(u): return True, "", ipaddress.ip_address("93.184.215.14")
    real = (F.check_url, F.peer_ok, httpx.AsyncClient)

    def respond(req):
        if stream:     # no Content-Length: the cap must hold while reading
            async def chunks():
                for i in range(0, len(body), 65536):
                    yield body[i:i + 65536]
            return httpx.Response(200, headers=headers, content=chunks())
        return httpx.Response(200, headers=headers, content=body)
    F.check_url, F.peer_ok = ok, lambda r: True
    F.httpx.AsyncClient = lambda **k: real[2](transport=httpx.MockTransport(respond), **k)
    try:
        return F.fetch(url)
    finally:
        F.check_url, F.peer_ok, F.httpx.AsyncClient = real


r = fetch_fixture(SAMPLE, {"content-type": "application/pdf"})
assert r["status"] == "OK" and r["pdf"] and r["page_starts"] == got["page_starts"] and "267.57" in r["text"], r
assert r["detail"].startswith("PDF, 2 pages")
assert fetch_fixture(SAMPLE, {"content-type": "application/octet-stream"})["status"] == "OK"   # .pdf URL
locked = fetch_fixture(rewrite(SAMPLE, user_password="s", owner_password="x"), {"content-type": "application/pdf"})
assert (locked["status"], locked["detail"]) == ("PDF_ERROR", P.LOCKED)
u = unreachable(locked, locked["url"])
assert u["label"] == "SOURCE UNREACHABLE" and u["reason"] == "PDF is password-protected." and u["detail"] == "PDF_ERROR " + P.LOCKED

# Size cap: refused from Content-Length, and while streaming without one.
big = b"%PDF-1.4\n" + b"0" * (P.PDF_MAX_BYTES + 10)
assert fetch_fixture(big, {"content-type": "application/pdf"}) == {
    "url": "https://example.org/report.pdf", "status": "PDF_ERROR", "detail": P.TOO_BIG}
assert fetch_fixture(big, {"content-type": "application/pdf"}, stream=True)["detail"] == P.TOO_BIG
assert unreachable({"status": "PDF_ERROR", "detail": P.TOO_BIG}, "u")["reason"] == "PDF is larger than 15 MB."

# Time limit through fetch: a slow parse is reported, the fetch returns.
real_seconds = P.PDF_SECONDS
P.extract_async.__defaults__ = (0.05, P.PDF_MEMORY_MB)
try:
    slow = fetch_fixture(SAMPLE, {"content-type": "application/pdf"})
finally:
    P.extract_async.__defaults__ = (real_seconds, P.PDF_MEMORY_MB)
assert (slow["status"], slow["detail"]) == ("PDF_ERROR", P.TOO_SLOW), slow

# 7. Quotes from a PDF get their page number.
page = {"text": got["text"], "page_starts": got["page_starts"]}
res = {"facts": [{"fact": "x", "status": "stated", "quote": "Exports reached 10.85 million bags in January 2026."},
                 {"fact": "y", "status": "possible", "evidence": got["text"].split("\n")[0]},
                 {"fact": "z", "status": "missing", "quote": ""}]}
add_pages(res, page)
assert [f.get("page") for f in res["facts"]] == [2, 1, None], res

# 8. The real ICO February 2026 report (downloaded once into testdata/, gitignored).
if not os.path.exists(ICO_FILE) and os.environ.get("TOUCHSTONE_OFFLINE") == "1":
    print("(offline: skipped the real ICO PDF)")
elif not os.path.exists(ICO_FILE):
    try:
        os.makedirs(os.path.dirname(ICO_FILE), exist_ok=True)
        data = httpx.get(ICO_URL, timeout=30, headers=F.HEADERS).content
        if data.startswith(b"%PDF"):
            open(ICO_FILE, "wb").write(data)
    except httpx.HTTPError as e:
        print(f"(skipped the real ICO PDF: {type(e).__name__})")
if os.path.exists(ICO_FILE):
    ico = P.extract(open(ICO_FILE, "rb").read())
    assert ico["pages"] == 12 and len(ico["page_starts"]) == 12, ico.get("error")
    text = ico["text"]
    # Paragraphs rejoined: the sentence the report cites sits on one line, on page 1.
    line = next(l for l in text.split("\n") if l.startswith("The ICO Composite Indicator Price (I-CIP) averaged 267.57"))
    assert "a 9.9% decrease from January 2026." in line
    assert P.page_number(text.index(line), ico["page_starts"]) == 1
    # Table rows stay one per line.
    assert any(l.startswith("Robusta 73,356 71,910") for l in text.split("\n"))
    assert P.page_number(text.index("Table 3: World Supply/Demand Balance"), ico["page_starts"]) == 11
    assert "308.62" in text and "179.73" in text and "330.89" in text     # report5's Arabica/Robusta claim
    assert "ﬁ" not in text                                           # ligatures unfolded

# 8. Audit deadline: a PDF parse still running is killed when its fetch is cancelled, and
#    PARSE_LOCK (one parse at a time, process-wide) is released; waiting for the lock is
#    cancellable too, so another audit's slow PDF can't hold this one past its deadline.
import sys
real_spawn, children = asyncio.create_subprocess_exec, []
async def hanging_child(*a, **k):
    proc = await real_spawn(sys.executable, "-c", "import time; time.sleep(60)", **k)
    children.append(proc)
    return proc
asyncio.create_subprocess_exec = hanging_child
try:
    async def cancel_mid_parse():
        task = asyncio.create_task(P.extract_async(SAMPLE))
        await asyncio.sleep(0.5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return True
    t0 = time.monotonic()
    assert asyncio.run(cancel_mid_parse()) and time.monotonic() - t0 < 3
    assert children[0].returncode is not None, "child left running"          # killed
    assert P.PARSE_LOCK.acquire(blocking=False); P.PARSE_LOCK.release()       # lock released
    # Through fetch_many's deadline: the PDF comes back LATE, not after its 20 s parse.
    real = (F.check_url, F.peer_ok, httpx.AsyncClient)
    async def ok(u): return True, "", ipaddress.ip_address("93.184.215.14")
    F.check_url, F.peer_ok = ok, lambda r: True
    F.httpx.AsyncClient = lambda **k: real[2](transport=httpx.MockTransport(
        lambda req: httpx.Response(200, headers={"content-type": "application/pdf"}, content=SAMPLE)), **k)
    try:
        t0 = time.monotonic()
        late = F.fetch_many(["https://example.org/report.pdf"], within=0.8)[0]
        took = time.monotonic() - t0
    finally:
        F.check_url, F.peer_ok, F.httpx.AsyncClient = real
    assert late["status"] == F.LATE and took < 2.5, (late, took)
    assert all(c.returncode is not None for c in children) and len(children) == 2
finally:
    asyncio.create_subprocess_exec = real_spawn
assert P.PARSE_LOCK.acquire(blocking=False)                    # another parse holds the lock...
try:
    async def wait_for_lock():
        try:
            await asyncio.wait_for(P.extract_async(SAMPLE), 0.3)
        except TimeoutError:
            return True
    assert asyncio.run(wait_for_lock())                        # ...this one gives up on time
finally:
    P.PARSE_LOCK.release()
assert "267.57" in P.extract(SAMPLE)["text"]                   # and nothing was left holding it

print("pdf checks passed")
