"""Token-free checks of the code-only verdict checks: unit-scaled numbers and the name check.
Run: .venv/bin/python test_checks.py"""
from entities import check_fact, entities
from quote_check import judge, missing_numbers, numbers_not_in_passage, quote_on_page
from quote_check import own_text as QC_own

# 1. Unit-scaled numbers. A claim number matches a page number in the same unit family that
#    converts to it at the claim's precision (rounded or cut off); never a unitless number.
def found(claim, passage):
    return missing_numbers(claim, passage) == []

assert found("Installed capacity reached 15.9 GW.", "capacity of 15,925 MW in 2024")
assert found("Installed capacity reached 15.9 GW.", "capacity of 15,925 megawatts (MW) in 2024")
assert found("Morocco added 3.2 GW of wind.", "wind capacity of 3,267 MW")
assert found("The plan costs $1.2 billion.", "a budget of 1,200 million dollars")
assert found("Capacity is 15,925 MW (15.9 GW).", "capacity of 15,925 megawatts")
assert found("Capacity is about 16 GW.", "capacity of 15,925 MW")
assert found("Output was 12.4 TWh.", "generation of 12,400 GWh")
assert found("The fund holds $50k.", "holds 50 thousand dollars")
assert not found("Capacity is about 17 GW.", "capacity of 15,925 MW")
assert not found("Installed capacity reached 15.9 GW.", "capacity of 15,925 kW")
assert not found("Costs fell 15.9%.", "capacity of 15,925 MW")
assert not found("The index rose to 15.9.", "capacity of 15,925 MW")          # no unit: never scaled
assert not found("Installed capacity reached 15.9 GW.", "generation of 15,925 MWh")  # power != energy
assert not found("Capacity reached 15.9 GW.", "15925 people visited")
assert missing_numbers("Costs fell 15.9% while capacity hit 15.9 GW.", "15,925 MW") == ["15.9"]
# The fact-level key-term check uses the same rule on the quote's paragraph.
page = "Morocco's renewable capacity reached 15,925 megawatts (MW) at the end of 2024.\nOther text."
q = "Morocco's renewable capacity reached 15,925 megawatts (MW) at the end of 2024."
assert numbers_not_in_passage("Morocco's renewable capacity is 15.9 GW", q, page) == []
assert numbers_not_in_passage("Morocco's renewable capacity is 17 GW", q, page) == ["17"]

# 2. Name check. (a) A fact only needs the names in its own text: "PV" elsewhere in the
#    claim is not required for "grown by more than 40%". (b) PV is a technical acronym, not a
#    name. (c) Reasons keep the original casing.
claim3 = ("Renewable electricity generation has grown by more than 40% over the past decade, "
          "driven mainly by wind, solar PV, and solar thermal")
page3 = ("Over the past decade, renewable electricity in North Africa has grown more than 40%, "
         "driven by the rapid expansion of wind, solar photovoltaic and solar thermal.")
assert entities(claim3) == []
for fact in ("Renewable electricity generation has grown by more than 40% over the past decade",
             "grown by more than 40% over the past decade",
             "The growth was driven mainly by wind, solar PV, and solar thermal"):
    assert check_fact(fact, page3, claim3, page3, quote_on_page) is None, fact
r = judge({"parts": [{"text": "Renewable electricity generation has grown by more than 40% over the past decade",
                      "kind": "fact", "status": "stated", "quote": page3},
                     {"text": "driven mainly by wind, solar PV, and solar thermal",
                      "kind": "fact", "status": "stated", "quote": page3}]}, claim3, page3)
assert r["label"] == "SOURCED", r

# Acronyms that are names: accepted when the passage spells them out, kept in original case.
assert entities("Funded by the ASF and VOLZ.") == ["ASF", "VOLZ"]
assert check_fact("The ASF backed 40 startups", "The Algerian Startup Fund backed 40 startups.",
                  "The ASF backed 40 startups.", "The Algerian Startup Fund backed 40 startups.",
                  quote_on_page) is None
# A different agency is not the same name: IRENA vs IEA must still fail.
irena_page = "The International Energy Agency (IEA) reports 15,925 MW of capacity.\nOther text."
irena_quote = "The International Energy Agency (IEA) reports 15,925 MW of capacity."
hit = check_fact("IRENA reports 15.9 GW of capacity", irena_quote, "IRENA reports 15.9 GW of capacity.",
                 irena_page, quote_on_page)
assert hit and hit[1] == ["IRENA"], hit

# Claim 26 regression (report2): Moustachir's IPO credited to VOLZ must stay contradicted.
claim26 = ("VOLZ — Algiers Stock Exchange listing: The company was reported as the first Algerian "
           "startup to list on the Algiers Stock Exchange. Its IPO raised approximately DZD 94 "
           "million—about $724,000—and was reportedly oversubscribed by 119%.")
page26 = "\n".join([
    "8. Volz — The First ASF Exit",
    "Founded in 2022, Volz closed a $5 million Series A round in December 2025 and became the "
    "first company the Algerian Startup Fund exited.",
    "10. Moustachir — The Stock Exchange Pioneer",
    "Moustachir operates an electronic consulting platform. Its significance in 2026 is "
    "structural rather than operational: it was the first Algerian startup to list on the "
    "Algiers Stock Exchange, with its IPO oversubscribed by 119% and raising approximately 94 "
    "million DZD (roughly $724,000).",
    "The cohort above spans four funding brackets: Series A/B (Yassir, Volz, LabLabee, Temtem), "
    "and public market (Moustachir)."])
q26 = ("it was the first Algerian startup to list on the Algiers Stock Exchange, with its IPO "
       "oversubscribed by 119% and raising approximately 94 million DZD (roughly $724,000).")
for fact in ("VOLZ was the first Algerian startup to list on the Algiers Stock Exchange",
             "It was the first Algerian startup to list on the Algiers Stock Exchange",
             "VOLZ's IPO was oversubscribed by 119%"):
    hit = check_fact(fact, q26, claim26, page26, quote_on_page,
                     "https://algeriatech.news/algeria-10-startups-to-watch-2026-sectors-profiles/")
    assert hit == ("contradicted", ["VOLZ"], "Moustachir"), (fact, hit)
r = judge({"parts": [{"text": "VOLZ's IPO was oversubscribed by 119%", "kind": "fact",
                      "status": "stated", "quote": q26}]}, claim26, page26)
# A1: the code's name check alone never accuses: amber, with its reason kept.
assert r["label"] == "COULDN'T CONFIRM" and "about Moustachir, not VOLZ" in r["reason"], r
assert r["facts"][0]["status"] == "unconfirmed"
# As in the saved report2 run, the model itself said "contradicted" (the passage is about
# Moustachir) but the quote has the claim's own figures: not CONTRADICTED (no conflicting
# value), still red: UNSUPPORTED. No page line names VOLZ with those figures (no fallback).
r = judge({"parts": [{"text": "VOLZ's IPO raised approximately DZD 94 million (about $724,000)", "kind": "fact",
                      "status": "contradicted", "quote": q26},
                     {"text": "VOLZ's IPO was oversubscribed by 119%", "kind": "fact",
                      "status": "contradicted", "quote": q26}]}, claim26, page26)
assert r["label"] == "UNSUPPORTED" and {f["status"] for f in r["facts"]} == {"missing"}, r

# 3. Passage selection: paragraphs holding the claim's anchors (titles in quotes/italics,
#    organisations/acronyms, numbers) are always sent, within MAX_EXCERPT_CHARS. Report3
#    claim 2: the attribution sentence sits in a different paragraph from the figure, and
#    keyword-heavy filler paragraphs used to crowd it out.
from quote_check import MAX_EXCERPT_CHARS, anchors, best_excerpts
claim2 = ("Installed renewable capacity reached 15,925 MW (15.9 GW) in 2025, according to an "
          "analysis of IRENA\u2019s *Renewable Capacity Statistics 2026*.")
