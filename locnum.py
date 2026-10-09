"""Locale-aware numbers (code-only): "2,585,187" in a report is "2 585 187" on a French page,
"29.7%" is "29,7%", "545,142" is German "545.142". Every number is read in each plausible
way, and two numbers match if any readings are equal.

Readings of a number token:
- grouped "2 585 187", "2.585.187", "2'585'187", "2,585,187" (groups of exactly 3 digits,
  one separator kind): the joined value. A single "," or "." group ("1,234", "545.142") is
  also read as a decimal (1.234, 545.142). Space-grouped tokens on a page also yield each
  group alone ("100 200 300" may be a table row, not one number).
- plain "29,7" / "29.7": a decimal, comma or point.
A grouped token never starts with more than 3 digits, so "In 2025 2 585 187 cars" is 2025 and
2,585,187, never 20252585187."""
import re
from decimal import Decimal

SPACES = "    "
# Linear: each repeated group starts with a literal (the backreference to the separator).
NUMBER = (r"(?<!\d)(?:(?P<grp>\d{1,3}(?P<g>[" + SPACES + r"'’.,])\d{3}(?:(?P=g)\d{3})*)(?!\d)"
          r"(?P<dec>(?!(?P=g))[.,]\d+)?|(?P<int>\d+)(?P<pdec>[.,]\d+)?)")
NUMBER_RE = re.compile(NUMBER)


MAX_DIGITS = 30   # no real figure is longer; a page-long digit run would overflow Decimal


def readings(m, page=False):
    """Every plausible value (Decimal) of a NUMBER match; none for absurdly long tokens."""
    if digits(m) > MAX_DIGITS:
        return set()
    if m.group("grp") is not None:
        grp, g, dec = m.group("grp"), m.group("g"), m.group("dec")
        out = {Decimal(grp.replace(g, "") + ("." + dec[1:] if dec else ""))}
        if g in ".," and grp.count(g) == 1 and not dec:
            out.add(Decimal(grp.replace(g, ".")))            # 1,234 = 1.234 too
        if page and g in SPACES:
            out |= {Decimal(x) for x in grp.split(g)}         # a row of separate numbers
        return out
    pdec = m.group("pdec")
    return {Decimal(m.group("int") + ("." + pdec[1:] if pdec else ""))}


def digits(m):
    return sum(ch.isdigit() for ch in m.group())


def values(text):
    """All readings of all numbers in the text (page side)."""
    return {v for m in NUMBER_RE.finditer(text) for v in readings(m, page=True)}


def missing(text, passage, min_digits=2, scaled=frozenset()):
    """Numbers in text (min_digits+ digits), as written, that no reading of a passage number
    equals. `scaled`: start offsets already supported in another way (units.py)."""
    have = values(passage)
    out = [m.group() for m in NUMBER_RE.finditer(text)
           if digits(m) >= min_digits and m.start() not in scaled and not readings(m) & have]
    return list(dict.fromkeys(out))


def canon(v):
    """'2585187', '29.7': one string per value (for keyword sets)."""
    return format(v.normalize(), "f")
