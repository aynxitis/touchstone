"""Compare two runs of the same report claim by claim (e.g. Groq vs Gemini), zero tokens.

  .venv/bin/python compare_runs.py A.json B.json [--labels labelsN.json]

A/B: run files from quote_check.py --out or the web page's "Download results" (audit.json
works too). Prints each claim's label in both runs, marks differences, and with --labels the
accuracy of each (CONTRADICTED = UNSUPPORTED, COULDN'T CONFIRM = PARTIAL, as in CLAUDE.md)."""
import argparse
import json

from rescore import load_run

SCORE = {"CONTRADICTED": "UNSUPPORTED", "COULDN'T CONFIRM": "PARTIAL"}


def name(path):
    with open(path, encoding="utf-8") as f:
        run = json.load(f)
    return f"{run.get('provider', '?')}" if isinstance(run, dict) else "audit.json"


def compare(a, b, labels=None):
    """Lines of the comparison table, then the totals."""
    ra = {c["claim"]: c for c in load_run(a)}
    rb = {c["claim"]: c for c in load_run(b)}
    na, nb = name(a), name(b)
    lines = [f"{'claim':>5}  {na[:18]:<18}  {nb[:18]:<18}  hand label"]
    same = both = 0
    for n in sorted(set(ra) | set(rb)):
        la, lb = ra.get(n, {}).get("label", "-"), rb.get(n, {}).get("label", "-")
        both += n in ra and n in rb
        same += n in ra and n in rb and la == lb
        mark = "  " if la == lb else "<>"
        lines.append(f"{n:>5}  {la:<18}  {lb:<18}  {(labels or {}).get(n, '')} {mark}".rstrip())
    lines.append(f"\nSame label on {same}/{both} claims checked in both runs.")
    if labels:
        sc = lambda l: SCORE.get(l, l)
        for nm, run in ((na, ra), (nb, rb)):
            scorable = [n for n, l in labels.items() if n in run and l != "SOURCE UNREACHABLE"]
            ok = sum(sc(run[n]["label"]) == sc(labels[n]) for n in scorable)
            lines.append(f"Accuracy {nm}: {ok}/{len(scorable)}")
    return lines


def main():
    ap = argparse.ArgumentParser(description="Compare two Touchstone runs claim by claim.")
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--labels")
    args = ap.parse_args()
    labels = None
    if args.labels:
        with open(args.labels, encoding="utf-8") as f:
            labels = {x["claim"]: x["label"] for x in json.load(f)}
    print("\n".join(compare(args.a, args.b, labels)))


if __name__ == "__main__":
    main()
