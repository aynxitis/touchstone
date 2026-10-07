"""Touchstone step 1: fetch every link in a report and check which return readable text."""
import ipaddress
import json
import re
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura

URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")
TIMEOUT = 15            # seconds per request
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


def check_url(url):
    """SSRF protection: only allow http(s) URLs that resolve to public IPs.
    Known gap: DNS can change between this check and the request (DNS rebinding).
    Fine for a local test; the server version needs to pin the resolved IP."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False, "not http(s)"
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
    except socket.gaierror:
        return False, "DNS failed"
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False, "bad IP"
        if not ip.is_global:
            return False, f"private IP {ip}"
    return True, ""


def fetch(url):
    """Fetch one URL, re-checking every redirect hop, and extract readable text."""
    current = url
    try:
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=False) as client:
            for _ in range(MAX_REDIRECTS + 1):
                ok, reason = check_url(current)
                if not ok:
                    return {"url": url, "status": "BLOCKED", "detail": reason}
                r = client.get(current)
                if r.is_redirect:
                    current = urljoin(current, r.headers.get("location", ""))
                    continue
                break
            else:
                return {"url": url, "status": "ERROR", "detail": "too many redirects"}
    except httpx.TimeoutException:
        return {"url": url, "status": "TIMEOUT", "detail": ""}
    except httpx.HTTPError as e:
        return {"url": url, "status": "ERROR", "detail": type(e).__name__}

    if r.status_code >= 400:
        return {"url": url, "status": "HTTP_ERR", "detail": str(r.status_code)}
    if "pdf" in r.headers.get("content-type", ""):
        return {"url": url, "status": "PDF", "detail": "not handled yet"}

    text = trafilatura.extract(r.text) or ""
    if len(text) < MIN_TEXT_CHARS:
        return {"url": url, "status": "NO_TEXT", "detail": "JS page or blocked?"}
    return {"url": url, "status": "OK", "detail": f"{len(text)} chars", "text": text}


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
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch, urls))

    for r in results:
        print(f"{r['status']:<9} {r['url'][:80]}  {r['detail']}")
    ok = sum(r["status"] == "OK" for r in results)
    print(f"\nUsable: {ok}/{len(results)} ({ok / len(results):.0%})   kill line: 70%")

    with open("fetch_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("Saved full results to fetch_results.json")


if __name__ == "__main__":
    main()