filler = [f"In 2025 the installed renewable capacity of country {i} reached new highs as renewable "
          f"capacity installed by developers grew and installed solar capacity reached records, "
          f"according to an analysis of national statistics on renewable capacity additions. "
          * 2 for i in range(12)]
figure = "North Africa\u2019s installed renewable capacity reached 15,925 megawatts at the end of the year."
attribution = ("The figures come from an analysis of IRENA\u2019s \u2018Renewable Capacity Statistics "
               "2026\u2019 report, published in March.")
page2 = "\n".join(filler[:6] + [figure] + filler[6:] + [attribution])
assert ("title", "renewable capacity statistics 2026") in anchors(claim2, page2)
assert ("name", "IRENA") in anchors(claim2, page2)
ex = best_excerpts(claim2, page2)
assert attribution in ex and figure in ex, [e[:40] for e in ex]
assert sum(map(len, ex)) <= MAX_EXCERPT_CHARS
# Without anchors (the old rule: keyword overlap, best first, while it fits) both are lost.
from quote_check import keywords
kw = keywords(claim2)
old, total = [], 0
for p in sorted(page2.split("\n"), key=lambda p: len(kw & keywords(p)), reverse=True):
    if total + len(p) <= MAX_EXCERPT_CHARS:
        old.append(p); total += len(p)
assert attribution not in old and figure not in old
# The apostrophe in IRENA's is not a quote; straight and underscore titles are titles.
assert [a for a in anchors("IRENA's data and 'Energy Outlook 2030' plus _World Energy Review_ say 12%.", "")
        if a[0] == "title"] == [("title", "energy outlook 2030"), ("title", "world energy review")]

# 4. Locale number formats (locnum.py): any reading of a page number may equal the claim's.
from decimal import Decimal as D
import locnum
for claim, passage in (("2,585,187 cars were sold", "Sales: 2 585 187 cars"),
                       ("a 29.7% increase", "une hausse de 29,7%"),
                       ("1,992,803 in 2024", "1\u202f992\u202f803 en 2024"),
                       ("1,992,803 in 2024", "1\u00a0992\u00a0803 en 2024"),
                       ("1,992,803 in 2024", "1\u2009992\u2009803 en 2024"),
                       ("545,142 EVs", "545.142 Elektroautos, +43,2%"),   # "43,2": the page's convention
                       ("2,585,187 cars", "2'585'187 Autos"),
                       ("2,585,187 cars", "2\u2019585\u2019187 Autos"),
                       ("60,651 EVs", "Austria 60,651"),
                       ("Norway grew 50.6%", "Norwegen 50,6%"),
                       ("1,234.5 units", "1.234,5 Einheiten"),
                       ("2,585,187 EVs, 29.7% more", "In 2025 2 585 187 EVs, +29,7%")):
    assert found(claim, passage), (claim, passage)
for claim, passage in (("a 29.7% increase", "une hausse de 27,9%"),
                       ("2,585,187 cars", "2 585 178 cars"),
                       ("Norway grew 50.6%", "5,06%"),
                       ("2,585,187 cars", "2585 187 cars")):          # 4-digit first group: not one number
    assert not found(claim, passage), (claim, passage)
# A year followed by a number is two numbers, never 20252585187 or 2025258.
toks = [(m.group(), locnum.readings(m, split=True)) for m in locnum.NUMBER_RE.finditer("In 2025 2 585 187 cars")]
assert [t for t, _ in toks] == ["2025", "2 585 187"], toks
assert D(20252585187) not in locnum.values("In 2025 2 585 187 cars") and D(2025258) not in locnum.values("In 2025 2 585 187 cars")
# Ambiguous tokens keep both readings; lists stay separate numbers.
assert locnum.values("1,234 / 0,5") == {D(1234), D("1.234"), D("0.5")}
assert locnum.values("545.142 / 0,5") == {D(545142), D("545.142"), D("0.5")}
assert locnum.values("10, 20, 30") == {D(10), D(20), D(30)}
assert [m.group() for m in locnum.NUMBER_RE.finditer("10,20,30 and 1,5,7")] == ["10,20", "30", "1,5", "7"]
# Reasons name the number as the claim wrote it.
assert missing_numbers("Sales reached 2,585,187.", "Sales reached 2 585 178.") == ["2,585,187"]
# The per-fact check and the quote matcher read locale formats too.
pg = "Battery-electric sales reached 2 585 187 units in 2025, up 29,7% on 2024.\nOther."
qt = "Battery-electric sales reached 2 585 187 units in 2025, up 29,7% on 2024."
assert numbers_not_in_passage("2,585,187 BEVs were sold in 2025, up 29.7%", qt, pg) == []
assert quote_on_page("Battery-electric sales reached 2,585,187 units in 2025, up 29.7% on 2024.", pg)
assert not quote_on_page("Battery-electric sales reached 2,585,178 units in 2025, up 29.7% on 2024.", pg)
# Units with locale numbers: 15 925 MW (French) is 15.9 GW.
assert found("Capacity reached 15.9 GW.", "capacité de 15 925 MW")

# 5. rescore.py: a downloaded run is re-scored through the current judge() with zero tokens.
#    Report4 claim 1 as production judged it before locale numbers: the model said "stated",
#    the number check demoted it ("2585187 not in its passage") -> UNSUPPORTED. Now SOURCED.
import json as _json, os as _os, subprocess, sys as _sys, tempfile as _tf
url4 = "https://eleport.com/ev-sales-in-europe/"
page4 = ("EV sales in Europe\nIn 2025, 2 585 187 battery-electric cars were sold in Europe (EU, EFTA "
         "and the UK), a rise of 29,7% from 1 992 803 in 2024.\nOther text about charging.")
quote4 = ("In 2025, 2 585 187 battery-electric cars were sold in Europe (EU, EFTA and the UK), a rise "
          "of 29,7% from 1 992 803 in 2024.")
claim4 = ("Total EV Sales: 2,585,187 battery-electric vehicles were sold across Europe (EU, EFTA, and "
          "the UK) in 2025")
model4 = {"opinion": False, "parts": [{"text": "2,585,187 battery-electric vehicles were sold across "
          "Europe (EU, EFTA, and the UK) in 2025", "kind": "fact", "status": "stated", "quote": quote4}]}
assert judge(model4, claim4, page4, url4)["label"] == "SOURCED"
run4 = {"format": "touchstone-run", "version": 1, "report": claim4, "claims": [
    {"claim": 1, "text": claim4, "url": url4, "label": "UNSUPPORTED", "model": model4,
     "facts": [{"fact": model4["parts"][0]["text"], "status": "missing", "quote": "",
                "unmatched_quote": quote4, "note": "Quote found, but 2585187 not in its passage."}]},
    {"claim": 2, "text": "Unreachable one", "url": "https://x.invalid/", "label": "SOURCE UNREACHABLE"}],
    "not_checked": [], "uncited": []}
with _tf.TemporaryDirectory() as d:
    run_path, cache = _os.path.join(d, "run.json"), _os.path.join(d, "r4.pages.json")
    _json.dump(run4, open(run_path, "w"))
    _json.dump([{"url": url4, "status": "OK", "text": page4}, {"url": "https://x.invalid/", "status": "ERROR"}],
               open(cache, "w"))
    labels_path = _os.path.join(d, "labels.json")
    _json.dump([{"claim": 1, "label": "SOURCED"}], open(labels_path, "w"))
    out = subprocess.run([_sys.executable, "rescore.py", run_path, "--cache", cache, "--labels", labels_path],
                         capture_output=True, text=True, check=True).stdout
assert "[ 1] UNSUPPORTED        -> SOURCED" in out, out
assert "1 label(s) changed out of 2." in out and "old 0/1, new 1/1" in out, out
# Without the "model" field (older runs), the reply is rebuilt from the facts: same result.
import rescore
assert rescore.model_reply({k: v for k, v in run4["claims"][0].items() if k != "model"}) == model4

