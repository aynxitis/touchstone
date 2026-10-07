"""Touchstone step 2 (code-only, zero tokens): do the numbers in each claim
appear in the page that claim cites?"""
import json
import re
import sys

from fetch_links import URL_RE

NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def norm(n):
    return n.replace(",", "")


def claims_with_sources(report):
    """Pair each chunk of text with the link that follows it."""
    pairs, last = [], 0
    for m in URL_RE.finditer(report):
        url = m.group().rstrip(".,;:!?")
        claim = report[last:m.start()]
        claim = re.sub(r"\[[^\]]*\]\($", "", claim)   # drop "[label](" before the link
        claim = claim.strip(" -*\n()[]")
        last = m.end()
        if claim:
            pairs.append((claim, url))
    return pairs


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
