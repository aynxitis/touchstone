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

# Common technical acronyms: written as acronyms but not names, so never entities on their
# own. A passage may write them out ("solar photovoltaic" for PV).
ACRONYMS = {"pv": ["photovoltaic"], "csp": ["concentrated solar power", "concentrating solar power"],
            "ev": ["electric vehicle"], "evs": ["electric vehicle"], "gdp": ["gross domestic product"],
            "ipo": ["initial public offering"], "ai": ["artificial intelligence"],
            "co2": ["carbon dioxide"], "w": ["watt"], "kw": ["kilowatt"], "mw": ["megawatt"],
            "gw": ["gigawatt"], "tw": ["terawatt"], "wh": ["watt-hour", "watt hour"],
            "kwh": ["kilowatt-hour", "kilowatt hour"], "mwh": ["megawatt-hour", "megawatt hour"],
            "gwh": ["gigawatt-hour", "gigawatt hour"], "twh": ["terawatt-hour", "terawatt hour"]}
GENERIC |= set(ACRONYMS)

# The same acronym in English and French: "POS terminals" on a French page are "TPE". Matched
# as whole words with their exact case ("UE", "IA", "TIC" are ordinary words in lowercase).
ACRONYM_PAIRS = [("POS", "TPE"), ("GDP", "PIB"), ("SME", "PME"), ("VAT", "TVA"), ("FDI", "IDE"),
                 ("UN", "ONU"), ("EU", "UE"), ("IMF", "FMI"), ("WHO", "OMS"), ("WTO", "OMC"),
                 ("NGO", "ONG"), ("ICT", "TIC"), ("AI", "IA")]
ACRONYM_EQUIV = {}
for _en, _fr in ACRONYM_PAIRS:
    ACRONYM_EQUIV.setdefault(_en, set()).update({_fr, _fr + "s"})
    ACRONYM_EQUIV.setdefault(_fr, set()).update({_en, _en + "s"})
    ACRONYM_EQUIV[_en + "s"], ACRONYM_EQUIV[_fr + "s"] = ACRONYM_EQUIV[_en], ACRONYM_EQUIV[_fr]
# Quarter / half codes (Q2, T2 = French trimestre, H1) are periods, checked by
# quote_check.period_caps(), never names.
GENERIC |= {f"{p}{n}" for p in "qt" for n in "1234"} | {"h1", "h2"}

