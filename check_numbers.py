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


LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")

# Footnote citations: "[1]", "[1, 2]", "[^1]", "【1】" in the text, not followed by "(" or
# ":" (that would be a markdown link or a definition). Trailing punctuation is captured so
# it can move before the URL ("38% [1]." -> "38%. URL").
ONE_MARKER = r"(?:\[\^?\d+(?:\s*,\s*\d+)*\]|\u3010\d+\u3011)(?![(:])"
MARKER = re.compile(r"\s*((?:\s*" + ONE_MARKER + r")+)([.,;:!?]*)")   # a run: "[1][2]," 
SOURCES_HEADING = re.compile(r"^\W*(sources|references|citations|bibliography|works cited|links)\W*$", re.I)
BRACKET_DEF = re.compile(r"^\s*(?:\[\^?(\d+)\]|【(\d+)】):?\s*(.*)$")   # [1] / [1]: / [^1]: / 【1】
NUMBERED_DEF = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")                           # 1. / 1)


def resolve_footnotes(report):
    """Turn footnote citations into inline URLs so segments() can treat them like links.
    Returns (report, named_only): named_only counts source-list entries without a URL.
    Source definitions are '[1] ...', '[1]: ...', '[^1]: ...', '【1】...' lines anywhere, and
    list items ('1. Title url', '- Title url') under a Sources/References heading. They are
    removed from the body, since they are not claims. A numbered line outside a Sources
    section only counts if its number is used as a marker, so ordinary lists stay."""
    lines = report.split("\n")
    used = {n for m in MARKER.finditer(report) for n in re.findall(r"\d+", m.group(1))}
    urls, defs, named_only, in_sources = {}, set(), 0, False
    for i, line in enumerate(lines):
        s_ = line.strip()
        if SOURCES_HEADING.match(s_):
            in_sources, _ = True, defs.add(i)
            continue
        if in_sources and (s_.startswith("#") or (s_ and not LIST_ITEM.match(line)
                                                  and not BRACKET_DEF.match(line))):
            in_sources = False            # another heading or a paragraph: section over
        m = BRACKET_DEF.match(line)
        n, rest = (m.group(1) or m.group(2), m.group(3)) if m else (None, None)
        if n is None and (m := NUMBERED_DEF.match(line)) and (in_sources or m.group(1) in used):
            n, rest = m.group(1), m.group(2)
            link = URL_RE.search(rest)
            if not in_sources and not link:
                continue                  # "1. text" in the body: an ordinary list item
        if n is None and in_sources and LIST_ITEM.match(line):
            rest = line                   # "- Title url" under Sources: unnumbered entry
        elif n is None:
            continue
        defs.add(i)
        link = URL_RE.search(rest)
        if link and n is not None:
            urls.setdefault(n, link.group().rstrip(".,;:!?"))
        elif not link:
            named_only += 1

    def to_url(m):
        found = [urls[n] for n in re.findall(r"\d+", m.group(1)) if n in urls]
        # One claim, one source (like inline links): a run "[1][2]" gives the text the first
        # URL; the others stay out so they don't become empty claims of their own.
        return m.group(2) + (f" {found[0]} " if found else "")

    body = [MARKER.sub(to_url, line) for i, line in enumerate(lines) if i not in defs]
    return "\n".join(body), named_only


def segments(report):
    """Split the report into (text, url) in document order; url is None for uncited text.
    A link only owns the text on its own line (paragraph, bullet or table row) since the
    previous link, so uncited paragraphs never get merged into the next claim.
    Exception: a lead-in line ending in ':' plus the bullets right after it form one block,
    owned by the link that ends the block."""
    report, _ = resolve_footnotes(report)
    out, block = [], []          # block: uncited lead-in + bullets waiting for a link

    def flush():                 # block ended without a link: each line is uncited
        out.extend((t, None) for t in block)
        block.clear()

    for line in report.split("\n"):
        s = line.strip()
        if not s:
            continue                                   # blank lines don't end a block
        if s.startswith("#") or re.fullmatch(r"\|?[\s:\-|]*", s):
            flush()
            continue                                   # heading, table separator
        links = list(URL_RE.finditer(line))
        if not links and s.startswith("|"):
            flush()
            continue                                   # uncited table row = header
        if block and not LIST_ITEM.match(line):
            flush()                                    # a non-bullet line ends the block
        last = 0
        for m in links:
            text = clean(line[last:m.start()])
            last = m.end()
            if block:
                text = " ".join(block + [text]).strip()
                block.clear()
            if text:
                out.append((text, m.group().rstrip(".,;:!?")))
        tail = clean(line[last:])
        if not tail:
            continue
        if links or not (block or tail.endswith(":")):
            out.append((tail, None))
        else:
            block.append(tail)                         # start or extend a list block
    flush()
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
