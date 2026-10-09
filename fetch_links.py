"""Touchstone step 1: fetch every link in a report and check which return readable text."""
import asyncio
import ipaddress
import json
import re
import socket
import sys
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

import httpx
import trafilatura
from html import unescape

URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")
TIMEOUT = 15            # seconds per request (connect/read)
MAX_SECONDS = 30        # hard wall clock per URL: DNS, all redirect hops, body
MAX_BYTES = 3_000_000   # stop reading a page beyond this
MAX_REDIRECTS = 5
MIN_TEXT_CHARS = 200    # less than this = no usable text
MIN_META_CHARS = 50     # a meta description shorter than this is useless
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Touchstone/0.1"}
BOT_BLOCKED = "blocked the checker (bot protection)"
BLOCK_STATUSES = (403, 429, 503)
# Challenge/block pages must never reach the model as "page text". Titles of Cloudflare's own
# interstitials count on any status; body markers only on a 403/429/503, because normal pages
# behind Cloudflare load /cdn-cgi/challenge-platform/ scripts too, and articles can mention them.
CF_TITLES = ("just a moment...", "attention required! | cloudflare")
BLOCK_MARKERS = ("cf-chl", "challenge-platform", "cf-error-details",   # Cloudflare
                 "captcha-delivery.com", "datadome",                    # DataDome
                 "edgesuite",                # Akamai "Access Denied" (often errors&#46;edgesuite&#46;net)
                 "px-captcha", "perimeterx", "_pxappid")                # PerimeterX
TITLE_RE = re.compile(r"<title[^>]{0,200}>([^<]{0,200})", re.I)
H_OPEN = re.compile(r"<h([1-3])\b[^>]{0,500}>", re.I)
ANY_TAG = re.compile(r"<[^>]{0,500}>")
MAX_HEADINGS = 200


def outline(html):
    """(title, [[level, text], ...]) for the page's <title> and h1-h3 headings, in order.
    Plain text loses them (trafilatura flattens headings into ordinary lines), but a year in
    the title or a heading dates the figures under it. Linear: one scan, bounded inner reads."""
    m = TITLE_RE.search(html)
    title = unescape(" ".join(m.group(1).split())) if m else ""
    lower, heads, misses = html.lower(), [], 0
    for m in H_OPEN.finditer(html):
        end = lower.find(f"</h{m.group(1)}", m.end(), m.end() + 2000)
        if end < 0:
            misses += 1
            if misses > MAX_HEADINGS:       # broken or hostile markup: stop looking
                break
            continue
        text = " ".join(unescape(ANY_TAG.sub(" ", html[m.end():end])).split())
        if text:
            heads.append([int(m.group(1)), text[:300]])
        if len(heads) >= MAX_HEADINGS:
            break
    return title, heads


def bot_blocked(status, headers, html):
    """True for a bot-protection challenge or block page."""
    if headers.get("cf-mitigated", "").strip().lower() == "challenge":
        return True
    m = TITLE_RE.search(html[:100_000])
    title = " ".join(m.group(1).split()).lower() if m else ""
    if title.replace("\u2026", "...") in CF_TITLES:
        return True
    if status in BLOCK_STATUSES:
        low = html[:200_000].lower()
        server = headers.get("server", "").lower()
        return (any(k in low for k in BLOCK_MARKERS) or "x-datadome" in headers
                or "datadome" in server or ("akamaighost" in server and "access denied" in low))
    return False


def decode(body, encoding):
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def extract_urls(text):
    """Find every unique link in the report, in order."""
    urls = []
    for u in URL_RE.findall(text):
        u = u.rstrip(".,;:!?")
        if u not in urls:
            urls.append(u)
    return urls


BLOCKED_V6 = [ipaddress.ip_network(n) for n in ("::/96", "64:ff9b::/96", "64:ff9b:1::/48")]


def is_public(ip):
    """True only for public IPs, including IPv4 hidden inside IPv6 (mapped, 6to4,
    IPv4-compatible, NAT64), which is_global alone lets through."""
    if ip.version == 6:
        if any(ip in n for n in BLOCKED_V6):
            return False
        inner = ip.ipv4_mapped or ip.sixtofour
        if inner:
            return inner.is_global
    return ip.is_global


async def check_url(url):
    """SSRF protection: only allow http(s) URLs whose host resolves to public IPs only.
    Returns (ok, reason, ip): the request is then sent to that exact IP (pinned_request),
    so DNS can't change between this check and the connection (DNS rebinding)."""
    try:
        parsed = urlparse(url)
        host, port = parsed.hostname, parsed.port
    except ValueError:            # e.g. unclosed IPv6 bracket, port out of range
        return False, "malformed URL", None
    if parsed.scheme not in ("http", "https") or not host:
        return False, "not http(s)", None
    try:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, port or (443 if parsed.scheme == "https" else 80),
                                       type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False, "DNS failed", None
    ips = []
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            return False, "bad IP", None
        if not is_public(ip):
            return False, f"private IP {ip}", None
        ips.append(ip)
    if not ips:
        return False, "DNS failed", None
    return True, "", ips[0]


def pinned_request(url, ip):
    """(url with the host replaced by the checked IP, headers, extensions). Host header and
    TLS SNI keep the real hostname, so virtual hosting and certificate checks still work."""
    parts = urlsplit(url)
    literal = f"[{ip}]" if ip.version == 6 else str(ip)
    netloc = literal + (f":{parts.port}" if parts.port else "")
    host = parts.hostname + (f":{parts.port}" if parts.port else "")
    if ":" in parts.hostname:     # an IPv6 literal in the URL itself
        host = f"[{parts.hostname}]" + (f":{parts.port}" if parts.port else "")
    pinned = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
    ext = {"sni_hostname": parts.hostname} if parts.scheme == "https" else {}
    return pinned, {"Host": host}, ext


