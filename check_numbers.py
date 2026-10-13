"""Touchstone step 2 (code-only, zero tokens): do the numbers in each claim
appear in the page that claim cites?"""
import html
import json
import re
import sys

from fetch_links import URL_RE

NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def norm(n):
    return n.replace(",", "")


def clean(text):
    """Strip markdown: table pipes, list markers, bold, '[label](' before a link."""
    text = re.sub(r"\[[^\][]*\]\($", "", text)     # [^][]: no rescans on "[[[["
    if text.lstrip().startswith("|"):
        text = " — ".join(c.strip() for c in text.split("|") if c.strip())
    text = re.sub(r"^\s*(?:[-*+]|\d+\.)\s+", "", text)
    text = text.replace("**", "")
    return trim_parens(re.sub(r"\s+", " ", text).strip(" -*[]|"))


def trim_parens(text):
    """Strip the parentheses a removed link leaves at the ends ("... (+23.9%) (" from
    "(+23.9%) ([Eleport](url))"), but keep balanced ones: "(+23.9%)" stays whole."""
    while text:
        if text[-1] == "(" or (text[-1] == ")" and text.count(")") > text.count("(")):
            text = text[:-1].rstrip(" -*[]|")
        elif text[0] == ")" or (text[0] == "(" and text.count("(") > text.count(")")):
            text = text[1:].lstrip(" -*[]|")
        else:
            break
    return text


HAS_WORD = re.compile(r"[^\W_]")     # a letter or digit: passages without one are junk
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")

# Footnote citations: "[1]", "[1, 2]", "[^1]", "【1】" in the text, not followed by "(" or
# ":" (that would be a markdown link or a definition). Trailing punctuation is captured so
# it can move before the URL ("38% [1]." -> "38%. URL").
# Linear-time by construction: every repetition must start with "[" or "【", and whitespace
# runs are capped (an earlier nested "\s*" version hung on 20,000 spaces).
ONE_MARKER = r"(?:\[\^?\d{1,4}(?:[ \t]{0,3},[ \t]{0,3}\d{1,4}){0,20}\]|\u3010\d{1,4}\u3011)(?![(:])"
MARKER = re.compile(r"[ \t]{0,8}(" + ONE_MARKER + r"(?:[ \t]{0,8}" + ONE_MARKER + r")*)([.,;:!?]{0,3})")
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
    defined = set()                       # marker numbers with a source entry (URL or not)
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
        if n is not None:
            defined.add(n)
        link = URL_RE.search(rest)
        if link and n is not None:
            urls.setdefault(n, link.group().rstrip(".,;:!?"))
        elif not link:
            named_only += 1

    def to_url(m):
        if not any(n in defined for n in re.findall(r"\d+", m.group(1))):
            return m.group()              # no such source: "[2023]" is text, kept as written
        found = list(dict.fromkeys(urls[n] for n in re.findall(r"\d+", m.group(1)) if n in urls))
        # A run "[1][2]" gives the text all its URLs; links separated only by spaces form one
        # group in blocks(), so they never become empty claims of their own.
        return m.group(2) + (f" {' '.join(found)} " if found else "")

    body = [MARKER.sub(to_url, line) for i, line in enumerate(lines) if i not in defs]
    return "\n".join(body), named_only


# ---- Copy-format cleanup (ChatGPT's copy button), before any parsing ----
# HTML entities, only with their ';' ("&#x20;", "&nbsp;", "&amp;"): html.unescape alone would
# also turn "?a=1&copy=2" in a URL into "?a=1©=2".
ENTITY = re.compile(r"&(?:#\d{1,7}|#[xX][0-9a-fA-F]{1,6}|[a-zA-Z][a-zA-Z0-9]{1,31});")
MD_ESCAPE = re.compile(r"\\([&_#=?%+~])")          # "\&sz=32": markdown escapes in URLs
# A markdown image/link; a favicon chip when its URL holds "favicon" (Google's s2/favicons).
# Linear: the regex stops at the URL; the closing ")" is checked separately (LINK_END at the
# URL's end), so a URL with no ")" after it is never backtracked through char by char.
MD_LINK = re.compile(r"!?\[[^\[\]\n]{0,300}\]\(\s{0,3}(https?://[^\s()]{1,2000})")
LINK_END = re.compile(r"\s{0,3}\)")


