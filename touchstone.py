"""Touchstone as a library: audit(report) yields one result per claim, in report order.
Used by the CLI (quote_check.py) and the web app (app.py)."""
import time
from concurrent.futures import ThreadPoolExecutor

from check_numbers import NUM_RE, segments
from fetch_links import fetch
from quote_check import check


def select(cited, max_claims):
    """Indices (0-based) of the cited claims to check: claims with numbers first, then the
    rest, in report order within each group, capped at max_claims."""
    with_nums = [i for i, (t, _) in enumerate(cited) if NUM_RE.search(t)]
    without = [i for i, (t, _) in enumerate(cited) if not NUM_RE.search(t)]
    return set((with_nums + without)[:max_claims])


def audit(report, client, pages=None, max_claims=None, only=None, deadline=None):
    """Yield events as dicts:
      {"type": "start", "cited", "checked", "uncited"}
      {"type": "claim", "index", "claim", "text", "url", "label", ...}   index = 1..checked
         (uncited text comes as a claim event with claim None, index None)
      {"type": "skipped", "claim", "text", "url"}   cited but over the cap / not in `only`
      {"type": "done", "tokens"}
    pages: {url: fetch result dict}; if None, the selected claims' pages are fetched live.
    deadline: time.monotonic() value; claims not started by then are marked NOT CHECKED."""
    segs = segments(report)
    cited = [(t, u) for t, u in segs if u]
    if only is not None:
        chosen = {i - 1 for i in only}
    elif max_claims is not None:
        chosen = select(cited, max_claims)
    else:
        chosen = set(range(len(cited)))
    yield {"type": "start", "cited": len(cited), "checked": len(chosen),
           "uncited": len(segs) - len(cited)}

    if pages is None:
        urls = list(dict.fromkeys(cited[i][1] for i in sorted(chosen)))
        with ThreadPoolExecutor(max_workers=8) as pool:
            pages = dict(zip(urls, pool.map(fetch, urls)))

    tokens, n, index = 0, 0, 0
    for text, url in segs:
        if url is None:   # uncited text: nothing to check, costs no tokens
            yield {"type": "claim", "index": None, "claim": None, "text": text, "url": None,
                   "label": "NO SOURCE GIVEN", "quote": "",
                   "reason": "The report gives no source for this.", "tokens": 0}
            continue
        n += 1
        if n - 1 not in chosen:
            yield {"type": "skipped", "claim": n, "text": text, "url": url}
            continue
        index += 1
        page = pages.get(url) or {}
        if deadline is not None and time.monotonic() > deadline:
            r = {"label": "NOT CHECKED", "quote": "", "reason": "Audit time limit reached.", "tokens": 0}
        elif not page.get("text"):
            why = " ".join(x for x in (page.get("status"), page.get("detail")) if x)
            r = {"label": "SOURCE UNREACHABLE", "quote": "",
                 "reason": f"Could not read the page ({why})." if why else "", "tokens": 0}
        else:
            try:
                r = check(client, text, page["text"])
            except Exception as e:   # model timeout, API error: report it, keep going
                r = {"label": "ERROR", "quote": "", "tokens": 0,
                     "reason": f"Model call failed ({type(e).__name__})."}
        tokens += r["tokens"]
        yield {"type": "claim", "index": index, "claim": n, "text": text, "url": url, **r}
    yield {"type": "done", "tokens": tokens}