def peer_ok(r):
    """The IP we actually connected to must be public (catches DNS rebinding)."""
    stream = r.extensions.get("network_stream")
    addr = stream.get_extra_info("server_addr") if stream else None
    if not addr:
        return False
    try:
        return is_public(ipaddress.ip_address(addr[0]))
    except ValueError:
        return False


async def read_capped(r):
    """Read the body, stopping at MAX_BYTES."""
    body = bytearray()
    async for chunk in r.aiter_bytes():
        body += chunk
        if len(body) > MAX_BYTES:
            break
    return bytes(body[:MAX_BYTES])


async def fetch_one(url):
    """Fetch one URL, re-checking every redirect hop, and extract readable text.
    MAX_SECONDS is a hard wall clock: on expiry the task is cancelled and its socket
    closed, so a server trickling bytes can't keep anything running."""
    try:
        async with asyncio.timeout(MAX_SECONDS):
            got = await _get(url)
    except TimeoutError:
        return {"url": url, "status": "TIMEOUT", "detail": ""}
    except Exception as e:        # one bad link must never end the whole audit
        return {"url": url, "status": "ERROR", "detail": type(e).__name__}
    if isinstance(got, dict):
        return got
    html = got
    title, headings = outline(html)
    text = trafilatura.extract(html) or ""
    if len(text) < MIN_TEXT_CHARS:
        # JS-rendered pages often carry their key facts only in the meta description
        # (StartupBlink). Use it, flagged, so verdicts can say how thin the evidence is.
        meta = trafilatura.extract_metadata(html)
        desc = (meta.description or "").strip() if meta else ""
        if len(desc) >= MIN_META_CHARS:
            title = (meta.title or "").strip()
            text = "\n".join(x for x in (title, desc, text) if x)
            return {"url": url, "status": "OK", "detail": f"meta description only, {len(text)} chars",
                    "text": text, "meta_only": True, "title": title, "headings": headings}
        return {"url": url, "status": "NO_TEXT", "detail": "JS page or blocked?"}
    return {"url": url, "status": "OK", "detail": f"{len(text)} chars", "text": text,
            "title": title, "headings": headings}


async def _get(url):
    """The page's HTML as a string, or a result dict if the page can't be used."""
    current = url
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=HEADERS, follow_redirects=False) as client:
            for _ in range(MAX_REDIRECTS + 1):
                ok, reason, ip = await check_url(current)
                if not ok:
                    return {"url": url, "status": "BLOCKED", "detail": reason}
                target, host_header, ext = pinned_request(current, ip)
                async with client.stream("GET", target, headers=host_header, extensions=ext) as r:
                    if not peer_ok(r):
                        return {"url": url, "status": "BLOCKED", "detail": "connected to a non-public IP"}
                    if r.is_redirect:   # resolve against the hostname URL, not the pinned IP
                        current = urljoin(current, r.headers.get("location", ""))
                        continue
                    blocked = {"url": url, "status": "BLOCKED", "detail": BOT_BLOCKED}
                    if bot_blocked(r.status_code, r.headers, ""):
                        return blocked
                    if r.status_code >= 400:
                        if r.status_code in BLOCK_STATUSES:
                            html = decode(await read_capped(r), r.encoding or "utf-8")
                            if bot_blocked(r.status_code, r.headers, html):
                                return blocked
                        return {"url": url, "status": "HTTP_ERR", "detail": str(r.status_code)}
                    if "pdf" in r.headers.get("content-type", ""):
                        return {"url": url, "status": "PDF", "detail": "not handled yet"}
                    html = decode(await read_capped(r), r.encoding or "utf-8")
                    return blocked if bot_blocked(r.status_code, r.headers, html) else html
            return {"url": url, "status": "ERROR", "detail": "too many redirects"}
    except httpx.TimeoutException:
        return {"url": url, "status": "TIMEOUT", "detail": ""}
    except httpx.HTTPError as e:
        return {"url": url, "status": "ERROR", "detail": type(e).__name__}


async def _fetch_all(urls):
    sem = asyncio.Semaphore(8)

    async def one(u):
        async with sem:
            return await fetch_one(u)
    return await asyncio.gather(*(one(u) for u in urls))


def fetch_many(urls):
    """Fetch all URLs concurrently (8 at a time); results in the same order.
    Each URL is bounded by MAX_SECONDS, so this returns within ~MAX_SECONDS * len/8."""
    return asyncio.run(_fetch_all(urls)) if urls else []


def fetch(url):
    return fetch_many([url])[0]


def main():
    if len(sys.argv) != 2:
        print("usage: python fetch_links.py report.txt")
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        urls = extract_urls(f.read())
    if not urls:
        print("No links found in the report.")
        return

    print(f"Found {len(urls)} links. Fetching...\n")
    results = fetch_many(urls)

    for r in results:
        print(f"{r['status']:<9} {r['url'][:80]}  {r['detail']}")
    ok = sum(r["status"] == "OK" for r in results)
    print(f"\nUsable: {ok}/{len(results)} ({ok / len(results):.0%})   kill line: 70%")

    with open("fetch_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("Saved full results to fetch_results.json")


if __name__ == "__main__":
    main()
