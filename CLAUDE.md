# Touchstone

Audits AI-generated research reports (Perplexity, ChatGPT, Gemini) claim by claim:
does each claim's own cited source actually support it? Built for Thirduni (AI build
program). Real users by Oct 15, 2026; final deadline late Oct 2026.

## Pipeline (Python 3.14, venv in .venv)
1. fetch_links.py REPORT: extract URLs, fetch pages (httpx + trafilatura), SSRF-safe
   (public IPs only, re-checked on every redirect). Writes fetch_results.json.
   PDFs (2026-10-10, pdf_text.py, pypdf: pure Python, maintained, no native deps; pdfminer.six
   extracts slightly better layouts but is slower and larger): content-type pdf, or a .pdf
   URL served as octet-stream. Hostile input: 15 MB download cap (Content-Length and while
   streaming), first 60 pages, parsed in a child process (`python -I pdf_text.py`) with
   RLIMIT_AS 512 MB + RLIMIT_CPU 20 s, killed after 20 s wall clock, one parse at a time
   process-wide (PARSE_LOCK, polled so the wait is cancellable; async subprocess killed when
   its fetch is cancelled at the audit deadline), outside the 30 s download clock. Encrypted (non-empty user password) ->
   "PDF is password-protected"; < 200 chars -> "PDF has no extractable text (likely
   scanned)". Lines are rejoined into paragraphs (prose lines 60+ chars; table rows and
   bullets never joined); "page_starts" keeps each page's offset so quotes show "p. N".
   Status codes: PDF_ERROR (detail = the reason). 401 joined BLOCK_STATUSES (reuters.com:
   401 + x-datadome). Detection only: blocks are never evaded.