# 6. Linear time on hostile pages (security review, 2026-10-09): "number then unit" in one
#    regex backtracked through every digit group (8,000 groups took 28 s; pages go to 3 MB).
#    A page-long digit run must not overflow Decimal either.
import time as _time, units as _units
_t = _time.monotonic()
_units.quantities("1" + " 234" * 200_000 + " x", page=True)
missing_numbers("Capacity is 15.9 GW and 2,585,187 cars", "9" * 1_000_000 + " GW\n1" + ",234" * 100_000 + " MW")
assert _time.monotonic() - _t < 3, _time.monotonic() - _t

# 7. Rankings tied to a name are facts, not framing (report4 part 2, claim 5): the model said
#    "stated", the lexicon demoted it ("best" inside "best-selling", < 8 other words).
from quote_check import is_evaluative
claim5 = ("While exact percentage shares for every individual brand across the entire continent are "
          "highly fragmented, market positioning shifted dramatically among the top automakers: "
          "Volkswagen: Reclaimed the title as the #1 best-selling electric car brand in Europe for the full year")
page5 = ("2025 Full Year Europe: Electric Car Sales per Country\nElectric car sales in Europe grew in 2025."
         "\nIn 2025, Volkswagen was the largest carmaker and best-selling electric car brand.\nOther.")
r = judge({"opinion": False, "parts": [
    {"text": "Volkswagen was the best-selling electric car brand in Europe for the full year", "kind": "fact",
     "status": "stated", "quote": "Volkswagen was the largest carmaker and best-selling electric car brand."},
    {"text": "market positioning shifted dramatically among the top automakers", "kind": "framing",
     "status": "", "quote": ""},
    {"text": "reclaimed the title as the #1 best-selling electric car brand in Europe for the full year",
     "kind": "framing", "status": "", "quote": ""}]}, claim5, page5)
assert r["label"] == "PARTIAL" and r["framing"] == ["market positioning shifted dramatically among the top automakers"], r
assert not is_evaluative("Volkswagen was the best-selling brand", ["Volkswagen"])
assert not is_evaluative("Yassir is the #1 ride-hailing app", ["Yassir"])
assert is_evaluative("the largest local-currency round", ["Volz"])          # no name: colour
assert is_evaluative("Volz was a notable signal", ["Volz"])                  # no ranking: colour

# 8. Safeguards against harsh false flags (Gemini part 2b, 2026-10-09).
from quote_check import line_on_page, passages, value_conflict
P = lambda text, status, quote="", kind="fact": {"text": text, "kind": kind, "status": status, "quote": quote}
brands_url = "https://www.best-selling-cars.com/europe/2025-full-year-europe-best-selling-car-manufacturers-and-brands/"
brands = "\n".join([
    "Best-Selling Car Manufacturers in Europe in 2025 (Full Year)",
    "The best-selling car manufacturers in the European Union (EU), the UK, and EFTA countries in full-year 2025, according to the ACEA were:",
    "| R | Brand | Sales 2025 | Sales 2024 | % 25/24 |",
    "| 9 | Tesla | 238,656 | 326,525 | -26.9 |",
    "| 12 | BYD | 187,657 | 50,912 | 268.6 |",
    "Tesla was the worst-performing larger car brand in 2025, with sales down by 26.9%. BYD was the best-performing brand with sales up almost ten times more \u2014 +268.6%.",
    "Volkswagen and Toyota were again the two best-selling car brands in Europe in 2025."])
tesla = ("Tesla: Despite having the most popular individual car, Tesla struggled as a brand in 2025. Its total "
         "European vehicle sales plummeted by 26.9% to 238,656 total units")
byd = "BYD: Experienced massive explosive growth, with its total European sales rocketing by 268.6% to 187,657 units"
row_t, row_b = "| 9 | Tesla | 238,656 | 326,525 | -26.9 |", "| 12 | BYD | 187,657 | 50,912 | 268.6 |"
sent = "BYD was the best-performing brand with sales up almost ten times more \u2014 +268.6%."

# B3: a year only has to be on the page; the table row sits under "Sales 2025".
r = judge({"parts": [P("Tesla's total European sales fell 26.9% to 238,656 units in 2025", "stated", row_t),
                     P("Tesla had the most popular individual car", "missing"),
                     P("Tesla struggled as a brand", "", kind="framing")]}, tesla, brands, brands_url)
assert r["label"] == "PARTIAL" and [f["status"] for f in r["facts"]] == ["stated", "missing"], r
assert numbers_not_in_passage("Tesla sold 238,656 units in 2025", row_t, brands) == []
assert numbers_not_in_passage("Tesla sold 238,656 units in 2019", row_t, brands) == ["2019"]   # year not on page

# B2: "European" is not a name; BYD named in its passage is never "about Tesla", even though
# the paragraph opens with Tesla.
assert entities(byd, brands) == ["BYD"] and entities("Its European sales") == []
assert entities("The European Union fund") == ["European Union"]
assert check_fact("BYD's total European sales rose 268.6%", sent, byd, brands, quote_on_page, brands_url) is None
r = judge({"parts": [P("Experienced massive explosive growth", "", kind="framing"),
                     P("BYD's total European sales rose 268.6%", "stated", sent),
                     P("BYD sold 187,657 units", "stated", row_b)]}, byd, brands, brands_url)
assert r["label"] == "SOURCED", r

# A1: a code check alone never accuses. The model said stated with a verified quote; the
# number check disagrees (passage lacks 187,657) -> "couldn't confirm", amber, with the reason.
r = judge({"parts": [P("BYD's sales rose 268.6% to 187,657 units", "stated", sent)]},
          byd, brands.replace(row_b, "| 12 | BYD | x | y | z |"), brands_url)
assert r["label"] == "COULDN'T CONFIRM" and r["facts"][0]["status"] == "unconfirmed", r
assert "187,657 not in its passage" in r["facts"][0]["note"]
# CONTRADICTED needs the model's "contradicted" AND a conflicting figure in a verified quote.
assert value_conflict("Tesla sold 250,000 units", row_t) and not value_conflict("Tesla sold 238,656 units", row_t)
assert not value_conflict("Tesla sold cars in 2024", "Tesla sold cars in 2025")          # years aren't figures
r = judge({"parts": [P("Tesla sold 250,000 units", "contradicted", row_t)]}, tesla, brands, brands_url)
assert r["label"] == "CONTRADICTED", r
r = judge({"parts": [P("Tesla had the best year of any brand", "contradicted", row_t)]}, tesla, brands, brands_url)
assert r["label"] == "UNSUPPORTED" and "no conflicting figure" in r["reason"], r

# A2: a fact the model didn't find in the passages, whose figures (and subject) sit on one
# page line, is "possibly stated" with that line as evidence; never counted as not found.
r = judge({"parts": [P("BYD sold 187,657 units", "missing")]}, byd, brands, brands_url)
assert r["label"] == "COULDN'T CONFIRM" and r["facts"][0]["status"] == "possible", r
assert r["facts"][0]["evidence"] == row_b and "Possibly stated" in r["reason"]
assert line_on_page("BYD sold 187,657 units", brands, ["BYD"]) == row_b
assert line_on_page("Tesla sold 187,657 units", brands, ["Tesla"]) is None       # BYD's line, not Tesla's
assert line_on_page("Sales rose in 2025", brands, []) is None                     # only a year: no fallback
assert line_on_page("Sales of 268.6% growth", brands, []) is not None             # no subject: figures only
r = judge({"parts": [P("BYD sold 187,657 units", "stated", row_b), P("BYD sold 999,999 units", "missing")]},
          byd, brands, brands_url)
assert r["label"] == "PARTIAL" and r["facts"][1]["status"] == "missing", r       # not on any line: not found

