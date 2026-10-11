"""Locale-aware numbers (code-only): "2,585,187" in a report is "2 585 187" on a French page,
"29.7%" is "29,7%", "545,142" is German "545.142". Every number is read in each plausible
way, and two numbers match if any readings are equal.

Readings of a number token:
- grouped "2 585 187", "2.585.187", "2'585'187", "2,585,187" (groups of exactly 3 digits,
  one separator kind): the joined value. A single "," group ("2,500") is also read as a
  decimal (2.5), and a single "." group ("545.142") as thousands (545142), only when the text
  shows the European convention (a decimal comma "29,7", "1.234.567", "1.234,5"); otherwise
  "2,500" is 2500 and "545.142" is 545.142, as in English. Space-grouped tokens on a
  table-like line (a "|" row, or as many numbers as words) also yield each group alone
  ("100 200 300" may be a row of cells), never when a group starts with 0 ("1 023 456" is
  one number: "23" is not on that line); in prose "2 585 187" is one number only.
- plain "29,7" / "29.7": a decimal, comma or point.
A grouped token never starts with more than 3 digits, so "In 2025 2 585 187 cars" is 2025 and
2,585,187, never 20252585187."""
import re
from decimal import Decimal
from functools import lru_cache

SPACES = "    "
# Linear: each repeated group starts with a literal (the backreference to the separator).
NUMBER = (r"(?<!\d)(?:(?P<grp>\d{1,3}(?P<g>[" + SPACES + r"'’.,])\d{3}(?:(?P=g)\d{3})*)(?!\d)"
          r"(?P<dec>(?!(?P=g))[.,]\d+)?|(?P<int>\d+)(?P<pdec>[.,]\d+)?)")
NUMBER_RE = re.compile(NUMBER)


MAX_DIGITS = 30   # no real figure is longer; a page-long digit run would overflow Decimal


def readings(m, split=False, euro=True):
    """Every plausible value (Decimal) of a NUMBER match; none for absurdly long tokens.
    split: the token sits on a table-like line, so space groups may be separate cells.
    euro: the text shows the European convention (european()), so a single "," group may be
    a decimal comma and a single "." group a thousands dot."""
    if digits(m) > MAX_DIGITS:
        return set()
    if m.group("grp") is not None:
        grp, g, dec = m.group("grp"), m.group("g"), m.group("dec")
        out = {Decimal(grp.replace(g, "") + ("." + dec[1:] if dec else ""))}
        if g in ".," and grp.count(g) == 1 and not dec:
            dot = Decimal(grp.replace(g, "."))
            if g == ".":                                   # 545.142: English decimal
                out = {dot} | (out if euro else set())     # German thousands only if shown
            elif euro:
                out.add(dot)                               # 2,500 = 2.5 only if shown
        groups = grp.split(g)
        if split and g in SPACES and not any(x.startswith("0") for x in groups[1:]):
            out |= {Decimal(x) for x in groups}            # a row of separate numbers
        return out
    pdec = m.group("pdec")
    return {Decimal(m.group("int") + ("." + pdec[1:] if pdec else ""))}


@lru_cache(maxsize=8)        # judge() asks about the same page many times (a few MB at most here)
def european(text):
    """True if the text writes numbers the European way: a decimal comma that can't be a
    thousands group ("29,7", "1,25"), dot thousands ("1.234.567"), or both ("1.234,5")."""
    for m in NUMBER_RE.finditer(text):
        g, dec, pdec = m.group("g"), m.group("dec"), m.group("pdec")
        if pdec and pdec[0] == "," and len(pdec) != 4:
            return True
        if m.group("grp") is not None and (dec and dec[0] == "," or (g == "." and m.group("grp").count(".") > 1)):
            return True
    return False


def table_line(line):
    """A table row: markdown "| a | b |", a tab-separated row, or (like pdf_text.tableish, but
    a grouped "2 585 187" counts as one number) at least 3 numbers and as many numbers as
    words: "Robusta 73 356 71 910 71 033" is a row, "Sales reached 2 585 187 cars" is not."""
    s = line.strip()
    if s.startswith("|") or "\t" in s:
        return True
    nums = sum(1 for _ in NUMBER_RE.finditer(s))
    words = sum(1 for w in s.split() if any(c.isalpha() for c in w))
    return nums >= 3 and nums >= words


def tokens(text, page=False, euro=None):
    """(match, readings) for every number in the text. page: the passage side, where space
    groups on table-like lines may be separate cells. euro: None = european(text)."""
    euro = european(text) if euro is None else euro
    if not page:
        return [(m, readings(m, False, euro)) for m in NUMBER_RE.finditer(text)]
    out = []
    for line in text.split("\n"):
        split = None            # table_line(), only once a space-grouped token needs it
        for m in NUMBER_RE.finditer(line):
            if split is None and m.group("g") and m.group("g") in SPACES:
                split = table_line(line)
            out.append((m, readings(m, bool(split), euro)))
    return out


def digits(m):
    return sum(ch.isdigit() for ch in m.group())


def values(text, euro=None):
    """All readings of all numbers in the text (page side)."""
    return {v for _, rs in tokens(text, page=True, euro=euro) for v in rs}


def missing(text, passage, min_digits=2, scaled=frozenset(), euro=None):
    """Numbers in text (min_digits+ digits), as written, that no reading of a passage number
    equals. `scaled`: start offsets already supported in another way (units.py). euro: the
    passage's page shows the European convention (None: judged from the passage itself);
    the text's own numbers are read by the text's convention."""
    have = values(passage, euro)
    out = [m.group() for m, rs in tokens(text)
           if digits(m) >= min_digits and m.start() not in scaled and not rs & have]
    return list(dict.fromkeys(out))


def canon(v):
    """'2585187', '29.7': one string per value (for keyword sets)."""
    return format(v.normalize(), "f")
