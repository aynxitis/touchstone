"""Re-score a saved run with the current code checks, zero tokens.

  .venv/bin/python rescore.py RUN.json [--cache PAGES.json] [--labels LABELS.json] [--out NEW.json]

RUN.json is a file from the web page's "Download results" button, or the CLI's audit.json.
Each checked claim's saved model reply is fed through the current judge() against its page,
and the old and new labels are printed side by side. Pages are re-fetched (no model call);
with --cache, they are read from PAGES.json if it exists, else fetched and saved there.
Cache files are copies of other sites' pages: never commit them (*.pages.json is ignored).

Limits: the model's reply is replayed as it was, so a change to passage selection or the
prompt is not measured (the model would have seen other passages). A page that changed since
the run can move a label by itself. Older runs without the "model" field are rebuilt from
their facts (a fact a code check demoted is replayed as the model's "stated"). Claims citing
several URLs replay each source's saved reply and merge them as the audit does."""
import argparse
import json
import os

from fetch_links import fetch_many
from quote_check import best_excerpts, judge
from check_numbers import blocks_ctx
from touchstone import HOMEPAGE, combine, hidden_cap, homepage_result, thin_result, vague_note

SKIP = {"SOURCE UNREACHABLE", "NOT CHECKED", "NO SOURCE GIVEN"}
META_NOTE = " Judged from the page's meta description only (the page body loads with JavaScript)."


def load_run(path):
    """[(claim number, text, url, old label, claim dict)] for the checked claims."""
    with open(path, encoding="utf-8") as f:
        run = json.load(f)
    claims = run["claims"] if isinstance(run, dict) else run      # download | audit.json
    return [c for c in claims if isinstance(c, dict) and c.get("claim") and c.get("url")]


def load_contexts(path):
    """{claim number: lead-in context} from the run's saved report (blocks_ctx); empty when
    the file has no report (the CLI's audit.json): then the whole claim text counts."""
    with open(path, encoding="utf-8") as f:
        run = json.load(f)
    report = run.get("report") if isinstance(run, dict) else None
    if not isinstance(report, str):
        return {}
    cited = [c for _, us, c in blocks_ctx(report) if us]
    return {n: c for n, c in enumerate(cited, 1)}


def model_reply(c):
    """The model's reply for a claim: saved as is (new runs), else rebuilt from its facts.
    None: no model call was made (or its reply was unparseable)."""
    if "model" in c:
        return c["model"]
    if c["label"] == "OPINION":
        return {"opinion": True, "parts": []}
    if not c.get("facts") and not c.get("framing"):
        return None
    parts = []
    for f in c.get("facts", []):
        quote = f.get("quote") or f.get("unmatched_quote") or f.get("rejected_quote") or ""
        status = {"unconfirmed": "stated", "possible": "missing"}.get(f["status"], f["status"])
        if f.get("unmatched_quote") or f.get("rejected_quote") or (status == "contradicted" and f.get("note")):
            status = "stated"           # demoted by a code check: the model had said stated
        parts.append({"text": f["fact"], "kind": "fact", "status": status, "quote": quote})
    parts += [{"text": x, "kind": "framing", "status": "", "quote": ""} for x in c.get("framing", [])]
    return {"opinion": False, "parts": parts}


def get_pages(urls, cache):
    pages = {}
    if cache and os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            pages = {r["url"]: r for r in json.load(f)}
    todo = [u for u in urls if u not in pages]
    if todo:
        print(f"Fetching {len(todo)} page(s) (no model call)...")
        pages.update(zip(todo, fetch_many(todo)))
        if cache:
            with open(cache, "w", encoding="utf-8") as f:
                json.dump(list(pages.values()), f, ensure_ascii=False)
    return pages


def rescore(c, page, context=""):
    """New label and reason for one claim, or (None, why) when it can't be re-scored."""
    if c["label"] in SKIP:
        return None, "not judged in the run"
    if not page.get("text"):
        return None, f"page unreadable now ({page.get('status')})"
    reply = model_reply(c)
    if reply is None:
        if c["label"] == "ERROR":
            return None, "model reply was unparseable"
        if best_excerpts(c["text"], page["text"]):
            return None, "no model call in the run; would call the model now"
        reply = {}                          # still no passage: judged without the model
        r = {"label": "UNVERIFIED", "reason": "No relevant passage found on the page."}
    else:
        r = judge(reply, c["text"], page["text"], c["url"],
                  meta={"title": page.get("title"), "headings": page.get("headings")}, context=context)
    if page.get("meta_only"):
        r["reason"] = (r.get("reason", "") + META_NOTE).strip()
        r = thin_result(r)
    if vague_note(c["url"]) == HOMEPAGE:
        r = homepage_result(r)
    if c.get("hidden"):
        r = hidden_cap(r, c["hidden"])
    return r["label"], r["reason"]