# B1: short list items (under the old 30-char minimum) are kept, with their heading/lead-in,
# so "Tesla Model Y: 116,989 units" has its passage; a quote from the row still verifies.
top5 = "\n".join([
    "We looked into the best-selling EVs in early 2026.",
    "The top 5 most popular electric cars 2025 in Europe from 2025 January to October",
    "Here are the best electric cars sold in Europe so far, per Jos\u00e9 Pontes\u2019 research at CleanTechnica:",
    "- Tesla Model Y: 116 989", "- \u0160koda Elroq: 71 148", "- Renault 5 (including Alpine A290): 67 625",
    "- Volkswagen ID.4: 66 030", "- Volkswagen ID.3: 64 414",
    "Notably, the Tesla Model 3 has just about fallen off the top 5 list, with 62 629 sales.",
    "1. Tesla Model Y \u2013 still the benchmark", "- Fast", "2. \u0160koda Elroq"])
ps = passages(top5)
group = [p for p in ps if "- Tesla Model Y: 116 989" in p]
assert len(group) == 1 and group[0].startswith("The top 5 most popular electric cars 2025") and "- \u0160koda Elroq: 71 148" in group[0], ps
assert "- Renault 5 (including Alpine A290): 67 625" in ps                       # over 30 chars: alone, as before
assert not any(p.endswith("- Fast") or p == "2. \u0160koda Elroq" for p in ps)      # no number: still dropped
claim_y = "Top 5 Best-Selling EV Models in Europe (Recorded Jan\u2013Oct 2025): Tesla Model Y: 116,989 units"
assert any("Model Y: 116 989" in e for e in best_excerpts(claim_y, top5))
assert any("Elroq: 71 148" in e for e in best_excerpts("\u0160koda Elroq: 71,148 units", top5))
assert sum(map(len, best_excerpts(claim_y, top5))) <= MAX_EXCERPT_CHARS
# 2025 comes from the h2 above the list (eleport.com's real heading, fetched with the page).
meta5 = {"title": "The Most Popular Electric Cars In Europe 2025, Compared",
         "headings": [[1, "Five Most Popular Electric Cars in Europe 2025, Compared"],
                      [2, "The top 5 most popular electric cars 2025 in Europe from 2025 January to October"]]}
fact_y = P("Tesla Model Y sold 116,989 units in Europe from January to October 2025", "stated", "- Tesla Model Y: 116 989")
r = judge({"parts": [fact_y]}, claim_y, top5, meta=meta5)
assert r["facts"][0]["status"] == "stated", r
# Without its context marked, the claim's "Top 5" counts and is in no part: amber (L2).
assert r["label"] == "COULDN'T CONFIRM" and "leaves out 5" in r["reason"], r
# But "Top 5 ... (Recorded Jan-Oct 2025):" is the list's lead-in (blocks_ctx context): only
# the bullet's own text must be covered, so the 5 doesn't cap it.
from check_numbers import blocks_ctx
lead = "**Top 5 Best-Selling EV Models in Europe (Recorded Jan\u2013Oct 2025):**"
r4 = lead + "\n\n1. **Tesla Model Y:** 116,989 units ([Eleport](https://eleport.com/most-popular-electric-cars/))\n" \
     "3. **Renault 5:** 67,625 units ([Eleport](https://eleport.com/most-popular-electric-cars/))"
(t1, _, c1), (t3, _, c3) = blocks_ctx(r4)
assert t1 == claim_y and c1 == "Top 5 Best-Selling EV Models in Europe (Recorded Jan\u2013Oct 2025):", (t1, c1)
assert c3 == "" and t3 == "Renault 5: 67,625 units", (t3, c3)       # its own line, no lead-in
r = judge({"parts": [fact_y]}, claim_y, top5, meta=meta5, context=c1)
assert r["label"] == "SOURCED", r
# The year rule still sees the context: the fact's 2025 is dated by the page's heading.
r = judge({"parts": [fact_y]}, claim_y, top5, context=c1)
assert r["label"] == "COULDN'T CONFIRM" and "2025 not in its passage" in r["reason"], r
# A number in the bullet's OWN text is covered by a part OR a verified quote: "Renault 5"
# paraphrased to "Renault" is fine when the quote verifies "Renault 5 (...): 67 625".
fact_r = P("Renault sold 67,625 units", "stated", "- Renault 5 (including Alpine A290): 67 625")
r = judge({"parts": [fact_r]}, "Top 5 EV models: Renault 5: 67,625 units", top5, context="Top 5 EV models:")
assert r["label"] == "SOURCED", r
# In neither a part nor a verified quote: still capped.
r = judge({"parts": [P("Renault sold 67,625 units", "stated", "- Renault 5 (including Alpine A290): 67 625")]},
          "Top 5 EV models: Renault 7: 67,625 units", top5, context="Top 5 EV models:")
assert r["label"] == "COULDN'T CONFIRM" and "leaves out 7" in r["reason"], r
# An unverified quote covers nothing: the number must come from page text the checks accepted.
r = judge({"parts": [P("Renault sold 67,625 units", "stated", "Renault 7 sold 67,625 units in Europe this year.")]},
          "Top 5 EV models: Renault 7: 67,625 units", top5, context="Top 5 EV models:")
assert r["label"] != "SOURCED" and r["facts"][0].get("rejected_quote"), r
r = judge({"parts": [P("Renault 5 sold 67,625 units", "stated", fact_r["quote"])]},
          "Top 5 EV models: Renault 5: 67,625 units", top5, context="Top 5 EV models:")
assert r["label"] == "SOURCED", r
# A context that isn't the claim's prefix is ignored (whole claim counts).
assert QC_own("Top 5: X 1", "Other:") == "Top 5: X 1" and QC_own("Top 5: X 1", "Top 5:") == "X 1"
# Without title/headings (an old cache), the year can't be dated: amber, never red.
r = judge({"parts": [fact_y]}, claim_y, top5)
assert r["label"] == "COULDN'T CONFIRM" and "2025 not in its passage" in r["reason"], r
# If the replayed model reply predates B1 (it saw no list), A2 still finds the row.
r = judge({"parts": [P("Tesla Model Y sold 116,989 units", "missing")]}, claim_y, top5)
assert r["label"] == "COULDN'T CONFIRM" and r["facts"][0]["evidence"] == "- Tesla Model Y: 116 989", r

# 9. B3 tightened: a year counts only in the passage, the page title, the headings above the
#    passage, or the quoted row's table header/caption. Never footer/copyright text.
from quote_check import year_context
assert numbers_not_in_passage("Tesla sold 238,656 units in 2025", row_t, brands) == []        # table header
footer_page = ("Market report\nIn 2023, sales reached 412,000 units across the region.\n"
               "Other news.\n\u00a9 2026 Example Media. All rights reserved.")
q23 = "In 2023, sales reached 412,000 units across the region."
assert numbers_not_in_passage("Sales reached 412,000 units in 2026", q23, footer_page,
                              {"title": "Market report", "headings": []}) == ["2026"]
assert numbers_not_in_passage("Sales reached 412,000 units in 2026", q23, footer_page,
                              {"title": "Market report \u00a9 2026", "headings": []}) == ["2026"]  # copyright title
assert numbers_not_in_passage("Sales reached 412,000 units in 2026", q23, footer_page,
                              {"title": "Market report 2026", "headings": []}) == []               # title
