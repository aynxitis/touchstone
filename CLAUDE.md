# Touchstone

Audits AI-generated research reports (Perplexity, ChatGPT, Gemini) claim by claim:
does each claim's own cited source actually support it? Built for Thirduni (AI build
program). Real users by Oct 15, 2026; final deadline late Oct 2026.

## Pipeline (Python 3.14, venv in .venv)
1. fetch_links.py REPORT: extract URLs, fetch pages (httpx + trafilatura), SSRF-safe
   (public IPs only, re-checked on every redirect). Writes fetch_results.json.
2. check_numbers.py: resolve_footnotes() first turns footnote citations ([1], [1][2], [^1],
   【1】 + a numbered/bracketed source list or Sources/References section) into inline URLs
   and drops the source list; a run of markers gives the text its FIRST source only.
   segments() splits the report per line; a link owns its line's text
   (a ':' lead-in + its bullets form one block); uncited text -> NO SOURCE GIVEN; passages
   with no letter or digit (the "." after "([Name](url)).") and rules (---, ***, ___) are
   dropped; link stripping keeps balanced parentheses ("(+23.9%) ([Eleport](url))" ->
   "(+23.9%)");
   code-only check that numbers in a claim appear on the cited page.
3. quote_check.py REPORT [4,9]: best_excerpts() picks passages (max 3000 chars total) from
   passages(): paragraphs > 30 chars, plus the short list items / table rows (<= 30 chars,
   a number after the list marker) the 30-char rule used to drop ("- Tesla Model Y: 116 989"),
   grouped per run with up to 2 short lines before it (heading, lead-in) and a table's
   header; it
   first, per anchor of the claim (titles in quotes/*italics*/_underscores_, organisation
   names + acronyms, 2+ digit numbers incl. unit-scaled), the best-scoring paragraph holding
   it if it fits; then the rest by keyword overlap while they fit (until 2026-10-09 keyword
   overlap only, which dropped report3 claim 2's "analysis of IRENA's ..." sentence), Groq openai/gpt-oss-120b splits the claim into one list of parts, each marked
   fact or framing (<=5 facts: stated/missing/contradicted, each with its own quote; a part
   with a number is always a fact). Code verifies every quote (exact, else
   rapidfuzz partial_ratio >= 92 with identical numbers; unverified -> missing) and derives
   the label: any contradicted -> CONTRADICTED, all stated -> SOURCED, some -> PARTIAL,
   none -> UNSUPPORTED. Framing never affects the label.
   SAFEGUARDS (2026-10-09, fresh-report errors were all too harsh):
   A1 a code heuristic alone never accuses. A fact the model found "stated" with a verified
   quote that a code check (numbers, units, years, names) rejects becomes "unconfirmed"
   ("couldn't confirm" + the check's reason); the framing lexicon never overrules such a
   fact. A claim whose only doubts are unconfirmed/possible facts (or claim numbers not on
   the page) is COULDN'T CONFIRM (amber, new label, scored as PARTIAL: PARTIAL means some
   fact is not found; this means the model found it and code doubts it). CONTRADICTED needs
   the model's "contradicted" AND a verified quote with a conflicting figure
   (value_conflict: a non-year number on each side the other lacks); otherwise "missing".
   A2 full-page fallback: a "missing" fact whose non-year numbers (one with 2+ digits) and
   subject (first claim name in the fact) all sit on one page line becomes "possible"
   ("possibly stated", the line shown as evidence), never counted as not found. No model call.
   Years (1900-2100) only have to be somewhere on the page, not in the figure's passage
   (table rows sit under "Sales 2025"); cost: a date is no longer tied to its passage. judge() is the code-only half of
   check() (model reply -> label), so saved runs can be re-scored with zero tokens.
   Name check (entities.py, code-only): a "stated" fact's names (only the claim's names that
   appear in the fact's own text, plus the claim's lead name if the fact opens with It/The
   company) must be in the quote's paragraph or be the page's subject (2+ paragraphs);
   publisher names (domain) skipped. Else missing, or contradicted if the paragraph/quote/
   previous sentence opens with another unclaimed name ("about Moustachir, not VOLZ"; names
   keep their original casing). Technical acronyms in entities.ACRONYMS (PV, CSP, EV, GDP,
   IPO, AI, CO2, W/Wh units) are never names. A name acronym also counts as named when the
   passage spells it out in capitalized words (ASF = Algerian Startup Fund; IRENA != IEA).
   Demonyms/region adjectives (European, Algerian, North African...: entities.DEMONYMS) are
   never names on their own ("European Union" still is). "About someone else" never fires
   when the fact's subject is in the passage (BYD's quote in a paragraph opening "Tesla").
   Prompt also requires facts to name their subject.
   Key-term check: a stated fact's numbers (2+ digits) must be in its quote or the quote's
   paragraph, else missing. Number matching (claim-level "Numbers not on page" too) accepts
   a unit-scaled form (units.py): both numbers carry an explicit unit of one family
   (W/kW/MW/GW/TW + written-out; Wh..TWh; thousand/million/billion/trillion, k/M/bn/B), and
   the page number converts to the claim's at its stated precision, rounded or cut off
   (15,925 MW = 15.9 GW = 16 GW, not 17 GW; 3,267 MW = 3.2 or 3.3 GW). A number without a
   unit is never scaled. Locale numbers (locnum.py), used by every number comparison
   (claim-wide, per fact, units, quote matcher, excerpt keywords/anchors): a token is
   grouped (1-3 digits, then groups of exactly 3 after one separator kind: space, NBSP,
   U+202F, U+2009, ' or ’, '.', ',') or plain (digits with an optional ',' or '.' decimal).
   Each token gets every plausible reading: "1,234"/"545.142" = thousands or decimal;
   "29,7" = 29.7; space-grouped page tokens also yield each group (table rows). Two numbers
   match if any readings are equal (unit-scaled: at the claim's precision). A 4-digit start
   never groups, so "2025 2 585 187" is 2025 and 2585187. Reasons quote the number as the
   claim wrote it ("2,585,187 not in its passage"). Framing lexicon (EVALUATIVE): a part with no number, an evaluative
   word (largest, leading, the most...) and < 8 other content words is framing, whatever the
   model says, EXCEPT a ranking/superlative (RANKING: best, best-selling, largest, top, #1,
   leading, the most...) in a part naming one of the claim's entities: "X was the
   best-selling Y" is a fact (2026-10-09: "best" inside "best-selling" had demoted VW's
   stated fact, report4-part2 claim 5 UNSUPPORTED -> PARTIAL on rescore). Framing = colour
   with nothing to verify (strong, robust, dramatic, massive, struggled). No content-noun check and no framing->fact rule: on the saved runs both broke
   correct claims (paraphrase; analytical sentences in 7/9/22/25/29). Groq call uses seed=0. Optional 2nd arg
   re-runs only those claim numbers. Writes audit.json. Each claim result carries "model"
   (the model's sanitized reply; None if unparseable) so judge() can replay it.
4. touchstone.py: audit(report, client, pages=None, max_claims=None, only=None, deadline=None)
   is the importable pipeline. Yields events: start {cited, checked, uncited, limit}, claim
   (one per segment, uncited ones with claim: null), skipped {label: NOT CHECKED}, done
   {tokens}. pages=None fetches live. max_claims keeps the FIRST N cited claims in report
   order (until 2026-10-09 it checked claims containing digits ahead of the others, which
   skipped claim 5 of report3 mid-report).
   quote_check.py's CLI is a thin wrapper over it (uses cached fetch_results.json).
5. app.py (FastAPI, run: .venv/bin/uvicorn app:app): GET / serves static/ (index.html, app.js,
   style.css, no framework; index.html is served with /static/<name>?v=<sha256[:12]>
   computed at startup: versioned URLs get "public, max-age=31536000, immutable", the page and
   unversioned URLs "no-cache"); POST /api/audit {report} streams NDJSON events; GET /api/example
   returns report2.txt. Limits: 20,000 chars, 10 cited claims (first 10 in report order; the
   rest stream as "skipped" and show collapsed as "Not checked (limit of 10 per audit)", and
   the summary says "Checked X of N claims"),
   5 audits/IP/hour (IPv6: per /64) + GLOBAL_AUDITS_PER_DAY (7, UTC day, counted at an audit's first model call; in memory), one audit at a time (Groq TPM), 300 s per audit (later claims
   -> NOT CHECKED), a {"type":"heartbeat"} line after 15 s of stream silence (the audit runs in
   its own thread, which owns the busy lock; app.js ignores heartbeats), 30 s Groq timeout, 30 s hard wall clock (async, cancelled on expiry) + 3 MB per fetched page. Strict CSP header.
   After an audit, a "Download results" button saves the run as JSON, built client-side
   from the received events (no server storage): report, every claim event (facts, quotes,
   statuses, label, reason, URL, model reply), not_checked, uncited, tokens, timestamp.
   Frontend renders everything with textContent (never innerHTML); only http(s) URLs become
   links; every streamed field is type-checked, bad lines become a "could not be read" card.
   A report with zero cited claims (no links, names-only sources, or a Sources list without
   markers) is answered at once outside the 5-audit limit (own limit: 30/IP/hour), and shows the
   no-links screen ("cites no sources, so none of its N claims can be checked", N = sentences)
   with copy-button advice and a one-click copy of the fix-your-links prompt.
   Groq 429 mid-audit: audit() stops with a "quota" event (claims already checked are kept,
   no per-claim error cards). Per-day or unclear limit -> "free daily capacity is used up,
   try again tomorrow" and the daily cap is marked full. Per-minute limits no longer stop an
   audit (pacing.py, 2026-10-09; a live run had stopped after 5 claims): a TokenPacer shared
   by the process tracks tokens of the trailing 60 s (response usage) and waits before a
   call that would pass 7,500; a per-minute 429 waits its retry-after (header, else "try
   again in Xs", else 10 s; +0.5 s, max 60 s) and resends the same claim. Each wait streams
   {"type":"wait","seconds","claim"} -> "Waiting for capacity... (Xs)", a live countdown that
   any later status replaces and that never survives the audit's end; heartbeats continue.
   A wait that would pass the 300 s deadline isn't taken: the rest are NOT CHECKED. Groq SDK
   max_retries=0 (audit() retries: 429s as above, timeouts/5xx twice). Retries never count
   twice toward the daily cap (CountingClient counts the first call attempt). The daily cap counts an audit at its first model call attempt.
   Client IP: X-Touchstone-Client-IP is trusted only if X-Touchstone-Proxy-Secret matches env
   PROXY_SECRET (hmac.compare_digest); else CLIENT_IP_HEADER (X-Real-IP), else the socket.
   Bot protection (fetch_links.bot_blocked): cf-mitigated: challenge, Cloudflare challenge
   titles, or a 403/429/503 with Cloudflare/DataDome/Akamai/PerimeterX markers -> BLOCKED
   "blocked the checker (bot protection)" -> SOURCE UNREACHABLE, never sent to the model.
6. cloudflare/worker.js: the public entry point, https://touchstone.aynx.dev (Worker custom
   domain; workers.dev + Preview URLs disabled; user -> Worker -> Railway, permanently, since
   Ooredoo reaches Railway only intermittently). The railway.app URL is never shared.
   Strips client copies of the two X-Touchstone headers, sets them from CF-Connecting-IP and env.PROXY_SECRET; 500 "misconfigured" without ORIGIN_HOST/PROXY_SECRET.
Parsing regexes must stay linear: every repeated group starts with a literal, whitespace
runs are capped (a nested \s* marker regex once hung the server on 20,000 spaces). Never
put a required suffix after a repeated group in one regex run over page text: units.py's
"number then unit" was quadratic (8,000 digit groups: 28 s); match the number with
NUMBER_RE, then .match() the suffix at its end. Number tokens over 30 digits get no reading.
Report parsing runs in a thread pool, never on the event loop.
Dependencies: requirements.txt. Token-free checks: .venv/bin/python test_parsing.py (parsing,
bot-page fixtures on a mocked transport, claim cap order, report4 junk passages and
parentheses), test_checks.py (unit-scaled and locale numbers, name check scope/acronyms,
VOLZ/Moustachir, anchor passage selection, rescore.py end to end) and
test_security.py (network: rebinding, TLS, SSRF blocks; client IP + proxy secret, table
pruning, heartbeat with a fake slow model, examples/ui_check.txt makes no model call,
cache-busting headers). examples/ui_check.txt = DEPLOY.md's zero-token UI check on production.
(samples/ holds hand-made reports: footnotes, names-only sources, no links).
Labels: SOURCED / PARTIAL / COULDN'T CONFIRM / UNSUPPORTED / CONTRADICTED / UNVERIFIED / OPINION / SOURCE UNREACHABLE /
NO SOURCE GIVEN / NOT CHECKED / ERROR. Verdicts judge factual parts only; editorial framing is noted, not penalized.

## Rules
- GROQ_API_KEY lives in .env only. Never in code, prompts, logs, or git.
- PROXY_SECRET (openssl rand -hex 32) lives only in Railway's variables and the Worker's
  secrets. Never in code, git, logs, chats or prompts; never ask Anis to paste it.
- Page text is untrusted (prompt injection). Keep it delimited; never put secrets in prompts.
- Never commit fetch_results.json, runs/ or *.pages.json (copies of other sites' pages).
- Free tier: Groq 30 RPM, 1K RPD, 8K TPM, 200K tokens/day. ~900 tokens per claim.
  Re-run only the claims you're debugging.
- Never present a verdict as stronger than the evidence. Honesty is the product.

## Eval so far (report2.txt, Algeria startup ecosystem, 29 claims)
labels2.json = 13 ground-truth labels, made by Claude from the cited pages via a web
tool. Human spot-check of claims 3, 8, 26 still pending.
Touchstone caught 3/3 real problems (3, 8, 26: all real numbers attributed to the wrong
source; 26 = Moustachir's IPO credited to VOLZ).
labels2.json is now the TUNING SET (issues 1-2 were fixed against it). The next eval must
use a fresh report with fresh labels, or the score is overfitted.
Scoring: CONTRADICTED counts as UNSUPPORTED; COULDN'T CONFIRM counts as PARTIAL. Always do 2 full runs and track BOTH metrics:
- accuracy per run: labeled claims correct (out of 13 for report2)
- run agreement: how many of the cited claims get the identical label in both runs
Results on report2 (2 full runs each, ~41-44K tokens per run):
- 2026-10-08, name check: accuracy 12/13 and 10/13; run agreement 24/29
- 2026-10-08, + meta fallback, number key-term check, framing lexicon, seed=0:
  accuracy 12/13 and 11/13; run agreement 27/29 (28/29 if CONTRADICTED = UNSUPPORTED).
  Misses: claim 2 PARTIAL both runs (meta description has the figures, not the methodology
  sentence; the label was made from the rendered page, so PARTIAL is honest for what we
  fetch); claim 29 once (model called a long analytical sentence a fact).
TUNING ON REPORT2 IS CLOSED (2026-10-08). Every number above is on the tuning set and
optimistic. The next eval is a fresh report with fresh labels, scored with both metrics.
Claim 1 label corrected SOURCED -> PARTIAL (2026-10-07) after re-checking the source: the
page names tax advantages and public procurement, not public funding.
2026-10-09: re-scored the saved run (audit.json) through judge() after the units/name-check
changes below: no label or reason changed (11/13 on that run, same as before). Same again
after locale numbers + parsing fixes (also no excerpt or report2 segment changed).

## Re-scoring production runs (zero tokens)
After a change to the code checks, never re-run audits to see its effect: download the run
from the web page ("Download results") and run
  .venv/bin/python rescore.py RUN.json --cache NAME.pages.json [--labels labelsN.json]
It re-fetches the cited pages (or reads the cache; *.pages.json is gitignored: copies of
other sites' pages), replays each claim's saved model reply through the current judge(),
and prints old -> new label per claim (+ accuracy vs hand labels). It works on the CLI's
audit.json too (older runs without "model" are rebuilt from their facts). It cannot measure
changes to excerpt selection or the prompt (the model's reply is fixed), and a page that
changed since the run can move a label by itself. Claims judged without a model call are
re-scored only if the page still offers no passage.

## Fresh-report eval 1 (2026-10-09, production): report3.txt, North African renewables
Perplexity report, 18 cited claims; production checked 10 (1-4, 6-11: the old numbers-first
cap skipped claim 5, which has no digits). labels3.json: 10 hand labels (those claims, 5 not
labelled) verified against the live pages. With the report-order cap, a default audit now
checks 1-10: claim 5 is in (unlabelled), claim 11 is out; use only=1-11 to replay all labels. Result 6/9 scorable (67%;
target 85%; claim 4 SOURCE UNREACHABLE not scored). All 3 errors were false alarms from code
checks: unit-scaled numbers ("15.9 GW" vs "15,925 MW") and the name check (whole-claim
scope + "PV" read as a name, "Pv not named in its passage"). Both fixed 2026-10-09.
report3 is now a REGRESSION SET, not an eval set: it has been seen.

## Fresh-report eval 2 (2026-10-09, production): report4.txt, Gemini, EV sales in Europe
22 cited claims, 2 uncited sentences. Scored 3/10: all 7 errors were false UNSUPPORTED from
locale numbers (eleport.com writes "2 585 187", "29,7%"; the report "2,585,187", "29.7%").
Also: 19 junk "." passages in the uncited list and "(+23.9%" truncation. All fixed
2026-10-09 (locnum.py, segments()). No hand labels file yet. report4 is now a REGRESSION
set too; re-score the production run with rescore.py, then the next eval is a fresh report. The next eval must use
fresh reports run after these fixes, scored with both metrics.

## Open issues, in order
1. DONE: Claims 4 and 9 false rejections. Cause: U+2011 hyphens and '...'-shortened quotes; fixed in
   normalize() + piece-by-piece matching; fuzzy matches must keep the passage's numbers.
2. DONE: Parsing. Per-line segments, ':' lead-in + bullets = one block, markdown stripped,
   uncited text -> NO SOURCE GIVEN (claim: null in audit.json; cited claims keep numbers 1-29).
3. Thin pages: upgrowth.dz is ~700 chars of a JS page, so claims 18-20 get UNSUPPORTED.
   Pages under ~1500 chars should yield SOURCE INCOMPLETE instead.
4. DONE (2026-10-08): JS pages. Body < 200 chars -> title + meta description (>= 50 chars) as
   the page text, flagged meta_only; verdicts then say "Judged from the page's meta
   description only". Fixes claim 2 (StartupBlink) and aventure.dz.
5. Excerpt-only judgments: reasons should say "not in the checked passages", not
   "not on the page".
6. (Low priority) Weak excerpt selection: claim 4 picks unrelated quotes (VOLZ/forex) for a
   list-of-verticals claim; keyword overlap ranks the wrong paragraphs.
7. DONE: Framing duplicated as facts. The model returns one list of parts marked fact|framing,
   so nothing is listed twice; fuzzy dedup removed. Tested on 1, 3, 22, 23 only: full re-run
   still pending (do it twice, see Scoring).
8. DONE (2026-10-08): Subject dropped from facts (claim 26 SOURCED via "It was the first...").
   Fixed by the name check in entities.py + prompt. 23-26 twice: 23-25 SOURCED, 26
   CONTRADICTED both runs. Known limit: a name on a multi-topic page that appears in 2+
   paragraphs passes as "page subject" unless the quoted paragraph opens with another name.
9. DONE (2026-10-08): pre-deploy security. fetch connects to the IP check_url validated
   (Host header + TLS SNI keep the hostname; certs still verified); client IP comes from
   CLIENT_IP_HEADER (Railway: X-Real-IP), never X-Forwarded-For's spoofable leftmost
   entry (why uvicorn --forwarded-allow-ips='*' is not used); limits key IPv6 by /64
   (address rotation); GLOBAL_AUDITS_PER_DAY (7) caps audits across all visitors, refused up
   front, counted at an audit's first model call attempt (a count of starts let token-free
   audits lock everyone out; counting reported tokens failed open on errors); --workers 1; rate-limit tables
   pruned every 5 min; /healthz; "waking up" notice + a host's HTML loading page never parsed.
   Hosting (2026-10-08): Railway full trial (Render needed a card), EU West Amsterdam.
   railpack.json pins Python 3.14 + start command; dashboard sets healthcheck, region,
   variables (Railway Config as Code / railway.json is deprecated for new services).
   Deployed 2026-10-08 (touchstone-project.up.railway.app, 1 replica, CLIENT_IP_HEADER=
   X-Real-IP). Verified: Railway overwrites X-Real-IP (31 forged requests: 30x200, then 429).
   Ooredoo: reaching Railway is intermittent (railway.app and a custom domain CNAMEd to
   Railway timed out on 2026-10-08 even with 1.1.1.1 DNS, worked on 2026-10-09); the
   Cloudflare Worker loads fine, so it stays permanently. Public URL (2026-10-09):
   https://touchstone.aynx.dev, a Worker custom domain (aynx.dev DNS moved from Name.com to
   Cloudflare; portfolio records DNS-only); workers.dev and Preview URLs disabled. Public
   traffic is user -> Worker -> Railway; the railway.app URL is never shared.
   Known minor issue: an app redirect (e.g. /static -> /static/) would send users to
   railway.app (Location names the origin); not triggered today. Worker traffic gets its
   own buckets via the PROXY_SECRET handshake (DEPLOY.md: secret, deploy order, forged-header
   tests direct + through the Worker, mobile test on Ooredoo/Mobilis/Djezzy with VPNs and DNS
   apps off). VPN users (WARP) with rotating exit IPs get extra buckets: accepted for the
   MVP, the daily cap protects the Groq budget.
10. Fallback if abuse happens after launch: invite codes for pilot users (audit requires a
   valid server-side code, per-code daily quota). Not built: IP limits can't stop a multi-IP
   abuser, and a per-IP daily limit was rejected (2026-10-08) because Algerian campus Wi-Fi
   and mobile carriers put many users behind one IP. Same risk for the 5/hour per-IP limit:
   raise RATE_LIMIT if pilot users hit it without running 5 audits themselves.
After each fix: re-run the affected claims, compare with labels2.json, commit.

## Working style
The developer (Anis) wants direct, blunt answers. Explain each change in a sentence or
two, then do it. Commit after each working fix.