# Demonyms and region adjectives: capitalized, but they describe, they don't name ("its total
# European sales"). A run made only of these (and compass words) is never an entity; inside a
# longer name it stays ("European Union", "Algerian Startup Fund").
DEMONYMS = set("""european african asian american arab arabic latin nordic scandinavian
mediterranean maghrebi maghreb sub-saharan gulf western eastern northern southern north south
east west central middle algerian moroccan tunisian egyptian libyan mauritanian sudanese
french german british english scottish welsh irish italian spanish portuguese dutch belgian
swiss austrian danish swedish norwegian finnish icelandic polish czech slovak hungarian
romanian bulgarian greek turkish russian ukrainian baltic estonian latvian lithuanian croatian
serbian slovenian chinese japanese korean indian pakistani indonesian vietnamese thai
malaysian filipino australian canadian mexican brazilian argentine argentinian chilean
colombian peruvian nigerian kenyan ethiopian ghanaian senegalese ivorian south-african
saudi emirati qatari kuwaiti omani bahraini jordanian lebanese syrian iraqi iranian israeli
palestinian yemeni""".split())

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
    Exchange'), acronyms ('ASF'), single names ('Yassir'). Casing as written (first time
    seen), possessive stripped; compare with named_in(), which ignores case.
    A sentence-initial word ('Capital', 'State-backed' in a table cell) only counts if it is
    an acronym or appears capitalized mid-sentence in the text or `context` (e.g. the page)."""
    names = _mid_sentence_caps(text) | _mid_sentence_caps(context)
    out, run = [], []

    def end_run():
        if (run and " ".join(run).lower() not in {o.lower() for o in out}
                and not all(w.lower() in DEMONYMS for w in run)):
            out.append(" ".join(run))
        run.clear()

    for word, possessive, start in _tokens(text):
        low = word.lower()
        acronym = sum(ch.isupper() for ch in word) >= 2
        initial_ok = not start or (low not in COMMON and (acronym or low in names))
        if word[:1].isupper() and len(word) > 1 and low not in GENERIC and initial_ok:
            run.append(word)
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


# Countries and their adjectives / demonyms, English and French: a claim naming a country is
# satisfied by a passage using its adjective and vice versa ("Algérie" = "Algerian market").
# One row per country: English names | English adjectives/demonyms | French names | French
# adjectives (masculine singular; feminine and plurals are derived by fr_forms). Plural
# English forms get an "s" added automatically. A form starting with "=" is matched with its
# exact case only ("US", "EAU": as lowercase words they are "us" and "eau", water).
COUNTRY_ROWS = """
Algeria | Algerian | Algérie | algérien
Angola | Angolan | Angola | angolais
Benin | Beninese | Bénin | béninois
Botswana | Motswana, Batswana, Botswanan | Botswana | botswanais
Burkina Faso | Burkinabe, Burkinabè | Burkina Faso | burkinabè, burkinabé
Burundi | Burundian | Burundi | burundais
Cameroon | Cameroonian | Cameroun | camerounais
Cape Verde, Cabo Verde | Cape Verdean, Cabo Verdean | Cap-Vert, Cabo Verde | cap-verdien
Central African Republic, =CAR | Central African | République centrafricaine, Centrafrique, =RCA | centrafricain
Chad | Chadian | Tchad | tchadien
Comoros | Comorian | Comores | comorien
Republic of the Congo, Congo-Brazzaville, Congo | Congolese | République du Congo, Congo-Brazzaville, Congo | congolais
Democratic Republic of the Congo, DR Congo, =DRC, Congo-Kinshasa | Congolese | République démocratique du Congo, RD Congo, =RDC, Congo-Kinshasa | congolais
Djibouti | Djiboutian | Djibouti | djiboutien
Egypt | Egyptian | Égypte | égyptien
Equatorial Guinea | Equatoguinean, Equatorial Guinean | Guinée équatoriale | équato-guinéen
Eritrea | Eritrean | Érythrée | érythréen
Eswatini, Swaziland | Swazi, Emaswati | Eswatini, Swaziland | swazi
Ethiopia | Ethiopian | Éthiopie | éthiopien
Gabon | Gabonese | Gabon | gabonais
Gambia, The Gambia | Gambian | Gambie | gambien
Ghana | Ghanaian | Ghana | ghanéen
Guinea | Guinean | Guinée | guinéen
Guinea-Bissau | Bissau-Guinean | Guinée-Bissau | bissau-guinéen
Ivory Coast, Côte d'Ivoire | Ivorian | Côte d'Ivoire | ivoirien
Kenya | Kenyan | Kenya | kényan, kenyan
Lesotho | Basotho, Mosotho, Lesothan | Lesotho | lesothan
Liberia | Liberian | Liberia, Libéria | libérien
Libya | Libyan | Libye | libyen
Madagascar | Malagasy, Madagascan | Madagascar | malgache
Malawi | Malawian | Malawi | malawite, malawien
Mali | Malian | Mali | malien
Mauritania | Mauritanian | Mauritanie | mauritanien
Mauritius | Mauritian | Maurice, île Maurice | mauricien
Morocco | Moroccan | Maroc | marocain
Mozambique | Mozambican | Mozambique | mozambicain
Namibia | Namibian | Namibie | namibien
Niger | Nigerien | Niger | nigérien
Nigeria | Nigerian | Nigeria, Nigéria | nigérian
Rwanda | Rwandan | Rwanda | rwandais
São Tomé and Príncipe | Santomean, São Toméan | Sao Tomé-et-Principe | santoméen
Senegal | Senegalese | Sénégal | sénégalais
Seychelles | Seychellois | Seychelles | seychellois
Sierra Leone | Sierra Leonean | Sierra Leone | sierraléonais, sierra-léonais
Somalia | Somali, Somalian | Somalie | somalien
South Africa | South African | Afrique du Sud | sud-africain
South Sudan | South Sudanese | Soudan du Sud | sud-soudanais
Sudan | Sudanese | Soudan | soudanais
Tanzania | Tanzanian | Tanzanie | tanzanien
Togo | Togolese | Togo | togolais
Tunisia | Tunisian | Tunisie | tunisien
Uganda | Ugandan | Ouganda | ougandais
Zambia | Zambian | Zambie | zambien
Zimbabwe | Zimbabwean | Zimbabwe | zimbabwéen
France | French, Frenchman, Frenchmen, Frenchwoman, Frenchwomen | France | français
Spain | Spanish, Spaniard | Espagne | espagnol
Italy | Italian | Italie | italien
Germany | German | Allemagne | allemand
United Kingdom, =UK, =U.K., Britain, Great Britain | British, Briton | Royaume-Uni, Grande-Bretagne | britannique
United States, United States of America, =US, =U.S., =USA, =U.S.A. | American | États-Unis, États-Unis d'Amérique | américain
China | Chinese | Chine | chinois
India | Indian | Inde | indien
Turkey, Türkiye | Turkish, Turk | Turquie | turc, turque, turcs, turques
Saudi Arabia, =KSA | Saudi, Saudi Arabian | Arabie saoudite | saoudien
United Arab Emirates, =UAE, =U.A.E., Emirates | Emirati | Émirats arabes unis, =EAU, Émirats | émirien, émirati
Qatar | Qatari | Qatar | qatari, qatarien
Brazil | Brazilian | Brésil | brésilien
Japan | Japanese | Japon | japonais
South Korea, Korea, Republic of Korea | South Korean, Korean | Corée du Sud, Corée | sud-coréen, coréen
North Korea, =DPRK, Democratic People's Republic of Korea | North Korean | Corée du Nord, République populaire démocratique de Corée | nord-coréen
Papua New Guinea, =PNG | Papua New Guinean | Papouasie-Nouvelle-Guinée | papouan-néo-guinéen
Russia, Russian Federation | Russian | Russie, Fédération de Russie | russe
"""


def fr_forms(adj):
    """A French adjective's four forms from its masculine singular ("algérien" -> algérien,
    algérienne, algériens, algériennes)."""
    if adj.endswith("en"):
        return [adj, adj + "ne", adj + "s", adj + "nes"]
    if adj.endswith("s"):
        return [adj, adj + "e", adj + "es"]
    if adj.endswith("e"):
        return [adj, adj + "s"]
    return [adj, adj + "e", adj + "s", adj + "es"]


def _country_key(text):
    """Folded, hyphens/apostrophes as spaces: 'Côte d'Ivoire' -> 'cote d ivoire'."""
    return " ".join(re.sub(r"[\-'’.]", " ", fold(text)).split())


