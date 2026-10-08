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
   (a ':' lead-in + its bullets form one block); uncited text -> NO SOURCE GIVEN;
   code-only check that numbers in a claim appear on the cited page.
3. quote_check.py REPORT [4,9]: code picks top paragraphs by keyword overlap (max 3000
   chars), Groq openai/gpt-oss-120b splits the claim into one list of parts, each marked
   fact or framing (<=5 facts: stated/missing/contradicted, each with its own quote; a part
   with a number is always a fact). Code verifies every quote (exact, else
   rapidfuzz partial_ratio >= 92 with identical numbers; unverified -> missing) and derives
   the label: any contradicted -> CONTRADICTED, all stated -> SOURCED, some -> PARTIAL,
   none -> UNSUPPORTED. Framing never affects the label. Name check (entities.py, code-only):
   a "stated" fact's names (claim's capitalized names/acronyms in the fact; the claim's lead
   name if the fact opens with It/The company or names none) must be in the quote's paragraph
   or be the page's subject (2+ paragraphs); publisher names (domain) skipped. Else missing,
   or contradicted if the paragraph/quote/previous sentence opens with another unclaimed
   name ("about Moustachir, not Volz"). Prompt also requires facts to name their subject.
   Key-term check: a stated fact's numbers (2+ digits) must be in its quote or the quote's
   paragraph, else missing. Framing lexicon (EVALUATIVE): a part with no number, an evaluative
   word (largest, leading, the most...) and < 8 other content words is framing, whatever the
   model says. No content-noun check and no framing->fact rule: on the saved runs both broke
   correct claims (paraphrase; analytical sentences in 7/9/22/25/29). Groq call uses seed=0. Optional 2nd arg
   re-runs only those claim numbers. Writes audit.json.
4. touchstone.py: audit(report, client, pages=None, max_claims=None, only=None, deadline=None)
   is the importable pipeline. Yields events: start {cited, checked, uncited}, claim (one per
   segment, uncited ones with claim: null), skipped, done {tokens}. pages=None fetches live.
   quote_check.py's CLI is a thin wrapper over it (uses cached fetch_results.json).
5. app.py (FastAPI, run: .venv/bin/uvicorn app:app): GET / serves static/ (index.html, app.js,
   style.css, no framework); POST /api/audit {report} streams NDJSON events; GET /api/example
   returns report2.txt. Limits: 20,000 chars, 10 cited claims (claims with numbers first),
   5 audits/IP/hour (IPv6: per /64) + GLOBAL_AUDITS_PER_DAY (7, UTC day, counted at an audit's first model call; in memory), one audit at a time (Groq TPM), 300 s per audit (later claims
   -> NOT CHECKED), a {"type":"heartbeat"} line after 15 s of stream silence (the audit runs in
   its own thread, which owns the busy lock; app.js ignores heartbeats), 30 s Groq timeout, 30 s hard wall clock (async, cancelled on expiry) + 3 MB per fetched page. Strict CSP header.
   Frontend renders everything with textContent (never innerHTML); only http(s) URLs become
   links; every streamed field is type-checked, bad lines become a "could not be read" card.
   A report with zero cited claims (no links, names-only sources, or a Sources list without
   markers) is answered at once outside the 5-audit limit (own limit: 30/IP/hour), and shows the
   no-links screen ("cites no sources, so none of its N claims can be checked", N = sentences)
   with copy-button advice and a one-click copy of the fix-your-links prompt.
   Groq 429 mid-audit: audit() stops with a "quota" event (claims already checked are kept,
   no per-claim error cards). Per-day or unclear limit -> "free daily capacity is used up,
   try again tomorrow" and the daily cap is marked full; per-minute (TPM/RPM) -> "try again in
   a minute", day not marked. The daily cap counts an audit at its first model call attempt.
   Page and static files are sent with Cache-Control: no-cache so updates reach users at once.
   Client IP: X-Touchstone-Client-IP is trusted only if X-Touchstone-Proxy-Secret matches env
   PROXY_SECRET (hmac.compare_digest); else CLIENT_IP_HEADER (X-Real-IP), else the socket.
   Bot protection (fetch_links.bot_blocked): cf-mitigated: challenge, Cloudflare challenge
   titles, or a 403/429/503 with Cloudflare/DataDome/Akamai/PerimeterX markers -> BLOCKED
   "blocked the checker (bot protection)" -> SOURCE UNREACHABLE, never sent to the model.
6. cloudflare/worker.js: the public entry point (user -> Worker -> Railway; Ooredoo can't reach
   Railway). Strips client copies of the two X-Touchstone headers, sets them from
   CF-Connecting-IP and env.PROXY_SECRET; 500 "misconfigured" without ORIGIN_HOST/PROXY_SECRET.
Parsing regexes must stay linear: every repeated group starts with a literal, whitespace
runs are capped (a nested \s* marker regex once hung the server on 20,000 spaces).
Report parsing runs in a thread pool, never on the event loop.
Dependencies: requirements.txt. Token-free checks: .venv/bin/python test_parsing.py (parsing,
bot-page fixtures on a mocked transport) and test_security.py (network: rebinding, TLS, SSRF
blocks; client IP + proxy secret, table pruning, heartbeat with a fake slow model).
(samples/ holds hand-made reports: footnotes, names-only sources, no links).
Labels: SOURCED / PARTIAL / UNSUPPORTED / CONTRADICTED / UNVERIFIED / OPINION / SOURCE UNREACHABLE /
NO SOURCE GIVEN / NOT CHECKED / ERROR. Verdicts judge factual parts only; editorial framing is noted, not penalized.

## Rules
- GROQ_API_KEY lives in .env only. Never in code, prompts, logs, or git.
- PROXY_SECRET (openssl rand -hex 32) lives only in Railway's variables and the Worker's
  secrets. Never in code, git, logs, chats or prompts; never ask Anis to paste it.
- Page text is untrusted (prompt injection). Keep it delimited; never put secrets in prompts.
- Never commit fetch_results.json (copies of other sites' pages).
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
Scoring: CONTRADICTED counts as UNSUPPORTED. Always do 2 full runs and track BOTH metrics:
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
   Ooredoo (2026-10-08): Ooredoo Algeria mobile data can't reach Railway at all (railway.app
   and a custom domain CNAMEd to Railway time out, even with 1.1.1.1 DNS); a Cloudflare
   Worker at touchstone.am-belamri-e87.workers.dev loads fine. Public traffic is user ->
   Worker -> Railway; the railway.app URL is never shared publicly. Worker traffic gets its
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