def md_links(line):
    """(start, end, url) of each complete markdown link/image in the line."""
    out, pos = [], 0
    while m := MD_LINK.search(line, pos):
        if end := LINK_END.match(line, m.end()):
            out.append((m.start(), end.end(), m.group(1)))
            pos = end.end()
        else:
            pos = m.start() + 1
    return out


def drop_favicons(line):
    """The line without its favicon chips."""
    out, pos = [], 0
    for a, b, url in md_links(line):
        if "favicon" in url.lower():
            out.append(line[pos:a])
            pos = b
    return "".join(out) + line[pos:]
CHIP_COUNT = re.compile(r"\+\d{1,3}")              # "+1", "+2" after a chip
# Chart axis labels pasted as one line: "200¢/lb250¢/lb300¢/lbFeb 2025Nov 2025...".
GLUED = re.compile(r"[a-z%\u00a2]\d|\d[A-Z]")
GLUED_MIN = 4


def unescape_entities(text):
    return ENTITY.sub(lambda m: html.unescape(m.group()), text)


def is_chip_label(s):
    """A favicon chip's caption: a bare domain, a source name ("Reuters", "International
    Coffee Organization"), a file stem ("cmr-1225-e"). Short, no link, no sentence end."""
    return (0 < len(s) <= 60 and not URL_RE.search(s) and not s.startswith(("#", "|"))
            and not LIST_ITEM.match(s) and s[-1] not in ".!?:;")


def copy_cleanup(report):
    """Decode HTML entities, drop favicon chips and the caption lines right after them, drop
    chart-axis residue. None of these are claims, uncited passages or sources."""
    text = MD_ESCAPE.sub(r"\1", unescape_entities(report)).replace("\u00a0", " ")
    out, after_chip = [], 0
    for line in text.split("\n"):
        stripped = drop_favicons(line)
        if stripped != line and not stripped.strip():
            after_chip = 2                       # a line of chips only: captions may follow
            continue
        s = stripped.strip()
        if not s:
            out.append("")
            continue
        if after_chip and (CHIP_COUNT.fullmatch(s) or (after_chip == 2 and is_chip_label(s))):
            after_chip = 0 if CHIP_COUNT.fullmatch(s) else 1
            continue
        after_chip = 0
        if not URL_RE.search(s) and len(GLUED.findall(s)) >= GLUED_MIN:
            continue                             # chart axis labels glued together
        out.append(stripped)
    return "\n".join(out)


# ---- "Source:" lines and stat blocks ----
# "Source:", "**Sources:**", French "Source :" / "Sources :" (space, NBSP or U+202F before the
# colon: \s covers all three).
SOURCE_LINE = re.compile(r"^\s{0,8}(?:[-*+]\s{1,4})?[*_]{0,2}(?:sources?|references?)[*_]{0,2}\s{0,3}:", re.I)
RULE = re.compile(r"\|?[\s:\-|]*|[*_\s]{3,40}")
NUMBERED_TITLE = re.compile(r"\d{1,2}[.)]\s")       # "## 1. What happened in 2025?"
STAT_LINE_CHARS = 80


def stat_value(s):
    """The value of a stat heading ("# 354.32¢/lb", "# +94.6%"), or None for a section title.
    Numbers in headings are figures, not titles ("## 1. What happened" / "## 2026 outlook" are
    titles)."""
    if not s.startswith("#"):
        return None
    t = s.lstrip("#").strip()
    if (len(t) > 30 or not re.match(r"[+\-\u2212~\u2248\u00b1$\u20ac\u00a3\u00a5]{0,2}\d", t)
            or NUMBERED_TITLE.match(t) or t.endswith("?")):
        return None
    words = re.findall(r"[^\W\d_]{3,}", t)
    if len(words) > 2 or (re.match(r"(?:19|20)\d\d\b", t) and words):
        return None
    return t