2. check_numbers.py: copy_cleanup() first (ChatGPT copy button): HTML entities decoded (only
   with ';': "&copy=" in a URL stays), markdown "\&" unescaped, favicon chips
   ([image](...favicon...)) and the caption lines after them (a domain, "Reuters", "+1")
   dropped, chart-axis residue ("200¢/lb250¢/lb...") dropped. CHIPS (2026-10-14, ChatGPT search
   mode): a favicon chip (s2/favicons?domain=X) + caption + optional "+N" cites the block above
   it; X is resolved by registrable domain (www./subdomains ignored) to the report's own links
   (Sources list): 1-3 links -> cited (written as a "Source:" line; a link-less "Source: ANRT."
   line takes them, so a table above it is cited), 0 or > 3 -> pseudo-link CHIP_TAG+"site/X"
   -> NO SOURCE GIVEN card "The copied text only kept the site name (X)..." (never fetched, not
   in the uncited list; start event "site_only"). "+N" -> CHIP_TAG+"more/N" -> claim meta
   "hidden": hidden_cap() turns UNSUPPORTED/CONTRADICTED/UNVERIFIED into COULDN'T CONFIRM
   ("Also cites N more sources that weren't included in the copied text."), SOURCED unchanged;
   also on chips under already-cited lines (report5 claims 1-3, 8-12; claim 9 thus amber in a
   new audit). blocks_meta() = blocks_ctx() + meta; pseudo-links never leave it. Reference
   lists: SOURCES_HEADING also matches "Sources and further reading", Références,
   Bibliographie, "Sources et lectures (complémentaires)"...; reference_line() drops list lines
   that only name a source (no number, <= 8 words without links, capitalized or "Name —").
   Safety net checkable(): a cited text with no digit and < 4 words, or only capitalized
   words (a name), is dropped. Then resolve_footnotes() turns
   footnote citations ([1], [1][2], [^1], 【1】 + a numbered/bracketed source list or
   Sources/References section) into inline URLs and drops the source list; a run of markers
   gives the text ALL its sources; a marker with no source entry is text ("[2023]" stays). attach_sources(): a stat block (short label lines around
   number headings "# 354.32¢/lb"; numbered/year-led titles are not stats) becomes one claim
   per value ("February 2025 monthly average: 354.32¢/lb — US dollars: $3.54 per pound"); a
   "Source:"/"Sources:" line gives ALL its links to the block right above it (paragraph, stat
   block + a one-line caption under it, table: every row "Header: cell; Header: cell", list: every
   item; an INDENTED source line under a list goes to the last bullet only); French spacing
   "Source :" / "Sources :" (space, NBSP, U+202F) counts; text after its last link is a claim
   with those sources, the source name before them is not. blocks() returns (text, urls tuple); segments() = first URL only (app's
   zero-cited check, tests). Links separated only by connectors/punctuation ("[A] and [B]",
   "u1 u2") form one group: one claim, several sources; a trailing "Sources:" label is
   stripped from the claim; connector-only fragments ("and", ", and") are never claims.
   blocks() splits the report per line; a link group owns its line's text
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
   rapidfuzz partial_ratio >= 92 with identical numbers; unverified -> missing) inside ONE page
   line (paragraph, list item, table row, PDF block); a "..." quote's pieces must all be in
   that line, in order (2026-10-11 review L1: pieces anywhere could stitch a Tesla sentence to
   a BYD figure); paragraph_of() returns None for an unverified quote, never the quote itself,
   so no check runs on the model's own text. Then code derives
   the label: any contradicted -> CONTRADICTED, all stated -> SOURCED, some -> PARTIAL,
   none -> UNSUPPORTED. Framing never affects the label.
   COVERAGE (2026-10-11 L2): the model's parts must cover the claim. A non-year claim number
   in no part and no verified quote of that claim's results (product names keep digits the
   model paraphrases away: Renault 5, Model 3, A320), < 60% of the claim's content words (accents folded, filler words skipped) in
   the parts, or more than 12 facts (the first 12 are checked, never silently dropped) caps
   SOURCED at COULDN'T CONFIRM with the reason; amber only, never redder. Cross-language
   (2026-10-11): the prompt (shared RULES, both providers) asks for parts in the claim's
   language; if they still differ, the 60% word cap is skipped; the number rule stays.
   Fail-safe: skipped only if quote_check.language() confidently detects BOTH sides (>= 3
   function words of one language, >= 20% of the text's tokens with numbers counted, >= 3x
   the other language's), else None and the cap stays ("Algérie : 45 % en 2024" is None). Only the claim's
   OWN text counts: blocks_ctx() returns each claim's context (the ':' lead-in block joined
   before its line, "Top 5 Best-Selling EV Models ... (Recorded Jan-Oct 2025):"), which the
   model still sees and the year / numbers-on-page rules still use, but coverage doesn't
   require ("Renault 5" in the bullet itself still must be covered). audit() threads it
   through judge/merge/combine; rescore.py recomputes it from the run's saved report.
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
   A line over 400 chars (pages without line breaks) shows only the fewest sentences holding
   the match, "…" at cut edges (evidence_window; sentence_spans never splits "29.7", "M.",
   "U.S.", "etc." or French "vrai ?"); add_pages strips the "…" before finding a PDF page.
   Years (1900-2100) in a fact must be in its passage, the page title, the h1-h3 headings
   above the passage (its section path), or the quoted table row's header row / caption;
   never in footer text (lines with ©, "Copyright", "All rights reserved"). fetch_links
   stores "title" and "headings" ([[level, text]]) per page; caches made before 2026-10-09
   lack them, so years there are only found in the passage/table (stricter, amber).
   Any "unconfirmed" or "possible" fact keeps a claim from SOURCED (at best COULDN'T CONFIRM). judge() is the code-only half of
   check() (model reply -> label), so saved runs can be re-scored with zero tokens.
   Table rows (2026-10-13): a cited row "| Samsung | 18% | +3% [src](url) |" under "| Brand |
   Q2 2025 share | Trend |" + separator is ONE claim with all the row's links, every cell
   paired with its header: "Brand: Samsung; Q2 2025 share: 18%; Trend: +3%" (row_text;
   links stripped from cells, a link-only cell drops its column, empty header -> value alone,
   short rows pair what they have, "—" cells empty, minus signs kept; no separator row ->
   old " — " join; a blank line ends the header). Context = the header labels, one per line:
   own_text() strips "Label: ", so coverage asks only for the row's values.
   Period rule (2026-10-13, like years): Q1-Q4, H1/H2, T1-T4 (case-sensitive), 2Q25,
   "first/second... quarter|half", "premier/1er/deuxième/2e... trimestre|semestre" (one key:
   T2 = Q2 = "deuxième trimestre") in the claim must be in a stated fact's year_context
   (quote, paragraph, title, heading path, table header/caption), else SOURCED -> COULDN'T
   CONFIRM "Quote found, but the period Q2 is not in ...". Amber only: period codes are
   blanked in numbers_not_in (Q1 vs Q2 is never a value conflict, "2" of "Q2" never a
   key-term number) and are never names (entities GENERIC). merge(): capped only if every
   source stating a fact has the cap.
   Table columns (2026-10-13, column_check): a quoted row (or A2 line) that is a page table row
   ("| a | b |" or tab-separated) gets its header from the page (the row above |---|, same cell
   count; no separator -> the top row of the same-width run if it has no figure; else no check).
   A fact's period (its own; the claim's only if the claim has one figure; one year, <= 1
   quarter/half) picks columns. A fact figure found in the row ONLY under other-period columns:
   if exactly one column of the fact's period (same % kind; header words break ties) holds
   another figure -> "conflict" ("The page gives 18% for Q2 2025; 19% is its Q2 2024 figure."):
   CONTRADICTED when the model said contradicted/missing and the row's label cell ("Samsung")
   is named in the fact, unconfirmed if the model said stated (A1); else "elsewhere"
   ("This figure appears on the page under 'Q2 2024 share', not Q2 2025.") -> unconfirmed,
   never "possibly stated". A figure under a matching or period-free column (Brand, YoY), or
   not in the row at all, is left to the existing checks.
   Name check (entities.py, code-only): a "stated" fact's names (only the claim's names that
   appear in the fact's own text, plus the claim's lead name if the fact opens with It/The
   company) must be in the quote's paragraph or be the page's subject (2+ paragraphs);
   publisher names (domain) skipped. Else missing, or contradicted if the paragraph/quote/
   previous sentence opens with another unclaimed name ("about Moustachir, not VOLZ"; names
   keep their original casing). Technical acronyms in entities.ACRONYMS (PV, CSP, EV, GDP,
   IPO, AI, CO2, W/Wh units) are never names. A name acronym also counts as named when the
   passage spells it out in capitalized words (ASF = Algerian Startup Fund; IRENA != IEA).
   Demonyms/region adjectives (European, Algerian, North African...: entities.DEMONYMS) are
   never names on their own ("European Union" still is). Countries (2026-10-11,
   entities.COUNTRY_ROWS: 54 African countries + France, Spain, Italy, Germany, UK, USA, China,
   India, Turkey, Saudi Arabia, UAE, Qatar, Brazil, Japan, South Korea, Russia; EN name, EN
   adjective/demonym, FR name, FR adjective with fr_forms() m/f sg/pl): a country name counts
   as named by any of its forms as whole words, accents/case/hyphens ignored ("Algérie" =
   "Algerian market"), and only by a name meaning that country alone: the passage's country
   names are read longest-first ("South Sudan", "Guinée équatoriale", "DR Congo", "North
   Korea" are themselves, never Sudan/Guinea/Congo/Korea; North Korea and Papua New Guinea
   rows exist for this) and an ambiguous one ("Congolese": either Congo) never confirms
   (fail toward amber); "Niger" not in "Nigerian"; "=US", "=EAU" forms match exact case only
   (us, eau). The table's adjectives joined DEMONYMS. "About someone else" never fires
   when the fact's subject is in the passage (BYD's quote in a paragraph opening "Tesla").
   Prompt also requires facts to name their subject.
   Key-term check: a stated fact's numbers (single digits too, since 2026-10-11 L4: "$5
   million" vs "$3 million"; a digit written out, "one billion", counts) must be in its quote
   or the quote's paragraph, else unconfirmed. Page-wide checks keep 2+ digits. Number matching (claim-level "Numbers not on page" too) accepts
   a unit-scaled form (units.py): both numbers carry an explicit unit of one family
   (W/kW/MW/GW/TW + written-out; Wh..TWh; thousand/million/billion/trillion, k/M/bn/B), and
   the page number converts to the claim's at its stated precision, rounded or cut off
   (15,925 MW = 15.9 GW = 16 GW, not 17 GW; 3,267 MW = 3.2 or 3.3 GW). A number without a
   unit is never scaled. Locale numbers (locnum.py), used by every number comparison
   (claim-wide, per fact, units, quote matcher, excerpt keywords/anchors): a token is
   grouped (1-3 digits, then groups of exactly 3 after one separator kind: space, NBSP,
   U+202F, U+2009, ' or ’, '.', ',') or plain (digits with an optional ',' or '.' decimal).
   Each token gets every plausible reading: "1,234" = 1234, "545.142" = 545.142, plus the
   decimal-comma (1.234) / dot-thousands (545142) reading only when the text shows the
   European convention (locnum.european: "29,7", "1.234.567", "1.234,5"; per-fact checks use
   the whole page's convention); "29,7" = 29.7; space-grouped page tokens also yield each
   group only on a table-like line (a "|" row, a tab, or 3+ numbers and as many numbers as
   words, a grouped token counting once) and never if a group starts with 0, so "585" is not
   in "2 585 187" and "23" not in "1 023 456" (2026-10-11 L3/L5). Two numbers
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
3b. providers.py: PROVIDER=groq (default) | gemini (env; set per deployment, never default
   to gemini). Groq: one call per claim, ~3,000 chars of excerpts (unchanged). Gemini
   (gemini-3.5-flash-lite, verified in Google's model list 2026-10-09; google-genai SDK,
   temperature 0, seed 0, JSON with a response schema, max_output_tokens 32,768 of the
   model's 65,536, thinking on by default and counted in it): ONE call per cited page with
   every chosen claim citing it, in chunks of CLAIMS_PER_CALL (10) claims, the page text whole up to 100K chars (page_for_model: longer pages
   keep the claims' anchor passages and grow around them, "[...]" for gaps; lines verbatim
   so quotes verify). Prompt: SYSTEM_MULTI = same PREAMBLE + RULES as Groq's SYSTEM (shared
   verbatim; Groq's text is byte-identical), only the task statement asks for
   {"claims": [{"id", "opinion", "parts"}]}. map_results() maps ids to claims; a missing or
   malformed entry is that claim's ERROR. Every result goes through the same judge(): the
   model reports, code decides. Claims with no passage on the page are not sent (zero-token
   ui_check holds for both). Tokens of a call are split evenly over its claims.
   Pacing per provider (pacing.LIMITS): Groq 7,500 TPM; Gemini 225K TPM, 13 RPM, 450 RPD
   (under 250K/15/500), RPD used up -> stops like a per-day quota. Daily audit cap per
   provider: GLOBAL_AUDITS_PER_DAY (Groq, 7), GEMINI_AUDITS_PER_DAY (Gemini, 40).
   Eval: quote_check.py REPORT [CLAIMS] --provider groq|gemini --cache X.pages.json
   --out runs/NAME.json [--max-claims 10] [--show-raw]; compare_runs.py A.json B.json
   [--labels] compares two runs claim by claim; rescore.py reads both providers' runs.
   report4 estimate (first 10 claims): Gemini 2 requests, ~12.6K tokens; Groq 10 requests,
   ~17K tokens. Smoke test 2026-10-09 (2 claims, IANA page): 1 request, 798 tokens.
4. touchstone.py: audit(report, client, pages=None, max_claims=None, only=None, deadline=None,
   pacer=None, clock, sleep, provider=None, max_urls=None)
   max_urls (2026-10-13, Gemini 8): distinct source URLs per audit, counted in report order
   over the chosen claims; a claim with none inside -> skipped, reason "Limit of 8 sources per
   audit."; one with some -> checked against those, the rest NOT CHECKED in its sources
   ("1 more source not checked (limit of 8 sources per audit)."). Skipped events carry
   "reason"; start carries "url_limit".
   deadline = HARD wall clock (2026-10-13): fetch_many(within=left) cancels unfinished
   fetches (status LATE -> NOT CHECKED "Audit time limit reached."), PDF children killed;
   each model call runs in a thread (bounded()) with its request timeout = time left (Groq
   timeout=, Gemini http_options), abandoned at the deadline; < MIN_CALL_SECONDS (3) left ->
   not sent. Remaining claims/chunks NOT CHECKED "Audit time limit reached."
   is the importable pipeline. Multi-source claims (2026-10-10): the first MAX_SOURCES (3)
   sources of a claim (report order) are fetched and checked, the rest listed as NOT CHECKED
   and never fetched; the reason ends "N more source(s) not checked (limit of 3 per claim)": without the cap one claim line with 1,000 URLs made the server
   fetch them all (security review, SSRF/quota amplification); a web audit fetches at most
   10 x 3 = 30 URLs (Groq), 8 (Gemini). Each reachable source is
   checked (Groq: one call per claim AND source; Gemini: the claim joins each page's call),
   then combine(): one source -> its result unchanged; several -> quote_check.merge(): the
   most-supported source's fact list, each fact taking the best status any source gives the
   same fact (same_fact: identical numbers + token_set_ratio >= 80): "stated" if ANY source
   states it with a verified quote, "contradicted" only if one contradicts and none states;
   then the same verdict() (judge() = fact checks + verdict()), claim numbers checked against
   all pages. A fact one source states and another contradicts: "Sources disagree" (card note
   + reason), capped at COULDN'T CONFIRM (2026-10-11 L6). Some unreachable -> "1 of 3 sources couldn't be read"; all -> SOURCE
   UNREACHABLE. Claim events carry url (first), urls, sources [{url, label, reason, detail?,
   note?, model? (multi only: rescore replays it)}] and notes. Facts carry "source" (multi)
   and "page" (PDF). Vague citations (vague_note): path "/" -> "Cites a homepage, not a
   specific page"; a search/library path or filter keys with a query -> "Cites a listing
   page, not a document"; still checked. Unreachable reasons (unreachable()): bot block ->
   "<site> blocked the checker (bot protection or paywall)", other 401/403 -> "The site
   refused the checker (login, paywall or bot protection)", 404, timeout, PDF reasons...;
   the raw status ("HTTP_ERR 401") only in "detail" (card: "Details: ..."). Yields events: start {cited, checked, uncited, limit}, claim
   (one per segment, uncited ones with claim: null), skipped {label: NOT CHECKED}, done
   {tokens}. pages=None fetches live. max_claims keeps the FIRST N cited claims in report
   order (until 2026-10-09 it checked claims containing digits ahead of the others, which
   skipped claim 5 of report3 mid-report).
   quote_check.py's CLI is a thin wrapper over it (uses cached fetch_results.json).
5. app.py (FastAPI, run: .venv/bin/uvicorn app:app): GET / serves static/ (index.html, app.js,
   style.css, no framework; index.html is served with /static/<name>?v=<sha256[:12]>
   computed at startup: versioned URLs get "public, max-age=31536000, immutable", the page and
   unversioned URLs "no-cache"); POST /api/audit {report} streams NDJSON events; GET /api/example
   returns examples/demo.txt (Perplexity, Africa smartphones; Samsung 18% changed to 19%).
   "Try an example" (2026-10-13) loads it and replays examples/demo_run.json (GET
   /api/example-run: a "touchstone-run" v1 Download file, made by Anis from the live site and
   committed; 404 if missing/invalid) through the same resultsView()/renderCard() as a live
   audit: zero tokens, no limit. The page shows it only if its report equals demo.txt (trimmed),
   else the text alone. "Run it live" audits the box. Busy (another audit running): 503
   {"busy": true, error: BUSY_MSG} before rate_limited(), so the page retries every 15 s
   (countdown, Cancel) for up to 6 min without using the 5/hour limit, then "Still busy".
   Cards (reasonExtra): the grey reason line drops the pieces the rows already show
   ("Stated: ...", per-status lists, fact notes, "Framing not checked: ...", exact matches
   only) and is hidden when nothing is left. PROVIDER=gemini renders a plain bordered line (.notice) under the input,
   server-side into index.html (no endpoint, no keys): "Reports are processed by Google Gemini
   (free tier), which may use inputs to improve Google's products. Don't paste anything
   private." Groq shows nothing. Limits: 20,000 chars, app.CAPS per provider: Groq 10 cited claims,
   Gemini 25 claims + 8 distinct URLs (report order; the rest stream as "skipped" with their
   reason, shown collapsed as "Not checked (limit of 25 claims per audit; limit of 8 sources
   per audit): N claims", and the summary says "Checked X of N claims"; the page's limits
   line is rendered server-side at <!--limits--> by limits_line()),
   5 audits/IP/hour (IPv6: per /64) + GLOBAL_AUDITS_PER_DAY (7, UTC day, counted at an audit's first model call; in memory), one audit at a time (Groq TPM), 300 s hard wall clock per audit
   (fetching, PDF parsing, model calls; see 4), a {"type":"heartbeat"} line after 15 s of stream silence (the audit runs in
   its own thread, which owns the busy lock; app.js ignores heartbeats), 30 s Groq timeout; fetches: connect 15 s, read 15 s, 30 s hard wall clock per attempt (async,
   cancelled on expiry), a timed-out fetch retried once with read 30 s, both attempts within
   45 s per URL (2026-10-11; 30 URLs x 8 parallel <= 180 s) + 3 MB per fetched page. Strict CSP header.
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
   max_retries=0 (audit() retries: 429s as above, timeouts/5xx twice). Only the model call
   (provider.ask / ask_source) is retried; judge() runs once after it (finish / finish_source,
   safe_judge): a bug in the checks is ERROR "Internal check error.", tokens still counted. Retries never count
   twice toward the daily cap (CountingClient counts the first call attempt). The daily cap counts an audit at its first model call attempt.
   Client IP: X-Touchstone-Client-IP is trusted only if X-Touchstone-Proxy-Secret matches env
   PROXY_SECRET (hmac.compare_digest); else CLIENT_IP_HEADER (X-Real-IP), else the socket.
   Origin lockdown is opt-in: REQUIRE_PROXY_SECRET=1 refuses (403) every request without the
   secret (or with a malformed client IP) except /healthz and /healthz/proxy, each refusal
   logged with reason + path (never values); the app won't start with it set and no
   PROXY_SECRET. /healthz/proxy -> {"via_worker": bool}, reason of a false in the server log.
   2026-10-11 incident: unconditional enforcement (a40f4f4) answered 403 to the whole site
   while /healthz stayed green; rolled back. The code accepts a Worker-shaped request with
   the right secret (tests, real uvicorn): the header Railway got didn't match its
   PROXY_SECRET. Enable only via DEPLOY.md's procedure.
   fetch_links: httpx trust_env=False (no env proxies); a private IP shows only as "private
   address", never the address.
   Unreadable pages (2026-10-14): extracted text < 500 chars (was 200), or < 1500 with a
   JS/cookie-wall phrase (fetch_links.SHELL) -> meta fallback, else NO_TEXT -> SOURCE
   UNREACHABLE "The page loaded but its content couldn't be read (it may need JavaScript)."
   (before: 200-500-char pages were judged and could be UNSUPPORTED). A meta_only page's
   UNSUPPORTED/CONTRADICTED/UNVERIFIED -> that same SOURCE UNREACHABLE (thin_result).
   Bot protection (fetch_links.bot_blocked): cf-mitigated: challenge, Cloudflare challenge
   titles, or a 403/429/503 with Cloudflare/DataDome/Akamai/PerimeterX markers -> BLOCKED
   "blocked the checker (bot protection)" -> SOURCE UNREACHABLE, never sent to the model.
6. cloudflare/worker.js: the public entry point, https://touchstone.aynx.dev (Worker custom
   domain; workers.dev + Preview URLs disabled; user -> Worker -> Railway, permanently, since
   Ooredoo reaches Railway only intermittently). The railway.app URL is never shared.
   Strips client copies of the two X-Touchstone headers, sets them from CF-Connecting-IP and env.PROXY_SECRET; 500 "misconfigured" without ORIGIN_HOST/PROXY_SECRET.
   The Railway hostname is never in the repo: only in the Worker's ORIGIN_HOST variable.
Parsing regexes must stay linear: every repeated group starts with a literal, whitespace
runs are capped (a nested \s* marker regex once hung the server on 20,000 spaces). Never
put a required suffix after a repeated group in one regex run over page text: units.py's
"number then unit" was quadratic (8,000 digit groups: 28 s); match the number with
NUMBER_RE, then .match() the suffix at its end (same for MD_LINK: URL, then LINK_END). Number tokens over 30 digits get no reading.
Report parsing runs in a thread pool, never on the event loop.
Dependencies: requirements.txt. Token-free checks: .venv/bin/python test_parsing.py (parsing,
bot-page fixtures on a mocked transport, claim cap order, report4 junk passages and
parentheses, report5's pinned claim list + copy-format rules), test_pdf.py (generated
text/encrypted/blank PDFs, size/time/memory limits, page numbers, the real ICO report cached in
gitignored testdata/), test_sources.py (merge rules, partly/fully unreachable, Groq + Gemini
multi-source, vague notes, unreachable reasons, rescore of a multi-source claim), test_checks.py (unit-scaled and locale numbers, name check scope/acronyms, countries vs
demonyms, cross-language coverage, A2 evidence window,
VOLZ/Moustachir, anchor passage selection, rescore.py end to end) and
test_security.py (network: rebinding, TLS, SSRF blocks; client IP + proxy secret, table
pruning, heartbeat with a fake slow model, examples/ui_check.txt makes no model call,
cache-busting headers, fetch timeout retry, provider line). examples/ui_check.txt = DEPLOY.md's zero-token UI check on production.
(samples/ holds hand-made reports: footnotes, names-only sources, no links).
Labels: SOURCED / PARTIAL / COULDN'T CONFIRM / UNSUPPORTED / CONTRADICTED / UNVERIFIED / OPINION / SOURCE UNREACHABLE /
NO SOURCE GIVEN / NOT CHECKED / ERROR. Verdicts judge factual parts only; editorial framing is noted, not penalized.

## Rules
- GROQ_API_KEY and GEMINI_API_KEY live in .env (local) / the host's sealed variables only.
  Never in code, prompts, logs, or git.
- PROXY_SECRET (openssl rand -hex 32) lives only in Railway's variables and the Worker's
  secrets. Never in code, git, logs, chats or prompts; never ask Anis to paste it.
- Page text is untrusted (prompt injection). Keep it delimited; never put secrets in prompts.
- Never commit fetch_results.json, runs/, testdata/ or *.pages.json (copies of other sites' pages),
  or audit.json (the CLI's run output; untracked and gitignored since 2026-10-11).
- Free tier: Groq 30 RPM, 1K RPD, 8K TPM, 200K tokens/day. ~900 tokens per claim.
  Gemini 3.5 Flash Lite (free, per project): 15 RPM, 250K TPM, 500 RPD. Free-tier Gemini API
  content may be used by Google to improve its products (check the current terms).
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

## Fresh report 5 (2026-10-10, production): report5.txt, ChatGPT copy button, coffee prices
Production: 9 of 10 checked claims SOURCE UNREACHABLE (6 ICO PDFs unsupported, Reuters 401),
3 junk claims ("and", ", and", "Sources:"). Fixed 2026-10-10 (PDFs, copy format, multi-source,
vague notes, friendly reasons). Now 21 cited claims; of the first 10, 7 reach the model (3 are
Reuters, blocked). Zero-token check: "December 2025: 304.68¢/lb" is in none of its 3 cited
reports, and claim 8's 304.68 is not in the November report. No hand labels yet; report5 has
been seen while fixing parsing, so it is a REGRESSION set for parsing, not an accuracy eval.

## Held-out accuracy set (2026-10-10): heldout/perplexity.txt, heldout/gemini_fr.txt
Parse-only check so far (no fetch, no model call, pages never opened): perplexity 12 cited
claims (lead, 6 table rows, 4 bullets, final note) + 1 uncited; gemini_fr 7 cited (one per
bullet) + 1 uncited. gemini_fr's claim 1 carries the list's lead-in ("Voici les chiffres
clés..., accompagnés de leurs sources :") by the ':' lead-in rule; not changed, since the same
rule gives report4's first EV-model bullet its "Jan–Oct 2025" context. Never tune code on
these two files' content; they are for the next accuracy eval (hand labels + 2 runs).

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
   Deployed 2026-10-08 (a *.up.railway.app domain, named only in the Worker's ORIGIN_HOST; 1 replica, CLIENT_IP_HEADER=
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
