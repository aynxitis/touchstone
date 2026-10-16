"""Unit-scaled numbers (code-only): "15.9 GW" in a claim is the "15,925 megawatts" on the
page. A claim number only matches a scaled page number when BOTH carry an explicit unit from
the same family (power, energy, length, area, or plain magnitude); a number with no unit is
never scaled. In a range ("30–110 cm", "300 to 1,100 mm") the first number takes the unit
written after the second."""
import re
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP

import locnum

PREFIX = {"": 1, "k": 10**3, "kilo": 10**3, "M": 10**6, "mega": 10**6, "G": 10**9,
          "giga": 10**9, "T": 10**12, "tera": 10**12}
MAGNITUDE = {"thousand": 10**3, "k": 10**3, "K": 10**3, "million": 10**6, "mn": 10**6,
             "mln": 10**6, "M": 10**6, "m": 10**6, "billion": 10**9, "bn": 10**9, "B": 10**9,
             "milliard": 10**9, "trillion": 10**12, "tn": 10**12}

# Longest forms first (MWh before MW, megawatt-hours before megawatts). Symbols are
# case-sensitive (M = mega/million, m = metre); written-out words are not.
UNIT = (r"(?P<wh>[kMGT]?Wh)|(?P<w>[kMGT]?W)"
        r"|(?P<whw>(?i:(?:kilo|mega|giga|tera)?watt[- ]?hours?))"
        r"|(?P<ww>(?i:(?:kilo|mega|giga|tera)?watts?))"
        r"|(?P<area>km[\u00b22]|m[\u00b22]|ha|(?i:hectares?|square (?:kilo)?met(?:re|er)s?|sq\.? ?km"
        r"|kilom[eè]tres? carr[eé]s?|m[eè]tres? carr[eé]s?))"
        r"|(?P<len>mm|cm|km|(?i:(?:milli|centi|kilo)?met(?:re|er)s?|(?:milli|centi|kilo)?m[eè]tres?))"
        r"|(?P<mw>(?i:thousands?|millions?|milliards?|billions?|trillions?)|mn|mln|bn|tn|[kKMBm])")
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


AREA = {"km": Decimal(10**6), "m": Decimal(1), "ha": Decimal(10**4), "he": Decimal(10**4),
        "sq": Decimal(10**6), "sk": Decimal(10**6), "sm": Decimal(1)}
LENGTH = {"mm": Decimal("0.001"), "cm": Decimal("0.01"), "km": Decimal(1000), "m": Decimal(1)}
FAMILIES = {"W", "Wh", "len", "area"}       # what a number measures, besides a plain magnitude


def _area(word):
    w = word.lower()
    if w.startswith(("km", "sq", "square kilo", "kilom")):
        return AREA["km"]
    if w.startswith(("ha", "hectare")):
        return AREA["ha"]
    return AREA["m"]


def _length(word):
    w = word.lower()
    for p, k in (("milli", "mm"), ("centi", "cm"), ("kilo", "km"), ("mm", "mm"), ("cm", "cm"), ("km", "km")):
        if w.startswith(p):
            return LENGTH[k]
    return LENGTH["m"]


RANGE_SEP = re.compile(r"[ \t\u00a0]{0,2}(?:[\u2013\u2014-]|to(?= )|à(?= ))[ \t\u00a0]{0,2}")


def unit_at(text, end, ranged=True):
    """(family, scale, end of the unit) for the unit written right after the number that ends
    at `end`, or None. "m" glued to a number is million ("53.6m"), spaced it is a metre
    ("145 m"). ranged: a number followed by "–110 cm" / " to 1,100 mm" takes that unit."""
    if u := UNIT_AFTER.match(text, end):
        if u.group("mw") == "m" and u.start("mw") > end:
            return "len", LENGTH["m"], u.end()
        return (*_unit(u), u.end())
    if ranged and (sep := RANGE_SEP.match(text, end)) and (n := locnum.NUMBER_RE.match(text, sep.end())):
        if got := unit_at(text, n.end(), ranged=False):
            return got
    return None


def _unit(m):
    """(family, scale) for a UNIT_AFTER match."""
    if m.group("area"):
        return "area", _area(m.group("area"))
    if m.group("len"):
        return "len", _length(m.group("len"))
    if m.group("wh"):
        return "Wh", PREFIX[m.group("wh")[:-2]]
    if m.group("w"):
        return "W", PREFIX[m.group("w")[:-1]]
    if m.group("whw"):
        return "Wh", _prefix(m.group("whw"))
    if m.group("ww"):
        return "W", _prefix(m.group("ww"))
    word = m.group("mw")
    word = word if word in MAGNITUDE else word.lower().removesuffix("s")
    return "x", MAGNITUDE[word]


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
            # "m" is million only glued to the number ("53.6m"); "5 m" is five metres.
            if u := unit_at(line, m.end()):
                out.append((rs, u[0], u[1], m.start()))
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


def rounded_match(claim_quantity, passage_values):
    """True if a claim number with a scale word ("53.64 million", "2.6 million", "15.43
    milliards") is a passage number written out in full, rounded to the claim's unit and
    decimals: 53 636 104 -> 53.64 million, 2 565 347 -> 2.6 or 2.57 million (not 2.58). Only the
    passage value is rounded, half up, never cut off and never the claim."""
    wants, family, scale, _ = claim_quantity
    if family != "x":
        return False
    for want in wants:
        places = Decimal(1).scaleb(want.as_tuple().exponent)
        for n in passage_values:
            if n < scale / 2:                      # can't round to a non-zero count of units
                continue
            try:
                if (n / scale).quantize(places, ROUND_HALF_UP) == want:
                    return True
            except InvalidOperation:
                continue
    return False


def unit_supported(claim, passage, euro=None):
    """Start offsets (in the claim) of numbers that a unit-scaled passage number supports:
    one written with a unit of the same family (15.9 GW = 15,925 MW), or, for a scale word
    (million, k, milliard...), any passage number that rounds to it (53.64 million = 53 636 104).
    Only numbers written with a unit in the claim can be here. euro: as locnum.missing()."""
    want = quantities(claim)
    if not want:
        return set()
    have = quantities(passage, page=True, euro=euro)
    plain = None
    out = set()
    for q in want:
        if scaled_match(q, have):
            out.add(q[3])
        elif q[1] == "x":
            if plain is None:
                plain = {v for _, rs in locnum.tokens(passage, page=True, euro=euro) for v in rs}
            if rounded_match(q, plain):
                out.add(q[3])
    return out