def kind_of(line):
    s = line.strip()
    if stat_value(s) is not None:
        return "value"
    if s.startswith("|"):
        return "table"                                      # separator rows included
    if s.startswith("#") or RULE.fullmatch(s):
        return "heading"                                    # a boundary
    if SOURCE_LINE.match(line):
        return "source"
    if LIST_ITEM.match(line):
        return "list"
    return "para"


def units_of(lines):
    """[(kind, [line indices])]: one unit per line, except that table rows (consecutive) and
    list items (blank lines allowed between them) form one unit each."""
    units, prev_blank = [], False
    for i, line in enumerate(lines):
        if not line.strip():
            prev_blank = True
            continue
        k = kind_of(line)
        if units and k == units[-1][0] and ((k == "table" and not prev_blank) or k == "list"):
            units[-1][1].append(i)
        else:
            units.append((k, [i]))
        prev_blank = False
    return units


def stat_ish(kind, lines, idx):
    s = lines[idx[0]].strip()
    return kind == "value" or (kind == "para" and len(idx) == 1 and len(s) <= STAT_LINE_CHARS
                               and not URL_RE.search(s) and s[-1] not in ".!?:;,")


def stat_texts(lines, run):
    """One claim text per value in a stat block: "label: value — sub-line — ...". The line
    just before a value is its label; lines after it (up to the next label) are its details."""
    items = [(k, lines[idx[0]].strip()) for k, idx in run]
    vals = [j for j, (k, _) in enumerate(items) if k == "value"]
    out, label = [], items[vals[0] - 1][1] if vals[0] > 0 else None
    for n, j in enumerate(vals):
        stop = vals[n + 1] if n + 1 < len(vals) else len(items)
        between = [t for _, t in items[j + 1:stop]]
        subs, nxt = (between[:-1], between[-1] if between else None) if n + 1 < len(vals) else (between, None)
        value = stat_value(items[j][1])
        out.append(" \u2014 ".join([f"{label}: {value}" if label else value] + subs))
        label = nxt
    return out, items[:max(vals[0] - 1, 0)]


def row_cells(line):
    """A table row's cells, links removed: "| Samsung | 18% | +3% [src](url) |" -> ["Samsung",
    "18%", "+3%"]. A citation never ends up inside a cell value; a cell that held only a
    link is "" (its column is then left out of the claim)."""
    for a, b, _ in reversed(md_links(line)):
        line = line[:a] + line[b:]
    line = URL_RE.sub("", line)
    out = []
    for c in line.strip().strip("|").split("|"):
        c = re.sub(r"\[[^\][]*\]\($|\(\s*\)", "", c).replace("**", "")
        c = trim_parens(" ".join(c.split()).strip(" *[]"))     # "-1%" keeps its sign
        out.append("" if re.fullmatch(r"[-\u2013\u2014]*", c) else c)   # "—" placeholder: empty
    return out


def row_text(head, cells):
    """One table row as a claim: every cell paired with its column header, "Brand / group:
    Samsung; Q2 2025 shipment share: 18%; Annual trend: +3%", so the header's period and unit
    stay with the figure. Empty header cell -> the value alone; empty value -> column left
    out; a row with fewer cells than headers pairs what it has, extra cells go unlabelled.
    No header row: the cells joined with " \u2014 "."""
    if not head:
        return " \u2014 ".join(c for c in cells if c)
    head = head + [""] * (len(cells) - len(head))
    return "; ".join(f"{h}: {c}" if h else c for h, c in zip(head, cells) if c)


def row_labels(head, cells):
    """The header labels row_text() wrote for this row, one per line: the claim's context
    (quote_check.own_text strips them, so coverage asks only for the row's own values)."""
    return "\n".join(h for h, c in zip(head, cells) if h and c)


def table_rows(lines, idx):
    """A table's data rows as claim texts (row_text)."""
    rows = [i for i in idx if not RULE.fullmatch(lines[i].strip())]
    has_header = len(idx) > 1 and RULE.fullmatch(lines[idx[1]].strip())
    if not has_header:
        return [row_text(None, row_cells(lines[i])) for i in rows]
    head = row_cells(lines[rows[0]])
    return [row_text(head, row_cells(lines[i])) for i in rows[1:]]


