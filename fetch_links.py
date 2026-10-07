"""Touchstone step 1: fetch every link in a report and check which return readable text."""
import asyncio
import ipaddress
import json
import re
import socket
import sys
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura

URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")
TIMEOUT = 15            # seconds per request (connect/read)
MAX_SECONDS = 30        # hard wall clock per URL: DNS, all redirect hops, body
MAX_BYTES = 3_000_000   # stop reading a page beyond this
MAX_REDIRECTS = 5
MIN_TEXT_CHARS = 200    # less than this = no usable text
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Touchstone/0.1"}


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
    """SSRF protection: only allow http(s) URLs that resolve to public IPs.
    Known gap: DNS can change between this check and the request (DNS rebinding).
    fetch_one() re-checks the IP it actually connected to before reading the body, but the
    GET itself is already sent by then. Pin the resolved IP before deploying."""
    try:
        parsed = urlparse(url)
        host, port = parsed.hostname, parsed.port
    except ValueError:            # e.g. unclosed IPv6 bracket, port out of range
        return False, "malformed URL"
    if parsed.scheme not in ("http", "https") or not host:
        return False, "not http(s)"
    try:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, port or 443)
    except socket.gaierror:
        return False, "DNS failed"
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False, "bad IP"
        if not is_public(ip):
            return False, f"private IP {ip}"
    return True, ""


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
    body, encoding = got
    try:
        html = body.decode(encoding, errors="replace")
    except LookupError:
        html = body.decode("utf-8", errors="replace")
    text = trafilatura.extract(html) or ""
    if len(text) < MIN_TEXT_CHARS:
        return {"url": url, "status": "NO_TEXT", "detail": "JS page or blocked?"}
    return {"url": url, "status": "OK", "detail": f"{len(text)} chars", "text": text}


async def _get(url):
    """(body bytes, encoding), or a result dict if the page can't be used."""
    current = url
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=HEADERS, follow_redirects=False) as client:
            for _ in range(MAX_REDIRECTS + 1):
                ok, reason = await check_url(current)
                if not ok:
                    return {"url": url, "status": "BLOCKED", "detail": reason}
                async with client.stream("GET", current) as r:
                    if not peer_ok(r):
                        return {"url": url, "status": "BLOCKED", "detail": "connected to a non-public IP"}
                    if r.is_redirect:
                        current = urljoin(current, r.headers.get("location", ""))
                        continue
                    if r.status_code >= 400:
                        return {"url": url, "status": "HTTP_ERR", "detail": str(r.status_code)}
                    if "pdf" in r.headers.get("content-type", ""):
                        return {"url": url, "status": "PDF", "detail": "not handled yet"}
                    return await read_capped(r), r.encoding or "utf-8"
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