# Headings: only those ABOVE the passage, and only the current section path.
hp = "Results 2024\nSales were 412,000 units.\nOutlook 2026\nMore text here about the outlook."
hm = {"title": "", "headings": [[2, "Results 2024"], [2, "Outlook 2026"]]}
assert numbers_not_in_passage("Sales were 412,000 units in 2024", "Sales were 412,000 units.", hp, hm) == []
assert numbers_not_in_passage("Sales were 412,000 units in 2026", "Sales were 412,000 units.", hp, hm) == ["2026"]
assert "Outlook 2026" not in year_context("Sales were 412,000 units.", hp, hm)
# A table's caption (the line just above it) dates its rows; a row elsewhere doesn't.
tp = "Sales in 2024 by brand\n| Brand | Units |\n| Tesla | 238,656 |\nUnrelated 2025 text."
assert numbers_not_in_passage("Tesla sold 238,656 units in 2024", "| Tesla | 238,656 |", tp) == []
assert numbers_not_in_passage("Tesla sold 238,656 units in 2025", "| Tesla | 238,656 |", tp) == ["2025"]

# 10. "Possibly stated" can never make a claim SOURCED: at best COULDN'T CONFIRM, whatever
#     the other facts are (even all stated).
for others in ([], [P("BYD's sales rose 268.6%", "stated", sent)],
               [P("BYD's sales rose 268.6%", "stated", sent), P("BYD sold 187,657 units", "stated", row_b)]):
    r = judge({"parts": others + [P("BYD sold 187,657 units", "missing")]}, byd, brands, brands_url)
    assert "possible" in [f["status"] for f in r["facts"]] and r["label"] == "COULDN'T CONFIRM", r

# 11. compare_runs.py: two runs of one report, claim by claim, with accuracy per run.
import compare_runs
with _tf.TemporaryDirectory() as d:
    a, b = _os.path.join(d, "a.json"), _os.path.join(d, "b.json")
    _json.dump({"provider": "groq", "claims": [{"claim": 1, "url": "u", "label": "UNSUPPORTED"},
                                              {"claim": 2, "url": "u", "label": "SOURCED"}]}, open(a, "w"))
    _json.dump({"provider": "gemini", "claims": [{"claim": 1, "url": "u", "label": "COULDN'T CONFIRM"},
                                                {"claim": 2, "url": "u", "label": "SOURCED"}]}, open(b, "w"))
    out = compare_runs.compare(a, b, {1: "PARTIAL", 2: "SOURCED"})
assert "<>" in out[1] and "<>" not in out[2] and "Same label on 1/2" in out[3], out
assert out[-2:] == ["Accuracy groq: 1/2", "Accuracy gemini: 2/2"], out

# 12. Review 2026-10-11, L1: a "..." quote verifies only inside ONE page line, pieces in
#     order; no check ever runs against the model's own text.
from entities import paragraph_of
stitch_page = ("Tesla's European registrations fell sharply in 2025 as its line-up aged.\n"
               "BYD sold 116,989 cars in Europe in 2025, nearly four times its 2024 total.")
stitched = "Tesla's European registrations fell sharply ... 116,989 cars in Europe"
assert not quote_on_page(stitched, stitch_page)
assert paragraph_of(stitched, stitch_page, quote_on_page) is None
r = judge({"parts": [P("Tesla sold 116,989 cars in Europe in 2025", "stated", stitched)]},
          "Tesla sold 116,989 cars in Europe in 2025.", stitch_page)
assert r["facts"][0]["status"] in ("missing", "possible") and r["label"] != "SOURCED", r
# Same pieces in one line still verify; out of order they don't.
assert quote_on_page("BYD sold 116,989 cars ... nearly four times its 2024 total", stitch_page)
assert not quote_on_page("nearly four times its 2024 total ... BYD sold 116,989 cars", stitch_page)
# A quote spanning two lines is not one passage either.
assert not quote_on_page("its line-up aged. BYD sold 116,989 cars in Europe", stitch_page)
# A short page line never matches inside a longer quote.
assert not quote_on_page("BYD sold 116,989 cars in Europe in 2025 and Tesla sold 90,000", "BYD sold 116,989 cars")
assert check_fact("In 2025 Tesla sold 116,989 cars", stitched, "In 2025 Tesla sold 116,989 cars.", stitch_page,
                  quote_on_page) == ("missing", ["Tesla"], None)
assert numbers_not_in_passage("Tesla sold 116,989 cars", stitched, stitch_page) == ["116,989"]

# 13. L4: the per-fact number check counts single digits ($5M vs $3M); units still convert.
m_page = "VOLZ raised $3 million in its seed round, led by local investors."
r = judge({"parts": [P("VOLZ raised $5 million", "stated", m_page)]}, "VOLZ raised $5 million.", m_page)
assert r["facts"][0]["status"] == "unconfirmed" and r["label"] != "SOURCED", r
assert numbers_not_in_passage("VOLZ raised $5 million", m_page, m_page) == ["5"]
assert numbers_not_in_passage("VOLZ raised $3 million", m_page, m_page) == []
gw_page = "The plant adds 3,000 MW of capacity to the grid by 2027."
assert numbers_not_in_passage("The plant adds 3 GW of capacity", gw_page, gw_page) == []
assert numbers_not_in_passage("The plant adds 4 GW of capacity", gw_page, gw_page) == ["4"]
assert missing_numbers("VOLZ raised $5 million.", m_page) == []     # page-wide: 2+ digits only
w_page = "The pool is structured as one billion dinars allocated per wilaya, three million for others."
assert numbers_not_in_passage("DZD 1 billion per wilaya", w_page, w_page) == []           # written out
assert numbers_not_in_passage("DZD 5 billion per wilaya", w_page, w_page) == ["5"]

# 14. L3: space groups split into separate numbers only on table-like lines, and never when a
#     group starts with 0. In prose "2 585 187" is one number.
assert missing_numbers("Model Y sold 585 units.", "Sales reached 2 585 187 cars in 2025.") == ["585"]
assert missing_numbers("It sold 23 units.", "| Total | 1 023 456 | 2025 |") == ["23"]
assert missing_numbers("It sold 23 units.", "Total 1 023 456 cars sold in 2025 here") == ["23"]
assert missing_numbers("It sold 200 units.", "| Q1 | 100 200 300 |") == []          # real row cells
assert missing_numbers("Robusta averaged 71 cents.", "Robusta 73 356 71 910 71 033") == []   # PDF row
assert missing_numbers("Tesla Model Y: 116,989 sold.", "| 1 | Tesla Model Y | 116 989 |") == []
assert missing_numbers("2,585,187 cars", "Sales: 2 585 187 cars") == []

# 15. L5: "2,500" is 2.5 and "545.142" is 545142 only on a page that writes numbers the
#     European way; elsewhere English readings only.
assert missing_numbers("Prices rose 2.5%.", "Volume reached 2,500 tonnes.") == ["2.5"]
assert missing_numbers("Prices rose 2.5%.", "Volume reached 2,500 tonnes, up 29,7%.") == []
assert missing_numbers("Sales were 545,142.", "Absatz: 545.142 Elektroautos") == ["545,142"]
assert missing_numbers("Sales were 545,142.", "Absatz: 545.142 Elektroautos.\nAnteil 20,1%") == []
assert missing_numbers("Sales were 1,234,567.", "Absatz: 1.234.567") == []           # unambiguous
assert missing_numbers("Share was 29.7%.", "une hausse de 29,7%") == []
assert locnum.european("29,7%") and locnum.european("1.234.567") and locnum.european("1.234,5")
assert not locnum.european("2,500 tonnes and 1,234,567 cars at 2.5%")
# The page's convention also governs the per-fact check of a paragraph.
eu_page = "Absatz 2025: 545.142 Elektroautos.\nMarktanteil 20,1% (Vorjahr 14,6%)."
assert numbers_not_in_passage("Germany sold 545,142 EVs", "Absatz 2025: 545.142 Elektroautos.", eu_page) == []
assert numbers_not_in_passage("Germany sold 545,142 EVs", "Absatz 2025: 545.142 Elektroautos.",
                              "Absatz 2025: 545.142 Elektroautos.") == ["545,142"]