# North Korea and Papua New Guinea are listed so that "North Korea" and "Papua New Guinea"
# are read as themselves, never as Korea or Guinea.
FOLDED_FORMS, EXACT_FORMS = {}, {}     # form -> {row numbers of the countries it can mean}
for i, row in enumerate(COUNTRY_ROWS.strip().split("\n")):
    en, en_adj, fr, fr_adj = ([x.strip() for x in col.split(",")] for col in row.split("|"))
    forms = en + fr + en_adj + [a + "s" for a in en_adj if not a.endswith("s")]
    forms += [f for a in fr_adj for f in fr_forms(a)]
    for f in forms:
        if f.startswith("="):
            EXACT_FORMS.setdefault(f[1:], set()).add(i)
        else:
            FOLDED_FORMS.setdefault(_country_key(f), set()).add(i)
# Longest form first, so at each position the regex takes the longest name: "South Sudan"
# before "Sudan", "Guinée équatoriale" before "Guinée", "DR Congo" before "Congo".
FOLDED_RE = re.compile(r"(?<![a-z0-9])(?:" + "|".join(
    re.escape(f) for f in sorted(FOLDED_FORMS, key=len, reverse=True)) + r")(?![a-z0-9])")
EXACT_RE = re.compile(r"(?<![\w.])(?:" + "|".join(
    re.escape(f) for f in sorted(EXACT_FORMS, key=len, reverse=True)) + r")(?!\w)")
