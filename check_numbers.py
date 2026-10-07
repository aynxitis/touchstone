"""Touchstone step 2 (code-only, zero tokens): do the numbers in each claim
appear in the page that claim cites?"""
import json
import re
import sys

from fetch_links import URL_RE

NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def norm(n):
    return n.replace(",", "")


def clean(text):
    """Strip markdown: table pipes, list markers, bold, '[label](' before a link."""
    text = re.sub(r"\[[^\]]*\]\($", "", text)
    if text.lstrip().startswith("|"):
        text = " — ".join(c.strip() for c in text.split("|") if c.strip())
    text = re.sub(r"^\s*(?:[-*+]|\d+\.)\s+", "", text)
    text = text.replace("**", "")
    return re.sub(r"\s+", " ", text).strip(" -*()[]|")


def segments(report):
    """Split the report into (text, url) in document order; url is None for uncited text.
    A link only owns the text on its own line (paragraph, bullet or table row) since the
    previous link, so uncited paragraphs never get merged into the next claim."""
    out = []
    for line in report.split("\n"):
        s = line.strip()
        if not s or s.startswith("#") or re.fullmatch(r"\|?[\s:\-|]*", s):
            continue                                   # blank, heading, table separator
        last = 0
        links = list(URL_RE.finditer(line))
        if not links and s.startswith("|"):
            continue                                   # uncited table row = header
        for m in links:
            text = clean(line[last:m.start()])
            last = m.end()
            if text:
                out.append((text, m.group().rstrip(".,;:!?")))
        tail = clean(line[last:])
        if tail:
            out.append((tail, None))
    return out


def claims_with_sources(report):
    """Pair each chunk of cited text with the link that follows it."""
    return [(t, u) for t, u in segments(report) if u]


def main():
    if len(sys.argv) != 2:
        print("usage: python check_numbers.py report.txt")
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        report = f.read()
    with open("fetch_results.json", encoding="utf-8") as f:
        pages = {r["url"]: r.get("text", "") for r in json.load(f)}

    for i, (claim, url) in enumerate(claims_with_sources(report), 1):
        print(f"\n[{i}] {claim[:110]}{'...' if len(claim) > 110 else ''}")
        print(f"    source: {url}")
        text = pages.get(url, "")
        if not text:
            print("    SOURCE NOT FETCHED")
            continue
        page_nums = {norm(n) for n in NUM_RE.findall(text)}
        nums = [norm(n) for n in NUM_RE.findall(claim)]
        if not nums:
            print("    no numbers (needs the LLM check)")
        for n in nums:
            print(f"    {'found  ' if n in page_nums else 'MISSING'}  {n}")


if __name__ == "__main__":
    main()