# 16. L2: the model's parts must cover the claim. A reply with only the true half of
#     "raised $5M ... and was acquired by Yassir" is amber, never SOURCED, never red.
y_page = "VOLZ raised $5M in a seed round in 2023, led by local investors."
y_claim = "VOLZ raised $5M in 2023 and was later acquired by Yassir in 2025."
r = judge({"parts": [P("VOLZ raised $5M in 2023", "stated", y_page)]}, y_claim, y_page)
assert r["facts"][0]["status"] == "stated" and r["label"] == "COULDN'T CONFIRM", r
assert "covers only" in r["reason"], r
# A dropped number caps too, even when the words are mostly covered.
n_claim = "VOLZ raised $5M in 2023 from 12 local investors."
r = judge({"parts": [P("VOLZ raised $5M in 2023 from local investors", "stated", y_page)]}, n_claim, y_page)
assert r["label"] == "COULDN'T CONFIRM" and "leaves out 12" in r["reason"], r
# The full breakdown is SOURCED as before; a missing half stays PARTIAL (caps never redden).
r = judge({"parts": [P("VOLZ raised $5M in 2023", "stated", y_page),
                     P("VOLZ was acquired by Yassir in 2025", "missing")]}, y_claim, y_page)
assert r["label"] == "PARTIAL", r
r = judge({"parts": [P("VOLZ raised $5M in a seed round in 2023", "stated", y_page)]},
          "VOLZ raised $5M in a seed round in 2023.", y_page)
assert r["label"] == "SOURCED", r
# Caps are amber only: an unsupported reply stays UNSUPPORTED.
r = judge({"parts": [P("VOLZ raised $9M", "missing")]}, y_claim, y_page)
assert r["label"] == "UNSUPPORTED", r
# Facts are never dropped silently: over MAX_FACTS, the claim can't be SOURCED.
from quote_check import MAX_FACTS
many = [P(f"VOLZ raised $5M in a seed round in 2023", "stated", y_page)] * (MAX_FACTS + 1)
r = judge({"parts": many}, "VOLZ raised $5M in a seed round in 2023.", y_page)
assert r["label"] == "COULDN'T CONFIRM" and f"into {MAX_FACTS + 1} facts" in r["reason"], r
assert len(judge({"parts": many[:7]}, "VOLZ raised $5M in a seed round in 2023.", y_page)["facts"]) == 7


# 17. Cross-language coverage (L2): a French claim broken into English parts shares few
#     content words with them, so the word-coverage cap is skipped; numbers still count.
from quote_check import coverage_caps, language
fr_claim = ("Les ventes de vélos électriques en Tunisie ont atteint 12 000 unités en 2024, "
            "portées par les subventions publiques.")
en_parts = ["Electric bicycle sales in Tunisia reached 12,000 units in 2024",
            "The sales were driven by public subsidies"]
assert language(fr_claim) == "fr" and language("\n".join(en_parts)) == "en"
assert coverage_caps(fr_claim, en_parts) == [], coverage_caps(fr_claim, en_parts)
gone = coverage_caps(fr_claim, ["Electric bicycle sales in Tunisia grew in 2024",
                                "The sales were driven by public subsidies"])
assert len(gone) == 1 and "leaves out 12 000" in gone[0], gone              # numbers still apply
low = coverage_caps("Electric bicycle sales in Tunisia reached 12,000 units in 2024, driven by "
                    "public subsidies, cheaper imports and new urban cycling lanes.",
                    ["Electric bicycle sales in Tunisia reached 12,000 units in 2024"])
assert any("covers only" in c for c in low), low                            # same language: capped
low_fr = coverage_caps(fr_claim.replace(".", ", grâce aux importations moins chères et aux nouvelles pistes cyclables."),
                       ["Les ventes de vélos en Tunisie ont atteint 12 000 unités en 2024"])
assert any("covers only" in c for c in low_fr), low_fr
# Through judge(): stated with a verified English quote -> SOURCED, not capped by wording.
bk_page = ("Electric bicycle sales in Tunisia reached 12,000 units in 2024.\n"
           "Sales were driven by public subsidies for urban commuters.")
r = judge({"parts": [P(en_parts[0], "stated", "Electric bicycle sales in Tunisia reached 12,000 units in 2024."),
                     P("Sales were driven by public subsidies", "stated",
                       "Sales were driven by public subsidies for urban commuters.")]}, fr_claim, bk_page)
assert r["label"] == "SOURCED", r

# 18. Countries vs demonyms/adjectives, English and French, accents and case ignored.
from entities import named_in, DEMONYMS
assert named_in("Algérie", "Growth in the Algerian market was strong.")
assert named_in("Algeria", "Le marché algérien a progressé.") and named_in("ALGERIE", "algériennes")
assert named_in("Maroc", "Moroccan exports rose") and named_in("Morocco", "la production marocaine")
assert not named_in("Morocco", "Growth in the Algerian market was strong.")
assert not named_in("Niger", "Nigeria's oil output") and named_in("Niger", "the Nigerien government")
assert named_in("United States", "U.S. buyers") and not named_in("US", "between us and them")
assert named_in("Émirats arabes unis", "Emirati investors") and named_in("Côte d'Ivoire", "Ivorian cocoa")
assert named_in("Afrique du Sud", "South African banks") and named_in("Turquie", "Turkish exports")
assert entities("Algerian startups grew while Angolan firms waited.") == []  # demonyms alone: no names
assert "angolan" in DEMONYMS and "marocaine" in DEMONYMS
dz_page = "Algerian startups raised $5 million in 2024, mostly from public funds."
dz_q = "Algerian startups raised $5 million in 2024, mostly from public funds."
dz_claim = "Les startups en Algérie ont levé 5 millions de dollars en 2024."
assert check_fact("Les startups en Algérie ont levé 5 millions de dollars", dz_q, dz_claim, dz_page, quote_on_page) is None
ma_claim = "Les startups au Maroc ont levé 5 millions de dollars en 2024."
hit = check_fact("Les startups au Maroc ont levé 5 millions de dollars", dz_q, ma_claim, dz_page, quote_on_page)
assert hit and hit[0] == "missing" and hit[1] == ["Maroc"], hit

# 19. A2 evidence window: a page with no line breaks shows only the sentence(s) with the
#     match (<= ~400 chars, "…" at cut edges); decimals, abbreviations and French spacing
#     never split a sentence.
from quote_check import sentence_spans, EVIDENCE_CHARS
t = ("Prices rose 29.7 percent in 2024. M. Dupont said so, etc. and U.S. buyers agreed. "
     "Est-ce vrai ? Oui, selon l'institut.")
assert [t[a:b] for a, b in sentence_spans(t)] == [
    "Prices rose 29.7 percent in 2024.", "M. Dupont said so, etc. and U.S. buyers agreed.",
    "Est-ce vrai ?", "Oui, selon l'institut."], sentence_spans(t)
filler = "The weather in the coastal towns was mild and the markets stayed busy all week. "
one_line = (filler * 31 + "Exports rose 29.7 percent, M. Haddad said. Tunisia shipped 4,812 tonnes of "
            "dates to U.S. buyers in 2024, etc. and more. " + filler * 31).strip()
assert len(one_line) > 5000 and "\n" not in one_line
r = judge({"parts": [P("Tunisia shipped 4,812 tonnes of dates", "missing")]},
          "Tunisia shipped 4,812 tonnes of dates in 2024.", one_line)
ev = r["facts"][0].get("evidence", "")
assert r["facts"][0]["status"] == "possible" and len(ev) <= EVIDENCE_CHARS + 2, (len(ev), ev)
assert ev == "\u2026Tunisia shipped 4,812 tonnes of dates to U.S. buyers in 2024, etc. and more.\u2026", ev
# a match spread over two sentences keeps both; a short line is shown whole, no ellipsis
r = judge({"parts": [P("Exports rose 29.7% while Tunisia shipped 4,812 tonnes", "missing")]},
          "Exports rose 29.7% while Tunisia shipped 4,812 tonnes.", one_line)