def rescore_multi(c, pages, context=""):
    """A claim citing several sources: each source's saved model reply through the current
    judge(), merged with touchstone.combine() as in an audit."""
    if c["label"] in SKIP - {"SOURCE UNREACHABLE"}:
        return None, "not judged in the run"
    per = []
    for s in c["sources"]:
        page = pages.get(s["url"]) or {}
        if s["label"] in ("SOURCE UNREACHABLE", "NOT CHECKED") or s.get("model") is None:
            per.append((s["url"], {"label": s["label"], "quote": "", "reason": s.get("reason", ""),
                                   "tokens": 0, **({"detail": s["detail"]} if s.get("detail") else {})}))
        elif not page.get("text"):
            return None, f"page unreadable now ({page.get('status')}): {s['url']}"
        else:
            per.append((s["url"], judge(s["model"], c["text"], page["text"], s["url"],
                                        meta={"title": page.get("title"), "headings": page.get("headings")},
                                        context=context)))
    r = combine(c["text"], per, pages, context)
    if c.get("hidden"):
        r = hidden_cap(r, c["hidden"])
    return r["label"], r["reason"]


def main():
    ap = argparse.ArgumentParser(description="Re-score a saved Touchstone run with zero tokens.")
    ap.add_argument("run")
    ap.add_argument("--cache", help="pages cache (read if present, else written)")
    ap.add_argument("--labels", help="hand labels [{claim, label}] to score old vs new")
    ap.add_argument("--out", help="save the run with its new labels and reasons (eval/score.py reads it)")
    args = ap.parse_args()

    claims = load_run(args.run)
    contexts = load_contexts(args.run)
    urls = [s["url"] for c in claims for s in (c.get("sources") or [{"url": c["url"]}])]
    pages = get_pages(list(dict.fromkeys(urls)), args.cache)
    labels = {}
    if args.labels:
        with open(args.labels, encoding="utf-8") as f:
            labels = {x["claim"]: x["label"] for x in json.load(f)}

    changed, results, reasons = 0, {}, {}
    for c in claims:
        if len(c.get("sources") or []) > 1:
            new, reason = rescore_multi(c, pages, contexts.get(c["claim"], ""))
        else:
            new, reason = rescore(c, pages.get(c["url"]) or {}, contexts.get(c["claim"], ""))
        results[c["claim"]] = new or c["label"]
        reasons[c["claim"]] = reason if new else c.get("reason", "")
        mark = "  " if new in (None, c["label"]) else "->"
        changed += mark == "->"
        note = f"  ({reason})" if new is None else ""
        print(f"[{c['claim']:>2}] {c['label']:<18} {mark} {new or '(kept)':<18}{note}")
        if mark == "->":
            print(f"       {reason}")
    print(f"\n{changed} label(s) changed out of {len(claims)}.")
    if args.out:
        with open(args.run, encoding="utf-8") as f:
            run = json.load(f)
        for c in run["claims"] if isinstance(run, dict) else run:
            if isinstance(c, dict) and c.get("claim") in results:
                c.update(label=results[c["claim"]], reason=reasons[c["claim"]])
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(run, f, indent=2, ensure_ascii=False)
        print(f"Saved the re-scored run to {args.out}")
    if labels:
        # CLAUDE.md scoring: CONTRADICTED = UNSUPPORTED (red), COULDN'T CONFIRM = PARTIAL (amber)
        sc = lambda l: {"CONTRADICTED": "UNSUPPORTED", "COULDN'T CONFIRM": "PARTIAL"}.get(l, l)
        old = {c["claim"]: c["label"] for c in claims}
        scorable = [n for n, l in labels.items() if n in old and l != "SOURCE UNREACHABLE"]
        acc = lambda got: sum(sc(got[n]) == sc(labels[n]) for n in scorable)
        print(f"Accuracy vs {args.labels}: old {acc(old)}/{len(scorable)}, new {acc(results)}/{len(scorable)}")


if __name__ == "__main__":
    main()
