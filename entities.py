"""Entity check (code-only, zero tokens), the name counterpart of the number check:
a fact only counts as stated if the names it is about appear in the passage its quote
comes from. Catches real figures credited to the wrong company (claim 26: Moustachir's IPO
reported as VOLZ's), which quote verification alone can't see when the quote says "it"."""
import re
import unicodedata
from urllib.parse import urlparse

# Capitalized at the start of a sentence for grammar, not because they're names.
COMMON = set("""a an the this that these those it its they their there here he she his her we
our you your i in on at by for from to of with as and or but so if when while after before
since during between among over under about according also although because both each
either every many more most much no not one other some such than then thus yet all any
another few several first second third last next new major key overall meanwhile however
moreover today yesterday tomorrow recently currently now still reports report reported
reporting data figures sources source estimates analysts experts officials startup startups
ecosystem companies company founded launched backed based total government public
private local national international global regional""".split())

# Capitalized but not names: months, days, units, generic finance words.
GENERIC = set("""january february march april may june july august september october november
december monday tuesday wednesday thursday friday saturday sunday ipo ceo cto coo cfo gdp ai
vc vcs usd dzd eur gbp mad tnd egp sme smes b2b b2c saas fintech series round seed pre-seed
pre a b c d q1 q2 q3 q4 h1 h2 fy ltd inc llc sarl spa eurl no executive decree law article
ordinance act""".split())

TOKEN = re.compile(r"[^\W_][\w&\-]*(?:['’]s)?|[^\w\s]")   # words; punctuation one char each
BREAK = set(".!?:;|—–\"“")     # a word after one of these starts a sentence ('(' does not)
POSSESSIVE = re.compile(r"['’]s$")


def _tokens(text):
    """(word without possessive, had possessive, at sentence start) for each token."""
    start = True
    for tok in TOKEN.findall(text):
        word = POSSESSIVE.sub("", tok)
        yield word, word != tok, start
        start = tok in BREAK or (tok == "-" and start)


def _is_heading(line):
    """Title Case lines ('The Stock Exchange Pioneer') capitalize ordinary words."""
    words = [w for w in line.split() if len(w) >= 3 and w[:1].isalpha()]
    return bool(words) and sum(w[:1].isupper() for w in words) / len(words) >= 0.6


def _mid_sentence_caps(text):
    """Capitalized words seen somewhere other than a sentence start (headings skipped):
    those are names."""
    return {w.lower() for line in text.split("\n") if not _is_heading(line)
            for w, _, start in _tokens(line) if not start and w[:1].isupper()}


def entities(text, context=""):
    """Proper names in order of appearance: runs of capitalized words ('Algiers Stock
    Exchange'), acronyms ('ASF'), single names ('Yassir'). Lowercased, possessive stripped.
    A sentence-initial word ('Capital', 'State-backed' in a table cell) only counts if it is
    an acronym or appears capitalized mid-sentence in the text or `context` (e.g. the page)."""
    names = _mid_sentence_caps(text) | _mid_sentence_caps(context)
    out, run = [], []

    def end_run():
        if run and " ".join(run) not in out:
            out.append(" ".join(run))
        run.clear()

    for word, possessive, start in _tokens(text):
        low = word.lower()
        acronym = sum(ch.isupper() for ch in word) >= 2
        initial_ok = not start or (low not in COMMON and (acronym or low in names))
        if word[:1].isupper() and len(word) > 1 and low not in GENERIC and initial_ok:
            run.append(low)
            if possessive:                     # "Yassir's" ends the name
                end_run()
        else:
            end_run()
    end_run()
    return out


def _stems(word):
    """'algerian' also matches 'algeria'; 'startups' matches 'startup'."""
    forms = {word}
    for suffix in ("ns", "n", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            forms.add(word[: -len(suffix)])
    return forms


def fold(text):
    """Lowercase without accents: 'Algérie Télécom' matches 'Algerie Telecom'."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", text.lower())
                   if not unicodedata.combining(ch))


def named_in(entity, passage):
    """True if every word of the name (3+ letters) appears in the passage, ignoring case
    and accents."""
    entity, p = fold(entity), fold(passage)
    words = [w for w in entity.split() if len(w) >= 3] or entity.split()
    return all(any(re.search(r"(?<![a-z0-9])" + re.escape(f), p) for f in _stems(w)) for w in words)


# A fact that opens like this leaves its subject implicit: it is the claim's lead name.
IMPLICIT_SUBJECT = re.compile(
    r"^\W*(it|its|they|their|this|these|he|she|his|her|the (company|startup|firm|platform|"
    r"fund|group|business|app|venture|project|program|programme|deal|round|ipo|listing))\b", re.I)


def fact_entities(fact, claim_ents):
    """The claim's names this fact is about: those written in the fact, plus the claim's
    lead name (its subject) when the fact names none or opens with 'It'/'The company'."""
    own = [e for e in claim_ents if named_in(e, fact)]
    lead = claim_ents[:1]
    if lead and (not own or IMPLICIT_SUBJECT.match(fact)) and lead[0] not in own:
        own = lead + own
    return own


def paragraph_of(quote, page, on_page):
    """The page paragraph the (already verified) quote comes from, or the quote itself."""
    for para in page.split("\n"):
        if para.strip() and on_page(quote, para):
            return para
    return quote


def publisher(entity, url):
    """True if the name is the source's own (UpGrowth on upgrowth.dz): pages rarely name
    themselves."""
    host = (urlparse(url).hostname or "").lower().replace("-", "")
    first = entity.split()[0]
    return bool(host) and (entity.replace(" ", "").replace("-", "") in host
                           or (len(first) >= 4 and first in host))


def opening_name(text, page):
    """The name a sentence or paragraph opens with (its subject), if it opens with one."""
    if _is_heading(text):
        return None
    first = next(_tokens(text), None)
    ents = entities(text, page)
    return ents[0] if first and ents and ents[0].split()[0] == first[0].lower() else None


def sentence_before(quote, para):
    """The sentence just before the quote in its paragraph ('it' in a quote refers there)."""
    i = para.lower().find(quote.lower()[:40])
    head = para[:i] if i > 0 else ""
    parts = re.split(r"(?<=[.!?])\s+", head.strip())
    return parts[-1] if parts and parts[-1] else ""


def check_fact(fact, quote, claim, page, on_page, url=""):
    """None if every name the fact is about is in its quote, the quote's paragraph, or is
    the page's own subject (named in 2+ paragraphs). Otherwise ("missing", names, None), or
    ("contradicted", names, other) when the paragraph, the quote or the sentence before the
    quote opens with a different name the claim never mentions: it is about someone else."""
    claim_ents = entities(claim, page)
    need = [e for e in fact_entities(fact, claim_ents) if not publisher(e, url)]
    para = paragraph_of(quote, page, on_page)
    absent = [e for e in need if not named_in(e, quote) and not named_in(e, para)]
    if not absent:
        return None
    for text in (para, quote, sentence_before(quote, para)):
        other = opening_name(text, page)
        if other and not publisher(other, url) and not any(
                named_in(c, other) or named_in(other, c) for c in claim_ents):
            return ("contradicted", absent, other)
    paras = [p for p in page.split("\n") if p.strip()]
    absent = [e for e in absent if sum(named_in(e, p) for p in paras) < 2]
    return ("missing", absent, None) if absent else None