ev = r["facts"][0]["evidence"]
assert ev.startswith("\u2026Exports rose 29.7 percent, M. Haddad said. Tunisia shipped 4,812") and ev.endswith("\u2026"), ev
short = "Tunisia shipped 4,812 tonnes of dates in 2024."
r = judge({"parts": [P("Tunisia shipped 4,812 tonnes of dates", "missing")]}, short, short)
assert r["facts"][0]["evidence"] == short, r
# one sentence longer than the window: cut around the number, both edges marked
long_sentence = "In the coastal towns " + "and the busy markets " * 40 + "Tunisia shipped 4,812 tonnes " + "of dates and figs " * 40 + "."
r = judge({"parts": [P("Tunisia shipped 4,812 tonnes of dates", "missing")]}, short, long_sentence)
ev = r["facts"][0]["evidence"]
assert len(ev) <= EVIDENCE_CHARS + 2 and "4,812" in ev and ev[0] == ev[-1] == "\u2026", ev


# 20. Language fallback is fail-safe: the word cap is skipped only when BOTH sides are
#     confidently detected and differ; unknown / low-confidence keeps it.
from quote_check import LANG_MIN_HITS, LANG_MIN_SHARE, LANG_MAJORITY
assert language("Algérie : 45 % en 2024") is None                    # too few function words
caps = coverage_caps("Algérie : 45 % en 2024", ["The country held a 45% share in 2024 according to the ministry"])
assert any("covers only" in c for c in caps), caps                     # claim unknown: cap kept
num_parts = ["45%; 12,000 units; 2024", "3.2 GW, 9,500 MW"]
assert language("\n".join(num_parts)) is None                         # mostly numbers: unknown
caps = coverage_caps("Electric bicycle sales in Tunisia reached 12,000 units in 2024, with 45% bought "
                     "on credit and 3.2 GW of new charging capacity, 9,500 MW.", num_parts)
assert any("covers only" in c for c in caps), caps                     # English + number parts: kept
caps = coverage_caps("Electric bicycle sales in Tunisia reached 12,000 units in 2024, with 45% bought "
                     "on credit and 3.2 GW of new charging capacity, 9,500 MW.",
                     ["Electric bicycle sales in Tunisia reached 12,000 units in 2024"])
assert any("covers only" in c for c in caps), caps                     # same language: kept
assert coverage_caps(fr_claim, en_parts) == []                         # full FR vs full EN: skipped
assert (LANG_MIN_HITS, LANG_MIN_SHARE, LANG_MAJORITY) == (3, 0.2, 3)

# 21. A country name inside another country's name is that other country: never a match.
#     Ambiguous adjectives ("Congolese": either Congo) fail toward amber.
for claim_name, passage in [
        ("Sudan", "Oil exports from South Sudan rose."), ("Soudan", "Le Soudan du Sud exporte du pétrole."),
        ("Guinea", "Rice imports in Guinea-Bissau doubled."), ("Guinea", "Equatorial Guinea pumps oil."),
        ("Guinée", "La Guinée équatoriale produit du pétrole."), ("Guinea", "Papua New Guinea mines gold."),
        ("Congo", "Cobalt from DR Congo"), ("Congo", "the Democratic Republic of the Congo"),
        ("Congo", "le cobalt de la RDC"), ("Congo", "la République démocratique du Congo"),
        ("Korea", "North Korea tested a missile."), ("South Korea", "North Korea tested a missile."),
        ("Corée du Sud", "la Corée du Nord"), ("South Korea", "North Korean exports"),
        ("Niger", "Nigerian banks grew."), ("Niger", "les banques nigérianes"),
        ("DR Congo", "Congolese miners"), ("Congo", "Congolese miners")]:
    assert not named_in(claim_name, passage), (claim_name, passage)
for claim_name, passage in [
        ("South Sudan", "South Sudanese refugees"), ("Sudan", "Sudanese farmers"),
        ("Guinea", "Guinea and Guinea-Bissau signed a deal."), ("DR Congo", "le cobalt de la RDC"),
        ("Congo", "the Republic of the Congo"), ("Niger", "the Nigerien government"),
        ("South Korea", "South Korean carmakers"), ("Corée du Sud", "les exportations sud-coréennes")]:
    assert named_in(claim_name, passage), (claim_name, passage)

# Periods (quarters / halves) work like the year rule: the claim's period must be in the
# quoted passage, the page title, a heading above it or the quoted row's table header, else
# SOURCED is capped at COULDN'T CONFIRM (amber). A period mismatch alone is never red.
from check_numbers import blocks_ctx as _bctx
from quote_check import periods
fact = lambda text, quote: {"text": text, "kind": "fact", "status": "stated", "quote": quote}
row_report = ("| Brand / group | Q2 2025 shipment share | Annual trend |\n|---|---:|---|\n"
              "| Samsung | 18% | +3% year over year [src](https://phones.example/q) |")
(row, _urls, row_ctx), = _bctx(row_report)
assert row == "Brand / group: Samsung; Q2 2025 shipment share: 18%; Annual trend: +3% year over year", row
assert QC_own(row, row_ctx) == "Samsung; 18%; +3% year over year"       # headers are context
q1_page = ("Smartphone market update\n"
           "Samsung held an 18% share of smartphone shipments in Q1 2025, up 3% year over year.")
q1_quote = "Samsung held an 18% share of smartphone shipments in Q1 2025, up 3% year over year."
reply = {"parts": [fact("Samsung's Q2 2025 shipment share was 18%", q1_quote),
                   fact("Samsung's shipments grew 3% year over year", q1_quote)]}
r = judge(reply, row, q1_page, "https://phones.example/q", context=row_ctx)
assert r["label"] == "COULDN'T CONFIRM" and "the period Q2 is not in its passage" in r["reason"], r
# The model calling it contradicted ("Q1, not Q2") is still no red: Q1/Q2 is no figure conflict.
reply_c = {"parts": [{**fact("Samsung's Q2 2025 shipment share was 18%", q1_quote), "status": "contradicted"}]}
assert judge(reply_c, row, q1_page, "https://phones.example/q", context=row_ctx)["label"] not in (
    "CONTRADICTED", "UNSUPPORTED")
# A table whose header says Q2 2025: the period comes from the header row, SOURCED.
q2_page = ("Smartphone shipments by vendor\n| Vendor | Q2 2025 share | YoY |\n| Samsung | 18% | +3% |\n"
           "| Apple | 15% | -1% |")
reply = {"parts": [fact("Samsung's Q2 2025 shipment share was 18%", "| Samsung | 18% | +3% |"),
                   fact("Samsung's shipments grew 3% year over year", "| Samsung | 18% | +3% |")]}
r = judge(reply, row, q2_page, "https://phones.example/q", context=row_ctx)
assert r["label"] == "SOURCED", r
# French: "T2 2025" in the claim, "deuxième trimestre 2025" in the passage.
fr_claim = "Au T2 2025, les ventes de Renault ont atteint 412 000 véhicules."
fr_quote = "Au deuxième trimestre 2025, Renault a vendu 412 000 véhicules dans le monde."
fr_page = "Résultats commerciaux\n" + fr_quote
r = judge({"parts": [fact("Les ventes de Renault ont atteint 412 000 véhicules au T2 2025", fr_quote)]},
          fr_claim, fr_page, "https://renault.example/t2")
assert r["label"] == "SOURCED", r
assert periods("premier semestre 2025") == {("H", 1): "premier semestre"} and periods("H1 2025").keys() == {("H", 1)}
assert periods("1er trimestre") == {("Q", 1): "1er trimestre"} and periods("second half of 2024") == {("H", 2): "second half"}
assert periods("t2 FAQ2 Q22025 H3 third half") == {}
# A period in the page title counts too.
r = judge({"parts": [fact("Renault sold 412 000 vehicles in Q2 2025", "Renault sold 412 000 vehicles worldwide in 2025.")]},
          "Renault sold 412 000 vehicles in Q2 2025.", "Renault sold 412 000 vehicles worldwide in 2025.",
          "https://renault.example/t", meta={"title": "Renault Q2 2025 sales results", "headings": []})
