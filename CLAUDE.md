# Touchstone

Audits AI-generated research reports (Perplexity, ChatGPT, Gemini) claim by claim:
does each claim's own cited source actually support it? Built for Thirduni (AI build
program). Real users by Oct 15, 2026; final deadline late Oct 2026.

## Pipeline (Python 3.14, venv in .venv)
1. fetch_links.py REPORT: extract URLs, fetch pages (httpx + trafilatura), SSRF-safe
   (public IPs only, re-checked on every redirect). Writes fetch_results.json.
2. check_numbers.py: segments() splits the report per line; a link owns its line's text
   (a ':' lead-in + its bullets form one block); uncited text -> NO SOURCE GIVEN;
   code-only check that numbers in a claim appear on the cited page.
3. quote_check.py REPORT [4,9]: code picks top paragraphs by keyword overlap (max 3000
   chars), Groq openai/gpt-oss-120b splits the claim into one list of parts, each marked
   fact or framing (<=5 facts: stated/missing/contradicted, each with its own quote; a part
   with a number is always a fact). Code verifies every quote (exact, else
   rapidfuzz partial_ratio >= 92 with identical numbers; unverified -> missing) and derives
   the label: any contradicted -> CONTRADICTED, all stated -> SOURCED, some -> PARTIAL,
   none -> UNSUPPORTED. Framing never affects the label. Optional 2nd arg
   re-runs only those claim numbers. Writes audit.json.
Labels: SOURCED / PARTIAL / UNSUPPORTED / CONTRADICTED / UNVERIFIED / OPINION / SOURCE UNREACHABLE /
NO SOURCE GIVEN. Verdicts judge factual parts only; editorial framing is noted, not penalized.

## Rules
- GROQ_API_KEY lives in .env only. Never in code, prompts, logs, or git.
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
Scoring: CONTRADICTED counts as UNSUPPORTED. Single runs vary by 1-2 labels from model
randomness alone: compare scores across at least 2 runs, never one.
The next real eval is a FRESH report with fresh labels (labels2.json is the tuning set).
Claim 1 label corrected SOURCED -> PARTIAL (2026-10-07) after re-checking the source: the
page names tax advantages and public procurement, not public funding.

## Open issues, in order
1. DONE: Claims 4 and 9 false rejections. Cause: U+2011 hyphens and '...'-shortened quotes; fixed in
   normalize() + piece-by-piece matching; fuzzy matches must keep the passage's numbers.
2. DONE: Parsing. Per-line segments, ':' lead-in + bullets = one block, markdown stripped,
   uncited text -> NO SOURCE GIVEN (claim: null in audit.json; cited claims keep numbers 1-29).
3. Thin pages: upgrowth.dz is ~700 chars of a JS page, so claims 18-20 get UNSUPPORTED.
   Pages under ~1500 chars should yield SOURCE INCOMPLETE instead.
4. JS pages: read the meta description as a fallback (StartupBlink's data is only there).
5. Excerpt-only judgments: reasons should say "not in the checked passages", not
   "not on the page".
6. (Low priority) Weak excerpt selection: claim 4 picks unrelated quotes (VOLZ/forex) for a
   list-of-verticals claim; keyword overlap ranks the wrong paragraphs.
7. DONE: Framing duplicated as facts. The model returns one list of parts marked fact|framing,
   so nothing is listed twice; fuzzy dedup removed. Tested on 1, 3, 22, 23 only: full re-run
   still pending (do it twice, see Scoring).
After each fix: re-run the affected claims, compare with labels2.json, commit.

## Working style
The developer (Anis) wants direct, blunt answers. Explain each change in a sentence or
two, then do it. Commit after each working fix.