# Single-word English and French adjectives are demonyms too (never a name on their own).
for row in COUNTRY_ROWS.strip().split("\n"):
    cols = [[x.strip().lower() for x in col.split(",")] for col in row.split("|")]
    for w in cols[1] + [a + "s" for a in cols[1]] + [f for a in cols[3] for f in fr_forms(a)]:
        if " " not in w:
            DEMONYMS |= {w, fold(w)}


def countries_of(entity):
    """The countries (row numbers) a name can mean, or None if it names no country:
    'Algérie' -> {Algeria}; 'Congolese' -> both Congos."""
    return EXACT_FORMS.get(entity) or FOLDED_FORMS.get(_country_key(entity))


def country_named(countries, passage):
    """True if the passage names one of these countries unambiguously. Each country name in
    the passage is read whole (the longest form at its position: "South Sudan", not "Sudan")
    and counts only if every country it can mean is one of these: "Congolese" doesn't
    confirm "DR Congo" (it may be the other Congo). When unsure, the name check fails."""
    seen = [FOLDED_FORMS[m.group()] for m in FOLDED_RE.finditer(_country_key(passage))]
    seen += [EXACT_FORMS[m.group()] for m in EXACT_RE.finditer(passage)]
    return any(meant <= countries for meant in seen)


def names_country(text):
    """True if the text names a country, by name or adjective, English or French."""
    return bool(FOLDED_RE.search(_country_key(text)) or EXACT_RE.search(text))


# Small words skipped when reading an acronym off a name ("Office National des Statistiques").
CONNECTORS = {"of", "for", "and", "the", "de", "des", "du", "la", "le", "et", "d", "l", "&"}


def spelled_out(acronym, passage):
    """True if the passage has a run of capitalized words whose initials spell the acronym
    ('ASF' = 'Algerian Startup Fund'; connectors like 'of' and 'des' are skipped)."""
    want, run = acronym.lower(), ""
    for w in re.findall(r"[^\W\d_][\w\-]*|&", passage):
        if w.lower() in CONNECTORS and run:
            continue
        run = run + w[0].lower() if w[0].isupper() else ""
        if run.endswith(want):
            return True
    return False


def named_in(entity, passage):
    """True if every word of the name (3+ letters) appears in the passage, ignoring case
    and accents. An acronym also counts as named if the passage spells it out. A country
    counts as named by any of its forms, English or French ("Algérie" by "Algerian market",
    "Morocco" by "marocaine"), and only by a name meaning that country alone ("Sudan" is not
    in "South Sudan", "DR Congo" not in "Congolese"; see country_named)."""
    if (countries := countries_of(entity)) is not None:
        return country_named(countries, passage)
    if any(re.search(r"(?<![\w.])" + re.escape(x) + r"(?!\w)", passage)
           for x in ACRONYM_EQUIV.get(entity, ())):
        return True
    if entity.isupper() and " " not in entity and len(entity) >= 2:
        expansions = ACRONYMS.get(entity.lower(), [])
        if any(fold(x) in fold(passage) for x in expansions) or spelled_out(entity, passage):
            return True

    entity, p = fold(entity), fold(passage)
    words = [w for w in entity.split() if len(w) >= 3] or entity.split()
    return all(any(re.search(r"(?<![a-z0-9])" + re.escape(f), p) for f in _stems(w)) for w in words)