def link_urls(line):
    return list(dict.fromkeys(m.group().rstrip(".,;:!?") for m in URL_RE.finditer(line)))


def attach_sources(report):
    """Rewrite stat blocks and "Source:" lines into ordinary cited lines for blocks():
      - A stat block (short label lines around number headings like "# 354.32¢/lb") becomes
        one line per value: "February 2025 monthly average: 354.32¢/lb — US dollars: ...".
      - A line starting "Source:"/"Sources:" gives ALL its links to the content block right
        above it: a paragraph, a stat block (with a one-line caption under it), a table (every
        data row becomes a claim) or a list (every item). Text after its last link is a claim
        with the same sources; the source's name before the links is not.
    """
    lines = report.split("\n")
    units = units_of(lines)
    out = {}                                 # line index -> replacement (None = drop)
    done = set()                             # unit indices already rewritten
    targets = {}                             # first line of a stat block -> its claim texts
    stat_of = {}                             # unit index -> first line of its stat block
    k = 0
    while k < len(units):                    # stat blocks
        j = k
        while j < len(units) and stat_ish(units[j][0], lines, units[j][1]):
            j += 1
        run = units[k:j]
        if any(kind == "value" for kind, _ in run):
            texts, title = stat_texts(lines, run)
            nxt = units[j] if j < len(units) else None
            if (nxt and nxt[0] == "para" and len(nxt[1]) == 1 and j + 1 < len(units)
                    and units[j + 1][0] == "source" and len(lines[nxt[1][0]].strip()) <= 200
                    and not URL_RE.search(lines[nxt[1][0]])):
                caption = lines[nxt[1][0]].strip()     # "ICO composite indicator; US cents..."
                texts = [f"{t} \u2014 {caption}" for t in texts]
                out[nxt[1][0]] = None
                done.add(j)
            keep = len(title)
            for kind, idx in run[keep:]:
                out[idx[0]] = None
            first = run[keep][1][0]
            targets[first] = texts
            stat_of.update({u: first for u in range(k + keep, j)})
            out[first] = "\n".join(texts)
            k = j
        else:
            k = max(j, k + 1)

    for n, (kind, idx) in enumerate(units):  # "Source:" lines
        if kind != "source":
            continue
        line = lines[idx[0]]
        urls = link_urls(line)
        if not urls:
            continue                         # a source named without a link: uncited text
        tail = clean(line[list(URL_RE.finditer(line))[-1].end():]).lstrip(" .,;:")
        out[idx[0]] = f"{tail} {' '.join(urls)}" if HAS_WORD.search(tail) and not connector(tail) else None
        p = n - 1
        while p >= 0 and p in done:
            p -= 1
        if p < 0:
            continue
        pkind, pidx = units[p]
        suffix = " " + " ".join(urls)
        if p in stat_of:                     # a stat block
            out[stat_of[p]] = "\n".join(t + suffix for t in targets[stat_of[p]])
        elif any(URL_RE.search(lines[i]) for i in pidx) or pkind in ("heading", "source", "value"):
            continue                         # already cited, or nothing to attach to
        elif pkind == "table":
            rows = table_rows(lines, pidx)
            for i in pidx:
                out[i] = None
            out[pidx[0]] = "\n".join(r + suffix for r in rows if HAS_WORD.search(r))
        else:                                # a paragraph, or every item of a list, but an
            if pkind == "list" and line[:1].isspace():   # indented "Source :" under a bullet
                pidx = pidx[-1:]                 # belongs to that bullet alone
            for i in pidx:
                out[i] = lines[i].rstrip() + suffix
    return "\n".join(x for i, line in enumerate(lines)
                     for x in ([line] if i not in out else [] if out[i] is None else [out[i]]))


# ---- Splitting into claims ----
CONNECTORS = {"and", "or", "plus", "also"}
SOURCE_LABEL = re.compile(r"(?:^|(?<=[\s.;,(]))(?:sources?|references?)[ \t]{0,3}:?[ \t]{0,3}$", re.I)


