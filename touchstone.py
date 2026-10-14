"""Touchstone as a library: audit(report) yields one result per claim, in report order.
Used by the CLI (quote_check.py) and the web app (app.py)."""
import math
import re
import threading
import time
from urllib.parse import parse_qsl, urlsplit

from check_numbers import SITE_ONLY, blocks_meta
from fetch_links import BOT_BLOCKED, LATE, fetch_many
from pacing import DAY_FULL, TokenPacer, retry_after
from quote_check import best_excerpts, merge, quote_on_page

MAX_SOURCES = 3            # sources checked per claim: one claim must not fan out into many
                           # fetches/model calls (10 claims x 3 = at most 30 URLs per web audit)
MAX_MINUTE_RETRIES = 5     # per claim, only without a deadline (CLI); with one, the deadline decides
MAX_ERROR_RETRIES = 2      # timeouts, connection errors, 5xx: what the SDK's own retries did
MIN_CALL_SECONDS = 3       # less than this before the deadline: the call isn't sent
NOT_CHECKED_TIME = {"label": "NOT CHECKED", "quote": "", "reason": "Audit time limit reached.", "tokens": 0}
NO_PASSAGE = {"label": "UNVERIFIED", "quote": "", "tokens": 0,
              "reason": "No relevant passage found on the page."}
NOT_CHECKED_WAIT = {"label": "NOT CHECKED", "quote": "", "tokens": 0,
                    "reason": "Audit time limit reached while waiting for model capacity."}


def select(cited, max_claims):
    """Indices (0-based) of the cited claims to check: the first max_claims in report order,
    so the unchecked ones are simply the end of the report. (Numbers-first used to skip a
    no-number claim in the middle, which read as if it had been checked.)"""
    return set(range(min(len(cited), max_claims)))


def status_code(err):
    """HTTP status of a provider error: Groq's .status_code, google-genai's .code."""
    code = getattr(err, "status_code", None)
    return code if isinstance(code, int) else getattr(err, "code", None)


def quota_scope(err):
    """For a rate-limit/quota error (HTTP 429): "minute" if it names a per-minute limit
    (Groq TPM/RPM; Gemini quota ids "...PerMinute..."), else "day" (TPD/RPD, "...PerDay...",
    or unclear: assume the budget is gone)."""
    if status_code(err) != 429:
        return None
    text = f"{err} {getattr(err, 'body', '')} {getattr(err, 'details', '')}"
    return "minute" if re.search(r"per ?minute|\b[TR]PM\b", text, re.I) else "day"


def transient(err):
    """Worth one more try: timeouts, connection errors, 408/409/5xx (not 429, not 4xx)."""
    code = status_code(err)
    return (type(err).__name__ in ("APITimeoutError", "APIConnectionError", "TimeoutError")
            or code in (408, 409) or (isinstance(code, int) and code >= 500))


def error_result(err):
    return {"label": "ERROR", "quote": "", "tokens": 0,     # report it, keep going
            "reason": f"Model call failed ({type(err).__name__})."}


class Late(Exception):
    """A model call still running at the audit's deadline."""


