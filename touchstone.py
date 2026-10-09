"""Touchstone as a library: audit(report) yields one result per claim, in report order.
Used by the CLI (quote_check.py) and the web app (app.py)."""
import math
import re
import time

from check_numbers import segments
from fetch_links import BOT_BLOCKED, fetch_many
from pacing import DAY_FULL, TokenPacer, retry_after
from quote_check import best_excerpts

MAX_MINUTE_RETRIES = 5     # per claim, only without a deadline (CLI); with one, the deadline decides
MAX_ERROR_RETRIES = 2      # timeouts, connection errors, 5xx: what the SDK's own retries did
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


def attempt(call, pacer, need, deadline, clock, sleep, n):
    """Run one model call with pacing and retries. A generator: yields "wait" events, and
    returns (outcome, value): ("ok", result) | ("late", None) when a needed wait would pass
    the deadline | ("quota", "day"|"minute") when the audit must stop | ("error", exception).
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
                return "late", None
            yield {"type": "wait", "seconds": math.ceil(wait), "claim": n}
            sleep(wait)
            continue
        pacer.note_request()
        try:
            return "ok", call()
        except Exception as e:
            scope = quota_scope(e)
            if scope == "day" or (scope == "minute" and deadline is None
                                  and minute_tries >= MAX_MINUTE_RETRIES):
                return "quota", scope
            if scope == "minute":
                minute_tries += 1
                wait = retry_after(e)
                if deadline is not None and clock() + wait > deadline:
                    return "late", None
                yield {"type": "wait", "seconds": math.ceil(wait), "claim": n}
                sleep(wait)
                continue
            if transient(e) and error_tries < MAX_ERROR_RETRIES:
                error_tries += 1
                sleep(error_tries)
                continue
            return "error", e


def audit(report, client, pages=None, max_claims=None, only=None, deadline=None,
          pacer=None, clock=time.monotonic, sleep=time.sleep, provider=None):
    """Yield events as dicts:
      {"type": "start", "cited", "checked", "uncited", "limit"}   limit = max_claims or None
      {"type": "claim", "index", "claim", "text", "url", "label", ...}   index = 1..checked
         (uncited text comes as a claim event with claim None, index None)
      {"type": "skipped", "claim", "text", "url", "label": "NOT CHECKED"}   cited but over
         the cap / not in `only`; no fetch, no tokens
      {"type": "wait", "seconds", "claim"}   waiting for Groq's per-minute capacity (pacer or a
         per-minute 429), then the same claim is (re)sent
      {"type": "quota", "scope": "day"|"minute", "checked"}   Groq refused (429): audit stops,
         claims already checked are kept, the rest are not sent; then "done". "day" always
         stops; "minute" only without a deadline after MAX_MINUTE_RETRIES (with a deadline,
         waits that would pass it mark the rest NOT CHECKED instead)
      {"type": "done", "tokens"}
    pages: {url: fetch result dict}; if None, the selected claims' pages are fetched live.
    deadline: clock() value; claims not started by then are marked NOT CHECKED.
    pacer: TokenPacer shared across audits (app.py); None = a fresh one for the provider.
    clock/sleep are injectable so tests never really wait.
    provider: providers.Groq (default, wraps `client`: one call per claim) or
    providers.Gemini (one call per cited page with all its chosen claims; results are
    still yielded one claim at a time, in report order)."""
    from providers import Groq
    provider = provider or Groq(client)
    pacer = pacer or TokenPacer.for_provider(provider.name, clock=clock)
    segs = segments(report)
    cited = [(t, u) for t, u in segs if u]
    if only is not None:
        chosen = {i - 1 for i in only}
    elif max_claims is not None:
        chosen = select(cited, max_claims)
    else:
        chosen = set(range(len(cited)))
    yield {"type": "start", "cited": len(cited), "checked": len(chosen),
           "uncited": len(segs) - len(cited), "limit": max_claims}

    if pages is None:
        urls = list(dict.fromkeys(cited[i][1] for i in sorted(chosen)))
        pages = dict(zip(urls, fetch_many(urls)))

    tokens, n, index, out_of_capacity = 0, 0, 0, False
    batch = {}          # Gemini: claim number -> result, filled one cited page at a time
    for text, url in segs:
        if url is None:   # uncited text: nothing to check, costs no tokens
            yield {"type": "claim", "index": None, "claim": None, "text": text, "url": None,
                   "label": "NO SOURCE GIVEN", "quote": "",
                   "reason": "The report gives no source for this.", "tokens": 0}
            continue
        n += 1
        if n - 1 not in chosen:
            yield {"type": "skipped", "claim": n, "text": text, "url": url, "label": "NOT CHECKED"}
            continue
        index += 1
        page = pages.get(url) or {}
        meta = {"title": page.get("title"), "headings": page.get("headings")}
        if n in batch:
            r = batch.pop(n)
        elif out_of_capacity:
            r = dict(NOT_CHECKED_WAIT)
        elif deadline is not None and clock() > deadline:
            r = dict(NOT_CHECKED_TIME)
        elif not page.get("text"):
            why = " ".join(x for x in (page.get("status"), page.get("detail")) if x)
            reason = f"Could not read the page ({why})." if why else ""
            if page.get("detail") == BOT_BLOCKED:
                reason = f"The site {BOT_BLOCKED}."
            r = {"label": "SOURCE UNREACHABLE", "quote": "", "reason": reason, "tokens": 0}
        elif provider.per_source:
            # Gemini: this page's first claim. Send every remaining chosen claim citing it in
            # one call; claims with no passage on the page are UNVERIFIED without the model.
            group = [m for m in sorted(chosen) if m + 1 >= n and cited[m][1] == url and m + 1 not in batch]
            send = [m for m in group if best_excerpts(cited[m][0], page["text"])]
            for m in group:
                if m not in send:
                    batch[m + 1] = dict(NO_PASSAGE)
            if send:
                claims = [cited[m][0] for m in send]
                outcome, got = yield from attempt(
                    lambda: provider.check_source(claims, page["text"], url, meta), pacer,
                    provider.estimate(claims, page["text"]), deadline, clock, sleep, n)
                if outcome == "quota":
                    yield {"type": "quota", "scope": got, "checked": index - 1}
                    yield {"type": "done", "tokens": tokens}
                    return
                if outcome == "ok":
                    results, used = got
                    pacer.record(used)
                elif outcome == "late":
                    out_of_capacity, results = True, [dict(NOT_CHECKED_WAIT) for _ in send]
                else:
                    results = [error_result(got) for _ in send]
                batch.update({m + 1: res for m, res in zip(send, results)})
            r = batch.pop(n)
        else:
            outcome, got = yield from attempt(
                lambda: provider.check(text, page["text"], url, meta), pacer, None,
                deadline, clock, sleep, n)
            if outcome == "quota":
                # Out of capacity: every later claim would fail the same way. Stop cleanly
                # instead of sending one error card per remaining claim.
                yield {"type": "quota", "scope": got, "checked": index - 1}
                yield {"type": "done", "tokens": tokens}
                return
            if outcome == "late":
                out_of_capacity, r = True, dict(NOT_CHECKED_WAIT)
            else:
                r = got if outcome == "ok" else error_result(got)
            pacer.record(r["tokens"])
        if page.get("meta_only") and page.get("text"):
            r["reason"] = (r.get("reason", "") + " Judged from the page's meta description only "
                           "(the page body loads with JavaScript).").strip()
        tokens += r["tokens"]
        yield {"type": "claim", "index": index, "claim": n, "text": text, "url": url, **r}
    yield {"type": "done", "tokens": tokens}
