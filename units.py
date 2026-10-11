"""Unit-scaled numbers (code-only): "15.9 GW" in a claim is the "15,925 megawatts" on the
page. A claim number only matches a scaled page number when BOTH carry an explicit unit from
the same family (power, energy, or plain magnitude); a number with no unit is never scaled."""
import re
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP

import locnum

PREFIX = {"": 1, "k": 10**3, "kilo": 10**3, "M": 10**6, "mega": 10**6, "G": 10**9,
          "giga": 10**9, "T": 10**12, "tera": 10**12}
MAGNITUDE = {"thousand": 10**3, "k": 10**3, "K": 10**3, "million": 10**6, "mn": 10**6,
             "mln": 10**6, "M": 10**6, "billion": 10**9, "bn": 10**9, "B": 10**9,
             "trillion": 10**12, "tn": 10**12}

# Longest forms first (MWh before MW, megawatt-hours before megawatts). Symbols are
# case-sensitive (M = mega/million, m = metre); written-out words are not.
UNIT = (r"(?P<wh>[kMGT]?Wh)|(?P<w>[kMGT]?W)"
        r"|(?P<whw>(?i:(?:kilo|mega|giga|tera)?watt[- ]?hours?))"
        r"|(?P<ww>(?i:(?:kilo|mega|giga|tera)?watts?))"
        r"|(?P<mw>(?i:thousand|million|billion|trillion)|mn|mln|bn|tn|[kKMB])")
# A unit right after a number: at most one space/hyphen, then the unit, and no letter
# after it ("5 Morocco" is not 5 M). Tried with .match() at the end of each NUMBER_RE token:
# one regex "number then unit" backtracked through every digit group and restarted at each
# group when no unit followed (quadratic: 8,000 groups of a 3 MB page took 28 s).
UNIT_AFTER = re.compile(r"[ \t\u00a0-]?(?:" + UNIT + r")(?![A-Za-z])")


def _prefix(word):
    w = word.lower()
    for p in ("kilo", "mega", "giga", "tera"):
        if w.startswith(p):
            return PREFIX[p]
    return 1


def _unit(m):
    """(family, scale) for a UNIT_AFTER match."""
    if m.group("wh"):
        return "Wh", PREFIX[m.group("wh")[:-2]]
    if m.group("w"):
        return "W", PREFIX[m.group("w")[:-1]]
    if m.group("whw"):
        return "Wh", _prefix(m.group("whw"))
    if m.group("ww"):
        return "W", _prefix(m.group("ww"))
    word = m.group("mw")
    return "x", MAGNITUDE.get(word) or MAGNITUDE[word.lower()]


def quantities(text, page=False, euro=None):
    """[(readings, family, scale, start offset)] for every number with a unit; readings are
    the number's plausible values (locnum.tokens: page side, table rows, locale convention).
    Linear: each number token is read once and its unit tried once, anchored at the token's
    end. Offsets are into the text (claim side) or into the token's line (page side, unused)."""
    out = []
    lines = text.split("\n") if page else [text]
    euro = locnum.european(text) if euro is None else euro
    for line in lines:
        for m, rs in locnum.tokens(line, page=page, euro=euro):
            if u := UNIT_AFTER.match(line, m.end()):
                out.append((rs, *_unit(u), m.start()))
    return out


def scaled_match(claim_quantity, passage_quantities):
    """True if a passage number in the same unit family converts to the claim's number at the
    claim's stated precision, rounded or cut off: 15,925 MW is 15.9 GW and 16 GW, not 17 GW;
    3,267 MW is 3.2 GW (cut off) or 3.3 GW (rounded)."""
    wants, family, scale, _ = claim_quantity
    for want in wants:
        places = Decimal(1).scaleb(want.as_tuple().exponent)      # 15.9 -> 0.1, 16 -> 1
        for ns, fam, sc, _ in passage_quantities:
            if fam != family:
                continue
            for n in ns:
                v = n * sc / scale
                try:
                    if want in (v.quantize(places, ROUND_HALF_UP), v.quantize(places, ROUND_DOWN)):
                        return True
                except InvalidOperation:  # absurdly far apart (more than 28 digits): no match
                    continue
    return False


def unit_supported(claim, passage, euro=None):
    """Start offsets (in the claim) of numbers that a unit-scaled passage number supports.
    Only numbers written with a unit in the claim can be here. euro: as locnum.missing()."""
    have = quantities(passage, page=True, euro=euro)
    return {q[3] for q in quantities(claim) if scaled_match(q, have)}
