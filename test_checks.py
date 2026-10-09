"""Token-free checks of the code-only verdict checks: unit-scaled numbers and the name check.
Run: .venv/bin/python test_checks.py"""
from entities import check_fact, entities
from quote_check import judge, missing_numbers, numbers_not_in_passage, quote_on_page

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
assert r["label"] == "CONTRADICTED" and "about Moustachir, not VOLZ" in r["reason"], r

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
                       ("545,142 EVs", "545.142 Elektroautos"),
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
toks = [(m.group(), locnum.readings(m, page=True)) for m in locnum.NUMBER_RE.finditer("In 2025 2 585 187 cars")]
assert [t for t, _ in toks] == ["2025", "2 585 187"], toks
assert D(20252585187) not in locnum.values("In 2025 2 585 187 cars") and D(2025258) not in locnum.values("In 2025 2 585 187 cars")
# Ambiguous tokens keep both readings; lists stay separate numbers.
assert locnum.values("1,234") == {D(1234), D("1.234")} and locnum.values("545.142") == {D(545142), D("545.142")}
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

print("check tests passed")