assert r["label"] == "SOURCED", r
r = judge({"parts": [fact("Renault sold 412 000 vehicles in Q2 2025", "Renault sold 412 000 vehicles worldwide in 2025.")]},
          "Renault sold 412 000 vehicles in Q2 2025.", "Renault sold 412 000 vehicles worldwide in 2025.",
          "https://renault.example/t", meta={"title": "Renault Q3 2025 sales results", "headings": []})
assert r["label"] == "COULDN'T CONFIRM" and "period Q2" in r["reason"], r

# Column-aware table checks: a figure in the quoted row counts for the column it sits under.
from quote_check import table_header, column_check
row_s = "| Samsung | 3.4 | 18% | 3.3 | 19% | +3% |"
head_s = "| Brand | Q2 2025 units | Q2 2025 share | Q2 2024 units | Q2 2024 share | YoY |"
cols_page = ("Smartphone shipments by vendor, in millions\n" + head_s + "\n|---|---|---|---|---|---|\n"
             + row_s + " \n| Apple | 3.0 | 16% | 2.9 | 15% | +2% |\n| Brand | 2024 | 2025 |\n| Tesla | 10 | 12 |")
P = lambda t, st, q="": {"text": t, "kind": "fact", "status": st, "quote": q}
U = "https://phones.example/q2"
c19 = "Samsung held 19% of smartphone shipments in Q2 2025."
f19 = "Samsung held 19% of smartphone shipments in Q2 2025"
column_reason = "The page gives 18% for Q2 2025; 19% is its Q2 2024 figure."
for st, q in (("contradicted", row_s), ("missing", "")):     # the model's word + the column: red
    r = judge({"parts": [P(f19, st, q)]}, c19, cols_page, U)
    assert r["label"] == "CONTRADICTED" and column_reason in r["reason"], (st, r)
    assert "possibly stated" not in r["reason"].lower() and r["facts"][0]["quote"] == row_s, r
# The model saying stated: amber (a code check alone never accuses), never SOURCED.
r = judge({"parts": [P(f19, "stated", row_s)]}, c19, cols_page, U)
assert r["label"] == "COULDN'T CONFIRM" and column_reason in r["reason"], r
r = judge({"parts": [P("Samsung held 18% of smartphone shipments in Q2 2025", "stated", row_s)]},
          "Samsung held 18% of smartphone shipments in Q2 2025.", cols_page, U)
assert r["label"] == "SOURCED", r
# Header found by its separator; a glued table without one keeps its own (same-width) header.
assert table_header(row_s, cols_page)[1] == "Q2 2025 units"
assert table_header("| Tesla | 10 | 12 |", cols_page) == ["Brand", "2024", "2025"]
r = judge({"parts": [P("Tesla sold 10 units in 2025", "contradicted", "| Tesla | 10 | 12 |")]},
          "Tesla sold 10 units in 2025.", cols_page, U)
assert r["label"] == "CONTRADICTED" and "The page gives 12 for 2025; 10 is its 2024 figure." in r["reason"], r
# No findable header (a row with a figure on top, no separator): today's behaviour.
bare = "Vendor figures\n| Samsung | 3.4 | 18% | 3.3 | 19% |\n| Apple | 3.0 | 16% | 2.9 | 15% |"
assert table_header("| Samsung | 3.4 | 18% | 3.3 | 19% |", bare) is None
r = judge({"parts": [P(f19, "contradicted", "| Samsung | 3.4 | 18% | 3.3 | 19% |")]}, c19, bare, U)
assert r["label"] == "COULDN'T CONFIRM" and r["facts"][0]["status"] == "possible", r
# A claim with no period whose figure is in some column: today's behaviour.
r = judge({"parts": [P("Samsung held 19% of smartphone shipments", "missing")]},
          "Samsung held 19% of smartphone shipments.", cols_page, U)
assert r["label"] == "COULDN'T CONFIRM" and r["facts"][0]["status"] == "possible", r
assert column_check("Samsung grew 3% year over year in Q2 2025", row_s, cols_page) is None   # YoY: no period
# Only under another period, and no column for the claim's: amber, never "possibly stated".
only24 = "Shipments\n| Brand | Q2 2024 share |\n|---|---|\n| Samsung | 19% |"
r = judge({"parts": [P(f19, "missing")]}, c19, only24, U)
assert r["label"] == "COULDN'T CONFIRM" and r["facts"][0]["status"] == "unconfirmed", r
assert "This figure appears on the page under 'Q2 2024 share', not Q2 2025." in r["reason"], r
assert "possibly" not in r["reason"].lower()
# Two periods in one claim: a fact without its own period is never pinned to the claim's.
r = judge({"parts": [P("Samsung held 18% in Q2 2025", "stated", row_s),
                     P("Samsung was down from 19% a year earlier", "stated", row_s)]},
          "Samsung held 18% in Q2 2025, down from 19% a year earlier.", cols_page, U)
assert r["label"] != "CONTRADICTED" and "Q2 2024 figure" not in r["reason"], r
# French headers: T2 2025 / T2 2024 (T2 = Q2).
fr_row = "| Renault | 18 % | 19 % |"
fr_page = "Parts de marché\n| Marque | T2 2025 | T2 2024 |\n|---|---|---|\n" + fr_row
r = judge({"parts": [P("Renault détenait 19 % du marché au T2 2025", "contradicted", fr_row)]},
          "Renault détenait 19 % du marché au T2 2025.", fr_page, U)
assert r["label"] == "CONTRADICTED" and "The page gives 18 % for T2 2025; 19% is its T2 2024 figure." in r["reason"], r
r = judge({"parts": [P("Renault détenait 18 % du marché au deuxième trimestre 2025", "stated", fr_row)]},
          "Renault détenait 18 % du marché au deuxième trimestre 2025.", fr_page, U)
assert r["label"] == "SOURCED", r
# A header-paired table claim: the row label sits in its own part, so the number part names
# no one; the claim's text names the row (Samsung): red like the sentence form.
hp = lambda brand, share: (f"Brand / group: {brand}; Q2 2025 shipment share: {share}; "
                           "Annual trend: +3% year over year")
hp_ctx = "Brand / group\nQ2 2025 shipment share\nAnnual trend"
hp_parts = lambda brand, share, st: {"parts": [
    {"text": f"Brand / group: {brand}", "kind": "framing", "status": "", "quote": ""},
    P(f"Q2 2025 shipment share: {share}", st, row_s),
    P("Annual trend: +3% year over year", "stated", row_s)]}
r = judge(hp_parts("Samsung", "19%", "contradicted"), hp("Samsung", "19%"), cols_page, U, context=hp_ctx)
assert r["label"] == "CONTRADICTED" and column_reason in r["reason"], r
# The same figures claimed for Xiaomi, quoting Samsung's row: never red.
r = judge(hp_parts("Xiaomi", "19%", "contradicted"), hp("Xiaomi", "19%"), cols_page, U, context=hp_ctx)
assert r["label"] != "CONTRADICTED", r
# A sentence naming two brands: the fact about Xiaomi doesn't borrow the claim's Samsung.
r = judge({"parts": [P("Xiaomi held 19% in Q2 2025", "contradicted", row_s)]},
          "Samsung and Xiaomi held 18% and 19% in Q2 2025.", cols_page, U)
assert r["label"] != "CONTRADICTED", r
r = judge(hp_parts("Samsung", "18%", "stated"), hp("Samsung", "18%"), cols_page, U, context=hp_ctx)
assert r["label"] == "SOURCED", r

print("check tests passed")
