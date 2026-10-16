"""Score Touchstone runs against the challenge answer key.

    .venv/bin/python eval/score.py RUN.json [RUN.json ...] [--key eval/challenge/touchstone-answer-key.csv]
                                   [--csv OUT.csv]

RUN.json: a "touchstone-run" file (the web page's "Download results" or quote_check.py --out).
Claims are matched to answer-key rows by claim text + URL, never by claim number (Touchstone's
numbering skips uncited lines). A key row's report number picks the run whose report holds its
claim text, so the runs can be given in any order. Exit status 1 if any claim is false SOURCED.
"""
import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from urllib.parse import unquote

AMBER = {"PARTIAL", "COULDN'T CONFIRM"}
RED = {"UNSUPPORTED", "CONTRADICTED"}
NONE = {"", "—", "-"}


def norm(text):
    text = unicodedata.normalize("NFKC", text or "").replace("’", "'").replace("‘", "'")
    text = re.sub(r"\[([^\]]*)\]\([^)]*(\([^)]*\))?[^)]*\)", r"\1", text)   # markdown links
    return re.sub(r"[^\w%$€£¢.,'–-]+", " ", text.lower()).strip(" .")


def norm_url(url):
    url = (url or "").strip()
    return "" if url in NONE or not url.startswith("http") else unquote(url).rstrip("/")


def run_entries(run):
    """Every claim of a run as (text, urls, label, reason)."""
    out = []
    for c in run.get("claims", []):
        urls = c.get("urls") or ([c["url"]] if c.get("url") else [])
        if c.get("claim") is None:
            out.append((c.get("text", ""), [], "NO SOURCE GIVEN", c.get("reason", "")))
        else:
            out.append((c.get("text", ""), urls, c.get("label", ""), c.get("reason", "")))
    for c in run.get("not_checked", []):
        out.append((c.get("text", ""), [c["url"]] if c.get("url") else [], c.get("label") or "NOT CHECKED",
                    c.get("reason", "not checked")))
    for text in run.get("uncited", []):
        out.append((text, [], "NO SOURCE GIVEN", "listed in uncited"))
    return out


def similar(a, b):
    try:
        from rapidfuzz import fuzz
        return fuzz.ratio(a, b)
    except ImportError:
        import difflib
        return 100 * difflib.SequenceMatcher(None, a, b).ratio()


def find(entries, text, url):
    """The run entry for a key row: same URL (or none for a no-link row), best text match."""
    want, nt = norm_url(url), norm(text)
    best, score = None, 0
    for e in entries:
        urls = {norm_url(u) for u in e[1]}
        # A URL the run cut short (the old link parser stopped at a ')') still matches its row.
        if (want and not any(u == want or (u and want.startswith(u)) for u in urls)) or (not want and urls):
            continue
        ne = norm(e[0])
        s = 100 if ne == nt else (95 if (nt in ne or ne in nt) and min(len(ne), len(nt)) > 20 else similar(nt, ne))
        if s > score:
            best, score = e, s
    return best if score >= 85 else None


def accepted(row):
    labels = {row["Expected label"].strip()}
    also = row.get("Also acceptable", "").strip()
    if also not in NONE:
        labels |= {x.strip() for x in re.split(r"[/;|]", also) if x.strip() not in NONE}
    return labels


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--key", default="eval/challenge/touchstone-answer-key.csv")
    ap.add_argument("--csv", help="write per-claim results here")
    args = ap.parse_args()

    runs = []
    for path in args.runs:
        with open(path, encoding="utf-8") as f:
            run = json.load(f)
        runs.append((path, norm(run.get("report", "")), run_entries(run)))
    with open(args.key, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # A key report number maps to the run whose report text holds most of its claims.
    by_report = defaultdict(list)
    for row in rows:
        by_report[row["Report"]].append(row)
    run_of = {}
    for rep, rs in by_report.items():
        hits = [(sum(norm(r["Claim text"])[:60] in rtext for r in rs), i) for i, (_, rtext, _) in enumerate(runs)]
        n, i = max(hits)
        if n:
            run_of[rep] = i

    results = []
    for row in rows:
        ok_labels = accepted(row)
        expected = row["Expected label"].strip()
        if row["Report"] not in run_of:
            continue
        entry = find(runs[run_of[row["Report"]]][2], row["Claim text"], row["URL"])
        actual, reason = (entry[2], entry[3]) if entry else ("(not found)", "claim not found in the run")
        results.append({"report": row["Report"], "line": row["Claim #"], "category": row["Category (1-16)"],
                        "expected": expected, "also": row.get("Also acceptable", ""), "actual": actual,
                        "result": "PASS" if actual in ok_labels else "FAIL", "reason": reason,
                        "claim": row["Claim text"]})

    if not results:
        sys.exit("No answer-key row matched any run.")
    for r in results:
        print(f"{r['result']}  r{r['report']}#{r['line']:<3} {r['expected']:<18} -> {r['actual']:<18} {r['claim'][:70]}")
        if r["result"] == "FAIL":
            print(f"        {r['reason'][:240]}")

    passed = sum(r["result"] == "PASS" for r in results)
    print(f"\nPass rate: {passed}/{len(results)} ({100 * passed / len(results):.0f}%)")
    cats = defaultdict(Counter)
    for r in results:
        cats[r["category"]][r["result"]] += 1
    print("By category:")
    for cat in sorted(cats, key=lambda c: int(re.match(r"\d+", c).group()) if re.match(r"\d+", c) else 99):
        c = cats[cat]
        print(f"  {cat:<28} {c['PASS']}/{c['PASS'] + c['FAIL']}")
    false_sourced = [r for r in results if r["actual"] == "SOURCED" and r["expected"] != "SOURCED"]
    false_red = [r for r in results if r["actual"] == "CONTRADICTED" and r["expected"] in ("SOURCED", "PARTIAL")]
    safe = [r for r in results if r["result"] == "FAIL" and r["actual"] in AMBER
            and (r["expected"] == "SOURCED" or r["expected"] in RED)]
    print(f"FALSE SOURCED: {len(false_sourced)}" + "".join(f"\n  r{r['report']}#{r['line']} {r['claim'][:70]}" for r in false_sourced))
    print(f"FALSE RED (CONTRADICTED where SOURCED/PARTIAL expected): {len(false_red)}"
          + "".join(f"\n  r{r['report']}#{r['line']} {r['claim'][:70]}" for r in false_red))
    print(f"Safe misses (amber where green/red expected): {len(safe)}")
    if len(results) < len(rows):
        print(f"({len(rows) - len(results)} key rows skipped: no run given for their report)")

    if args.csv:
        with open(args.csv, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(results[0]))
            w.writeheader()
            w.writerows(results)
    sys.exit(1 if false_sourced else 0)


if __name__ == "__main__":
    main()
