"""Unit-scaled numbers (code-only): "15.9 GW" in a claim is the "15,925 megawatts" on the
page. A claim number only matches a scaled page number when BOTH carry an explicit unit from
the same family (power, energy, or plain magnitude); a number with no unit is never scaled."""
import re
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP

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
# A number, at most one space/hyphen, a unit, and no letter right after the unit ("5 Morocco"
# is not 5 M). Linear: no nested repeats.
QUANTITY = re.compile(r"(?<![\d.,])(\d[\d,]*(?:\.\d+)?)[ \t -]?(?:" + UNIT + r")(?![A-Za-z])")


def _prefix(word):
    w = word.lower()
    for p in ("kilo", "mega", "giga", "tera"):
        if w.startswith(p):
            return PREFIX[p]
    return 1


def _unit(m):
    """(family, scale) for a QUANTITY match."""
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


def quantities(text):
    """[(number as written, family, scale, start offset)] for every number with a unit."""
    return [(m.group(1), *_unit(m), m.start(1)) for m in QUANTITY.finditer(text)]


def scaled_match(claim_quantity, passage_quantities):
    """True if a passage number in the same unit family converts to the claim's number at the
    claim's stated precision, rounded or cut off: 15,925 MW is 15.9 GW and 16 GW, not 17 GW;
    3,267 MW is 3.2 GW (cut off) or 3.3 GW (rounded)."""
    num, family, scale, _ = claim_quantity
    want = Decimal(num.replace(",", ""))
    places = Decimal(1).scaleb(want.as_tuple().exponent)      # 15.9 -> 0.1, 16 -> 1
    for n, fam, sc, _ in passage_quantities:
        if fam != family:
            continue
        v = Decimal(n.replace(",", "")) * sc / scale
        try:
            if want in (v.quantize(places, ROUND_HALF_UP), v.quantize(places, ROUND_DOWN)):
                return True
        except InvalidOperation:      # absurdly far apart (more than 28 digits): no match
            continue
    return False


def unit_supported(claim, passage):
    """Start offsets (in the claim) of numbers that a unit-scaled passage number supports.
    Only numbers written with a unit in the claim can be here."""
    have = quantities(passage)
    return {q[3] for q in quantities(claim) if scaled_match(q, have)}