# A fact that opens like this leaves its subject implicit: it is the claim's lead name.
IMPLICIT_SUBJECT = re.compile(
    r"^\W*(it|its|they|their|this|these|he|she|his|her|the (company|startup|firm|platform|"
    r"fund|group|business|app|venture|project|program|programme|deal|round|ipo|listing))\b", re.I)


def fact_entities(fact, claim_ents):
    """The claim's names this fact is about: those written in the fact itself, plus the
    claim's lead name (its subject) when the fact opens with 'It'/'The company'. Names from
    elsewhere in the claim are not required ('grown by 40%' needs no 'PV')."""
    own = [e for e in claim_ents if named_in(e, fact)]
    lead = claim_ents[:1]
    if lead and IMPLICIT_SUBJECT.match(fact) and lead[0] not in own:
        own = lead + own
    return own


def paragraph_of(quote, page, on_page):
    """The page paragraph (line) the quote comes from, or None: then the quote is unverified,
    and no check may run against the model's own text instead. on_page may return the line
    itself (quote_check.quote_on_page): then it is used as is."""
    hit = on_page(quote, page)
    if isinstance(hit, str) or not hit:
        return hit or None
    for para in page.split("\n"):
        if para.strip() and on_page(quote, para):
            return para
    return None


def publisher(entity, url):
    """True if the name is the source's own (UpGrowth on upgrowth.dz): pages rarely name
    themselves."""
    host = (urlparse(url).hostname or "").lower().replace("-", "")
    entity = entity.lower()
    first = entity.split()[0]
    return bool(host) and (entity.replace(" ", "").replace("-", "") in host
                           or (len(first) >= 4 and first in host))


# Attribution: "According to ARPCE, ...", "The Ministry of Post and Telecommunications says
# ...", "selon l'ONS". A page published by that organisation rarely names itself, so on its
# own site (domain, or page title) the attribution's name counts as named; no other name does.
ATTRIBUTION_LEAD = [("according", "to"), ("selon",), ("d'après",), ("d’après",)]
ATTRIBUTION_VERBS = set("""says said reports reported estimates estimated states stated notes noted
indicates indicated shows showed counts counted announced announces puts put finds found
recorded records indique indiquait affirme annonce estime rapporte recense compte publie
précise""".split())
ARTICLES = {"the", "la", "le", "les", "l'", "l’"}
WORD = re.compile(r"[\w'’\-&]+|[^\w\s]")      # words; punctuation ends a name
NOT_NAMES = ARTICLES | {"this", "these", "that", "those", "it", "its", "they", "their", "he", "she"}


def _capital(w):
    return w[:1].isupper() and w.lower() not in NOT_NAMES


def attributions(claim):
    """The organisations a claim attributes its statement to, as written: "ARPCE",
    "Ministry of Post and Telecommunications" (connectors kept between capitalized words)."""
    # "l'ONS" -> "ONS" (an elided article before a name; "d'après" stays), "IMF's" -> "IMF"
    words = [POSSESSIVE.sub("", re.sub(r"^[lLdD]['’](?=[A-ZÀ-Þ])", "", w)) for w in WORD.findall(claim)]
    low = [w.lower() for w in words]
    out = []

    def name(run):
        while run and run[0].lower() in CONNECTORS | ARTICLES:
            run = run[1:]
        while run and run[-1].lower() in CONNECTORS:
            run = run[:-1]
        if run and any(_capital(w) for w in run):
            out.append(" ".join(run))

    for i in range(len(words)):
        for lead in ATTRIBUTION_LEAD:
            if tuple(low[i:i + len(lead)]) != lead:
                continue
            j = i + len(lead)
            if j < len(words) and low[j] in ARTICLES:
                j += 1
            run = []
            while j < len(words) and (_capital(words[j]) or (
                    low[j] in CONNECTORS and j + 1 < len(words) and _capital(words[j + 1]))):
                run.append(words[j])
                j += 1
            name(run)
        if low[i] in ATTRIBUTION_VERBS:
            j, run = i - 1, []
            while j >= 0 and (_capital(words[j]) or (
                    low[j] in CONNECTORS and j > 0 and _capital(words[j - 1]))):
                run.insert(0, words[j])
                j -= 1
            name(run)
    return list(dict.fromkeys(out))