def bounded(call, seconds):
    """call(seconds) in a daemon thread, waited for at most `seconds`: its result, its
    exception, or Late. The call gets the same budget as its request timeout, so the SDK
    closes the connection about when we stop waiting; the audit never waits past it."""
    box = {}

    def run():
        try:
            box["ok"] = call(seconds)
        except BaseException as e:
            box["err"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise Late()
    if "err" in box:
        raise box["err"]
    return box["ok"]


def attempt(call, pacer, need, deadline, clock, sleep, n):
    """Run one model call with pacing and retries. A generator: yields "wait" events, and
    returns (outcome, value): ("ok", result) | ("late", "wait") when a needed wait would pass
    the deadline | ("late", "time") when the deadline comes before or during the call |
    ("quota", "day"|"minute") when the audit must stop | ("error", exception).
    call(timeout): timeout = seconds left before the deadline (None without one).
      Proactive: wait until the call fits the provider's minute (tokens, requests); if
      today's requests are used up (RPD), stop as a daily quota.
      Reactive: a per-minute 429 waits what the provider asks, then resends the same call
      (the daily cap counted this audit at its first call; a retry doesn't count again).
      Timeouts / 5xx: MAX_ERROR_RETRIES retries. A per-day 429 stops at once."""
    minute_tries = error_tries = 0
    while True:
        wait = pacer.wait_needed(need)
        if wait == DAY_FULL:
            return "quota", "day"
        if wait > 0:
            if deadline is not None and clock() + wait > deadline:
                return "late", "wait"
            yield {"type": "wait", "seconds": math.ceil(wait), "claim": n}
            sleep(wait)
            continue
        left = None if deadline is None else deadline - clock()
        if left is not None and left < MIN_CALL_SECONDS:
            return "late", "time"
        pacer.note_request()
        try:
            return "ok", (call(None) if left is None else bounded(call, left))
        except Late:
            return "late", "time"
        except Exception as e:
            scope = quota_scope(e)
            if scope == "day" or (scope == "minute" and deadline is None
                                  and minute_tries >= MAX_MINUTE_RETRIES):
                return "quota", scope
            if scope == "minute":
                minute_tries += 1
                wait = retry_after(e)
                if deadline is not None and clock() + wait > deadline:
                    return "late", "wait"
                yield {"type": "wait", "seconds": math.ceil(wait), "claim": n}
                sleep(wait)
                continue
            if transient(e) and error_tries < MAX_ERROR_RETRIES:
                error_tries += 1
                if deadline is not None and clock() + error_tries + MIN_CALL_SECONDS > deadline:
                    return "late", "time"        # e.g. the request timed out at the deadline
                sleep(error_tries)
                continue
            return "error", e


META_NOTE = " Judged from the page's meta description only (the page body loads with JavaScript)."
HOMEPAGE = "Cites a homepage, not a specific page"
LISTING = "Cites a listing page, not a document"
LISTING_WORDS = {"search", "library", "archive", "archives", "category", "categories", "tag", "tags",
                 "browse", "results", "listing", "list", "filter", "documents", "publications"}
LISTING_KEYS = {"q", "query", "search", "s", "keyword", "keywords", "filter", "filters", "category",
                "tag", "type", "sort", "page"}


def site(url):
    """The site's name as shown to users: its host without "www."."""
    try:
        host = urlsplit(url).hostname
    except ValueError:
        host = None
    return (host or url).removeprefix("www.")


def vague_note(url):
    """HOMEPAGE for a site's front page, LISTING for a search/library page with filter
    parameters; None for a specific page. The source is still checked, the card says so."""
    try:
        parts = urlsplit(url)
        keys = {k.lower() for k, _ in parse_qsl(parts.query, keep_blank_values=True)}
    except ValueError:
        return None
    if parts.path in ("", "/"):
        return LISTING if keys & LISTING_KEYS else HOMEPAGE
    words = set(re.findall(r"[a-z]+", parts.path.lower()))
    return LISTING if parts.query and (words & LISTING_WORDS or keys & LISTING_KEYS) else None


def unreachable(page, url):
    """SOURCE UNREACHABLE with a plain reason; the raw status ("HTTP_ERR 401") goes in
    "detail", never in the main reason."""
    status, detail = page.get("status") or "", page.get("detail") or ""
    code = detail if status == "HTTP_ERR" else ""
    if status == "BLOCKED" and detail == BOT_BLOCKED:
        reason = f"{site(url)} blocked the checker (bot protection or paywall)."
    elif code in ("401", "403"):
        reason = "The site refused the checker (login, paywall or bot protection)."
    elif code in ("404", "410"):
        reason = "The page was not found (it may have moved or been removed)."
    elif code == "429":
        reason = "The site is limiting requests right now."
    elif code.startswith("5"):
        reason = "The site had a server error."
    elif status == "HTTP_ERR":
        reason = "The site returned an error."
    elif status == "PDF_ERROR":
        reason = detail + "."
    elif status == "TIMEOUT":
        reason = "The site took too long to respond."
    elif status == "NO_TEXT":
        reason = UNREADABLE
    elif status == "BLOCKED" and detail == "DNS failed":
        reason = "The site's address could not be found."
    elif status == "BLOCKED":
        reason = "The link points to a private or invalid address, so it was not fetched."
    elif not status:
        reason = "The page was not fetched."
    else:
        reason = "The site could not be reached."
    raw = " ".join(x for x in (status, detail) if x)
    return {"label": "SOURCE UNREACHABLE", "quote": "", "reason": reason, "detail": raw, "tokens": 0}


def add_pages(r, page):
    """PDF sources: each quote / evidence line gets its page number ("p. 3")."""
    starts, text = page.get("page_starts"), page.get("text") or ""
    if not starts:
        return
    bounds = list(zip(starts, starts[1:] + [len(text)]))
    for f in r.get("facts") or []:
        q = (f.get("quote") or f.get("evidence") or "").strip("\u2026")   # evidence may be cut
        if q:
            f["page"] = next((n for n, (a, b) in enumerate(bounds, 1) if quote_on_page(q, text[a:b])), None)


GONE = ("SOURCE UNREACHABLE", "NOT CHECKED")
UNREADABLE = "The page loaded but its content couldn't be read (it may need JavaScript)."
JUDGED = ("PARTIAL", "COULDN'T CONFIRM", "UNSUPPORTED", "CONTRADICTED", "UNVERIFIED")


def thin_result(r):
    """A meta-description-only page (the body needs JavaScript) can confirm a claim, never
    refute it: nothing found there means the page wasn't read, not that it disagrees."""
    if r["label"] in ("UNSUPPORTED", "CONTRADICTED", "UNVERIFIED"):
        return {"label": "SOURCE UNREACHABLE", "quote": "", "reason": UNREADABLE,
                "detail": "meta description only", "tokens": r.get("tokens", 0),
                **({"model": r["model"]} if "model" in r else {})}
    return r


def hidden_cap(r, hidden):
    """ChatGPT's "+N": N more sources the copied text dropped. If the visible ones don't
    confirm the claim, the hidden ones might: amber at worst (COULDN'T CONFIRM), never red."""
    if r["label"] not in JUDGED:
        return r
    r = dict(r)
    if r["label"] in ("UNSUPPORTED", "CONTRADICTED", "UNVERIFIED"):
        r["label"] = "COULDN'T CONFIRM"
    more = f"{hidden} more sources that weren't" if hidden > 1 else "1 more source that wasn't"
    r["reason"] = (r.get("reason", "") + f" Also cites {more} included in the copied text.").strip()
    return r


def over_limit(limit):
    """NOT CHECKED entry for a source past a cap; `limit` names it ("limit of 3 per claim")."""
    return {"label": "NOT CHECKED", "quote": "", "tokens": 0, "over_limit": limit,
            "reason": limit[0].upper() + limit[1:] + "."}


def over_reason(per):
    """" 2 more sources not checked (limit of 3 per claim)." per cap that left some out."""
    by = {}
    for _, r in per:
        if r.get("over_limit"):
            by[r["over_limit"]] = by.get(r["over_limit"], 0) + 1
    return "".join(f" {k} more source{'s' if k > 1 else ''} not checked ({lim})." for lim, k in by.items())


def combine(claim, per, pages, context=""):
    """One claim result from its sources' results [(url, result)], in citation order.
    One source: that result unchanged (plus "sources"/"notes"). Several: labelled from the
    reachable ones (merge()); all unreachable -> SOURCE UNREACHABLE; the reason says how
    many couldn't be read, and "sources" lists each with its own outcome."""
    for u, r in per:
        page = pages.get(u) or {}
        if r["label"] not in GONE:
            add_pages(r, page)
            if page.get("meta_only"):
                r["reason"] = (r.get("reason", "") + META_NOTE).strip()
    per = [(u, thin_result(r) if (pages.get(u) or {}).get("meta_only") else r) for u, r in per]
    multi = len(per) > 1
    sources = [{"url": u, "label": r["label"], "reason": r.get("reason", ""),
                **({"detail": r["detail"]} if r.get("detail") else {}),
                **({"note": vague_note(u)} if vague_note(u) else {}),
                **({"model": r.get("model")} if multi and "model" in r else {})} for u, r in per]
    notes = list(dict.fromkeys(f"{vague_note(u)} ({site(u)})" if multi else vague_note(u)
                               for u, _ in per if vague_note(u)))
    tokens = sum(r.get("tokens", 0) for _, r in per)
    usable = [(u, r) for u, r in per if r["label"] not in GONE]
    if not multi:
        out = dict(per[0][1])
    elif not usable:
        tried = [r for _, r in per if not r.get("over_limit")]
        lost = [r for r in tried if r["label"] == "SOURCE UNREACHABLE"]
        out = ({"label": "SOURCE UNREACHABLE", "quote": "",
                "reason": f"None of the {len(tried)} sources could be read."} if len(lost) == len(tried)
               else {**next(r for r in tried if r["label"] == "NOT CHECKED")})
        out.pop("over_limit", None)
        out["reason"] += over_reason(per)
    elif len(usable) == 1:
        out = {k: v for k, v in usable[0][1].items() if k != "model"}
        for f in out.get("facts") or []:
            f["source"] = usable[0][0]
    else:
        out = merge(claim, usable, [pages[u]["text"] for u, _ in usable], context)
    if multi and usable:
        lost = sum(r["label"] == "SOURCE UNREACHABLE" for _, r in per)
        late = sum(r["label"] == "NOT CHECKED" and not r.get("over_limit") for _, r in per)
        if over := over_reason(per):
            out["reason"] = (out.get("reason", "") + over).strip()
        if lost:
            out["reason"] = (out.get("reason", "") + f" {lost} of {len(per)} sources couldn't be read.").strip()
        if late:
            out["reason"] = (out.get("reason", "") + f" {late} of {len(per)} sources not checked (time limit).").strip()
    if out.get("disagree"):
        notes = ["Sources disagree"] + notes   # one source states a fact another contradicts
    out.pop("disagree", None)
    if multi:
        out.pop("detail", None)              # per-source details live in "sources"
    out.update(tokens=tokens, sources=sources, notes=notes)
    return out


def audit(report, client, pages=None, max_claims=None, only=None, deadline=None,
          pacer=None, clock=time.monotonic, sleep=time.sleep, provider=None, max_urls=None):
    """Yield events as dicts:
      {"type": "start", "cited", "checked", "uncited", "site_only", "limit", "url_limit"}
         limit = max_claims or None; url_limit = max_urls or None; site_only = claims cited
         only by a ChatGPT chip whose link was lost (claim events with claim None and "site")
      {"type": "claim", "index", "claim", "text", "url", "urls", "label", "sources", "notes", ...}
         index = 1..checked; url = the first of urls (a claim may cite several); sources =
         [{url, label, reason, detail?, note?, model?}] one per URL, in citation order
         (uncited text comes as a claim event with claim None, index None, urls [])
         "hidden": N when ChatGPT's "+N" hid N sources (hidden_cap(): never red)
      {"type": "skipped", "claim", "text", "url", "urls", "label": "NOT CHECKED", "reason"}
         cited but over the claim cap, with every source past the URL cap, or not in `only`;
         no fetch, no tokens
      {"type": "wait", "seconds", "claim"}   waiting for the provider's per-minute capacity
         (pacer or a per-minute 429), then the same call is (re)sent
      {"type": "quota", "scope": "day"|"minute", "checked"}   the provider refused (429): audit
         stops, claims already checked are kept, the rest are not sent; then "done". "day"
         always stops; "minute" only without a deadline after MAX_MINUTE_RETRIES (with a
         deadline, waits that would pass it mark the rest NOT CHECKED instead)
      {"type": "done", "tokens"}
    pages: {url: fetch result dict}; if None, the selected claims' pages are fetched live.
    max_urls: distinct source URLs per audit, counted in report order over the selected
    claims (Gemini's cost scales with URLs, not claims). A claim keeps the sources inside the
    cap; one with none inside it is skipped ("Limit of N sources per audit.").
    deadline: clock() value, a hard wall clock for the whole audit: fetches (PDF parsing
    included) still running are cancelled, a model call still running is abandoned with its
    connection, and every claim not finished by then is NOT CHECKED ("Audit time limit
    reached."). Results already yielded stay.
    pacer: TokenPacer shared across audits (app.py); None = a fresh one for the provider.
    clock/sleep are injectable so tests never really wait.
    provider: providers.Groq (default, wraps `client`: one call per claim and source) or
    providers.Gemini (one call per cited page with its chosen claims, at most
    claims_per_call per call; a claim citing several pages joins each page's call). Results
    are yielded one claim at a time, in report order, each merged over its sources (combine())."""
    from providers import Groq
    provider = provider or Groq(client)
    pacer = pacer or TokenPacer.for_provider(provider.name, clock=clock)
    segs = blocks_meta(report)
    cited = [(t, us) for t, us, _, _ in segs if us]
    contexts = [c for _, us, c, _ in segs if us]
    site_only = sum(1 for _, us, _, m in segs if not us and m.get("site"))
    if only is not None:
        chosen = {i - 1 for i in only if 0 < i <= len(cited)}
    elif max_claims is not None:
        chosen = select(cited, max_claims)
    else:
        chosen = set(range(len(cited)))
    allowed, url_capped = None, set()
    if max_urls is not None:
        allowed = set(list(dict.fromkeys(u for i in sorted(chosen) for u in cited[i][1][:MAX_SOURCES]))[:max_urls])
        url_capped = {i for i in chosen if not allowed.intersection(cited[i][1][:MAX_SOURCES])}
        chosen -= url_capped
    checks = lambda i: [u for u in cited[i][1][:MAX_SOURCES] if allowed is None or u in allowed]
    yield {"type": "start", "cited": len(cited), "checked": len(chosen),
           "uncited": len(segs) - len(cited) - site_only, "site_only": site_only,
           "limit": max_claims, "url_limit": max_urls}

    if pages is None:
        urls = list(dict.fromkeys(u for i in sorted(chosen) for u in checks(i)))
        pages = dict(zip(urls, fetch_many(urls, within=None if deadline is None else deadline - clock())))

    tokens, n, index, out_of_capacity = 0, 0, 0, False
    batch = {}          # Gemini: (claim number, url) -> result, filled one cited page at a time
    per_call = getattr(provider, "claims_per_call", None) or 10**9
    for text, urls, context, chip in segs:
        if not urls and chip.get("site"):   # cited by a chip whose link was lost: never fetched
            yield {"type": "claim", "index": None, "claim": None, "text": text, "url": None, "urls": [],
                   "label": "NO SOURCE GIVEN", "quote": "", "site": chip["site"],
                   "reason": SITE_ONLY.format(chip["site"]), "tokens": 0}
            continue
        if not urls:      # uncited text: nothing to check, costs no tokens
            yield {"type": "claim", "index": None, "claim": None, "text": text, "url": None, "urls": [],
                   "label": "NO SOURCE GIVEN", "quote": "",
                   "reason": "The report gives no source for this.", "tokens": 0}
            continue
        n += 1
        if n - 1 not in chosen:
            reason = (f"Limit of {max_urls} sources per audit." if n - 1 in url_capped
                      else f"Limit of {max_claims} claims per audit." if only is None and max_claims is not None
                      else "")
            yield {"type": "skipped", "claim": n, "text": text, "url": urls[0], "urls": list(urls),
                   "label": "NOT CHECKED", "reason": reason}
            continue
        index += 1
        res = {u: over_limit(f"limit of {MAX_SOURCES} per claim") for u in urls[MAX_SOURCES:]}
        res |= {u: over_limit(f"limit of {max_urls} sources per audit")
                for u in urls[:MAX_SOURCES] if u not in checks(n - 1)}
        for url in checks(n - 1):
            page = pages.get(url) or {}
            meta = {"title": page.get("title"), "headings": page.get("headings")}
            if (n, url) in batch:
                r = batch.pop((n, url))
            elif page.get("status") == LATE:
                r = dict(NOT_CHECKED_TIME)            # its fetch was cut off by the deadline
            elif not page.get("text"):
                r = unreachable(page, url)
            elif out_of_capacity:
                r = dict(NOT_CHECKED_WAIT)
            elif deadline is not None and clock() > deadline:
                r = dict(NOT_CHECKED_TIME)
            elif provider.per_source:
                # Gemini: this page's first claim. Send every remaining chosen claim citing it,
                # claims_per_call per call; claims with no passage on the page are UNVERIFIED
                # without the model.
                group = [m for m in sorted(chosen) if m + 1 >= n and url in checks(m)
                         and (m + 1, url) not in batch]
                send = [m for m in group if best_excerpts(cited[m][0], page["text"])]
                for m in group:
                    if m not in send:
                        batch[(m + 1, url)] = dict(NO_PASSAGE)
                late = None
                for k in range(0, len(send), per_call):
                    part = send[k:k + per_call]
                    if late:
                        results = [dict(NOT_CHECKED_WAIT if late == "wait" else NOT_CHECKED_TIME) for _ in part]
                        batch.update({(m + 1, url): res_ for m, res_ in zip(part, results)})
                        continue
                    claims = [cited[m][0] for m in part]
                    outcome, got = yield from attempt(
                        lambda t, claims=claims: provider.ask_source(claims, page["text"], t), pacer,
                        provider.estimate(claims, page["text"]), deadline, clock, sleep, n)
                    if outcome == "quota":
                        yield {"type": "quota", "scope": got, "checked": index - 1}
                        yield {"type": "done", "tokens": tokens}
                        return
                    if outcome == "ok":       # code checks outside the retries (C1)
                        results, used = provider.finish_source(got, claims, page["text"], url, meta,
                                                               [contexts[m] for m in part])
                        pacer.record(used)
                    elif outcome == "late":
                        late = got
                        out_of_capacity = out_of_capacity or got == "wait"
                        results = [dict(NOT_CHECKED_WAIT if got == "wait" else NOT_CHECKED_TIME) for _ in part]
                    else:
                        results = [error_result(got) for _ in part]
                    batch.update({(m + 1, url): res_ for m, res_ in zip(part, results)})
                r = batch.pop((n, url))
            else:
                outcome, got = yield from attempt(
                    lambda t: provider.ask(text, page["text"], t), pacer, None,
                    deadline, clock, sleep, n)
                if outcome == "quota":
                    # Out of capacity: every later claim would fail the same way. Stop cleanly
                    # instead of sending one error card per remaining claim.
                    yield {"type": "quota", "scope": got, "checked": index - 1}
                    yield {"type": "done", "tokens": tokens}
                    return
                if outcome == "late":
                    out_of_capacity = out_of_capacity or got == "wait"
                    r = dict(NOT_CHECKED_WAIT if got == "wait" else NOT_CHECKED_TIME)
                else:
                    # code checks outside the retries (C1): their bugs are never retried
                    r = (provider.finish(got, text, page["text"], url, meta, context) if outcome == "ok"
                         else error_result(got))
                pacer.record(r["tokens"])
            res[url] = r
        r = combine(text, [(u, res[u]) for u in urls], pages, context)
        if chip.get("hidden"):
            r = {**hidden_cap(r, chip["hidden"]), "hidden": chip["hidden"]}
        tokens += r["tokens"]
        yield {"type": "claim", "index": index, "claim": n, "text": text, "url": urls[0],
               "urls": list(urls), **r}
    yield {"type": "done", "tokens": tokens}
