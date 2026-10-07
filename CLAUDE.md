# Touchstone

Audits AI-generated research reports (Perplexity, ChatGPT, Gemini) claim by claim:
does each claim's own cited source actually support it? Built for Thirduni (AI build
program). Real users by Oct 15, 2026; final deadline late Oct 2026.

## Pipeline (Python 3.14, venv in .venv)
1. fetch_links.py REPORT: extract URLs, fetch pages (httpx + trafilatura), SSRF-safe
   (public IPs only, re-checked on every redirect). Writes fetch_results.json.
2. check_numbers.py: claims_with_sources() pairs each text chunk with the link after it;
   code-only check that numbers in a claim appear on the cited page.
3. quote_check.py REPORT [4,9]: code picks top paragraphs by keyword overlap (max 3000
   chars), Groq openai/gpt-oss-120b returns {verdict, quote, reason}, code confirms the
   quote is on the page (exact, else rapidfuzz partial_ratio >= 92). Optional 2nd arg
   re-runs only those claim numbers. Writes audit.json.
Labels: SOURCED / PARTIAL / UNSUPPORTED / UNVERIFIED / OPINION / SOURCE UNREACHABLE.

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
source; 26 = Moustachir's IPO credited to VOLZ). False flags: 1 (parsing) and 9 (quote match).

## Open issues, in order
1. DONE: Claims 4 and 9 false rejections. Cause: U+2011 hyphens and '...'-shortened quotes; fixed in
   normalize() + piece-by-piece matching; fuzzy matches must keep the passage's numbers.
2. Parsing: uncited text gets merged into the next claim (claim 1). Only the paragraph
   directly before a link belongs to it; uncited text gets NO SOURCE GIVEN.
   Also strip markdown headings, table pipes and stray characters from claims.
3. Thin pages: upgrowth.dz is ~700 chars of a JS page, so claims 18-20 get UNSUPPORTED.
   Pages under ~1500 chars should yield SOURCE INCOMPLETE instead.
4. JS pages: read the meta description as a fallback (StartupBlink's data is only there).
5. Excerpt-only judgments: reasons should say "not in the checked passages", not
   "not on the page".
6. (Low priority) Weak excerpt selection: claim 4 picks unrelated quotes (VOLZ/forex) for a
   list-of-verticals claim; keyword overlap ranks the wrong paragraphs.
After each fix: re-run the affected claims, compare with labels2.json, commit.

## Working style
The developer (Anis) wants direct, blunt answers. Explain each change in a sentence or
two, then do it. Commit after each working fix.
