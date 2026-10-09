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

print("check tests passed")