def initials(org):
    """'Ministry of Post and Telecommunications' -> 'mpt'; an acronym is itself."""
    ws = [w for w in org.split() if w.lower() not in CONNECTORS]
    return org.lower() if len(ws) == 1 else "".join(w[0].lower() for w in ws)


def site_of(org, url, title=""):
    """True if the page is published by this organisation: its registrable name or acronym in
    the URL's host ("arpce.dz", "mpt.gov.dz" for the Ministry of Post and Telecommunications),
    or its name / acronym in the page title."""
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    labels = host.split(".")
    key = re.sub(r"[^a-z0-9]", "", fold(org))
    acr = initials(org)
    if host and (key in host.replace("-", "").replace(".", "") or (len(acr) >= 2 and acr in labels)):
        return True
    if title and (named_in(org, title) or (len(acr) >= 2 and (
            re.search(r"(?<!\w)" + re.escape(acr) + r"(?!\w)", title, re.I) or spelled_out(acr, title)))):
        return True
    return False


def attributed_to_site(entity, claim, url, title=""):
    """True if the entity is (part of) a name the claim attributes its statement to and the
    cited page is that organisation's own: "Ministry" in "The Ministry of Post and
    Telecommunications says ..." cited to mpt.gov.dz. Any other name in the claim still needs
    to be in the passage."""
    e = fold(entity)
    return any(re.search(r"(?<![a-z0-9])" + re.escape(e) + r"(?![a-z0-9])", fold(org))
               and site_of(org, url, title) for org in attributions(claim))


def opening_name(text, page):
    """The name a sentence or paragraph opens with (its subject), if it opens with one."""
    if _is_heading(text):
        return None
    first = next(_tokens(text), None)
    ents = entities(text, page)
    return ents[0] if first and ents and ents[0].split()[0].lower() == first[0].lower() else None


def sentence_before(quote, para):
    """The sentence just before the quote in its paragraph ('it' in a quote refers there)."""
    i = para.lower().find(quote.lower()[:40])
    head = para[:i] if i > 0 else ""
    parts = re.split(r"(?<=[.!?])\s+", head.strip())
    return parts[-1] if parts and parts[-1] else ""


def check_fact(fact, quote, claim, page, on_page, url="", title=""):
    """None if every name the fact is about is in its quote, the quote's paragraph, or is
    the page's own subject (named in 2+ paragraphs), or the organisation the claim attributes
    it to when the page is that organisation's (attributed_to_site; title: the page title).
    Otherwise ("missing", names, None), or
    ("contradicted", names, other) when the paragraph, the quote or the sentence before the
    quote opens with a different name the claim never mentions: it is about someone else."""
    claim_ents = entities(claim, page)
    need = [e for e in fact_entities(fact, claim_ents)
            if not publisher(e, url) and not attributed_to_site(e, claim, url, title)]
    para = paragraph_of(quote, page, on_page)
    if para is None:             # unverified quote: nothing here supports any name
        return ("missing", need, None) if need else None
    absent = [e for e in need if not named_in(e, quote) and not named_in(e, para)]
    if not absent:
        return None
    # "About someone else" never when the fact's subject (its first name) is there: if BYD
    # is in the passage, a sentence before it opening with "Tesla" doesn't make it Tesla's.
    subject_here = need[0] not in absent
    for text in () if subject_here else (para, quote, sentence_before(quote, para)):
        other = opening_name(text, page)
        if other and not publisher(other, url) and not any(
                named_in(c, other) or named_in(other, c) for c in claim_ents):
            return ("contradicted", absent, other)
    paras = [p for p in page.split("\n") if p.strip()]
    absent = [e for e in absent if sum(named_in(e, p) for p in paras) < 2]
    return ("missing", absent, None) if absent else None