def connector(text):
    """Only connectors and punctuation ("and", ", and", ","): never a claim."""
    words = re.findall(r"[^\W_]+", text)
    return len(words) <= 3 and all(w.lower() in CONNECTORS for w in words)


def blocks(report):
    """(text, urls) per claim: blocks_ctx() without the context."""
    return [(t, us) for t, us, _ in blocks_ctx(report)]


def blocks_ctx(report):
    """Split the report into (text, urls, context) in document order; urls is a tuple of the claim's
    sources (empty for uncited text). A link group only owns the text on its own line
    (paragraph, bullet or table row) since the previous group, so uncited paragraphs never get
    merged into the next claim. Links separated only by connectors or punctuation ("[A](u1)
    and [B](u2)", "u1 u2") form one group: one claim with several sources.
    Exception: a lead-in line ending in ':' plus the bullets right after it form one block,
    owned by the link group that ends the block. context: that block's text before the
    linked line's own text ("Top 5 Best-Selling EV Models ... (Jan–Oct 2025):"), a prefix of
    text; "" otherwise. The model sees the whole text; coverage (quote_check.coverage_caps)
    only requires the claim's own numbers."""
    report, _ = resolve_footnotes(copy_cleanup(report))
    report = attach_sources(report)
    out, block = [], []          # block: uncited lead-in + bullets waiting for a link
    head, last_row = None, None  # current table's header cells; the previous uncited row

    def flush():                 # block ended without a link: each line is uncited
        out.extend((t, (), "") for t in block if not connector(t))
        block.clear()

    for line in report.split("\n"):
        s = line.strip()
        if not s:
            head = last_row = None                     # a blank line ends a table
            continue                                   # blank lines don't end a block
        if s.startswith("|") and "-" in s and RULE.fullmatch(s):
            flush()                                    # table separator: the row above is
            head, last_row = last_row, None            # the header (alignment colons fine)
            continue
        if s.startswith("#") or RULE.fullmatch(s):
            flush()
            head = last_row = None
            continue                                   # heading, rule
        links = list(URL_RE.finditer(line))
        if s.startswith("|"):
            flush()
            if not links:
                last_row = row_cells(line)             # header (or uncited data row)
                continue
            # A cited row is one claim with all its links, every cell under its header.
            cells = row_cells(line)
            text = row_text(head, cells)
            if HAS_WORD.search(text):
                out.append((text, tuple(dict.fromkeys(m.group().rstrip(".,;:!?") for m in links)),
                            row_labels(head, cells) if head else ""))
            last_row = None
            continue
        head = last_row = None
        if block and not LIST_ITEM.match(line):
            flush()                                    # a non-bullet line ends the block
        groups, last = [], 0
        for m in links:
            between = line[last:m.start()]
            if groups and connector(clean(between)):
                groups[-1][1].append(m)                # "[A](u1) and [B](u2)": one group
            else:
                groups.append((between, [m]))
            last = m.end()
        for between, ms in groups:
            text = clean(between)
            if SOURCE_LABEL.search(text):                  # "... strengthened. Sources: [A] and [B]"
                text = clean(SOURCE_LABEL.sub("", text)).rstrip(" ,;(")
            context = ""
            if block:
                context = " ".join(block)
                text = " ".join(block + [text]).strip()
                block.clear()
            if HAS_WORD.search(text) and not connector(text):
                context = context if text.startswith(context + " ") else ""
                out.append((text, tuple(dict.fromkeys(m.group().rstrip(".,;:!?") for m in ms)), context))
        tail = clean(line[last:])
        if not HAS_WORD.search(tail) or connector(tail):
            continue                                   # "." left after "([Name](url))."
        if links or not (block or tail.endswith(":")):
            out.append((tail, (), ""))
        else:
            block.append(tail)                         # start or extend a list block
    flush()
    return out


def segments(report):
    """blocks() with each claim's first source only: (text, url or None)."""
    return [(t, urls[0] if urls else None) for t, urls in blocks(report)]


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
