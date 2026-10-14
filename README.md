# Touchstone

Paste an AI research report (ChatGPT, Perplexity, Gemini). Touchstone opens every cited page and checks whether it actually says what the report claims — and shows the exact quote as proof.

Live: https://touchstone.aynx.dev. "Try an example" replays a saved run instantly (no model call, no wait).

## The problem

Students use ChatGPT, Perplexity and Gemini for research. The citations in those reports often don't support the claim they sit next to, and checking every link by hand is slow, so most people don't.

Our own small tests, not a study: we asked all three the same question ("internet access and the digital economy in Algeria", 14 Oct 2026).

- Gemini gave 18 citations. Of the 13 pages we could open, at most 2 supported the claim. It cited the 2024 edition of a report for 2026 figures, attributed UNCTAD figures to the World Bank, and cited bare homepages.
- Perplexity cited a page for figures that page doesn't contain.
- ChatGPT was mostly accurate, but its copied text drops the actual links, so the citations can't be followed from the pasted report.

## How it works

The model reports, the code decides.

1. Parse the report into claims and the links each claim cites (inline links, footnotes, "Source:" lines, tables, ChatGPT's copied favicon chips).
2. Fetch the cited pages (HTML and PDF), public addresses only.
3. The model splits each claim into facts and proposes a quote from the page for each fact.
4. Code verifies that each quote exists verbatim on the page (or as a near-exact match with identical numbers), then checks numbers (rounding, units, locale formats, qualifiers like "over" or "nearly"), table columns, periods (Q2, H1), years and names.
5. Code assigns the label.

Code alone never accuses: a red label needs the model's judgement plus a conflicting value verified on the page. When only a code check doubts a fact, the result is amber (COULDN'T CONFIRM), not red.

## Labels

| Label | Meaning |
|---|---|
| SOURCED | Every fact in the claim is stated on the cited page, with a verified quote. |
| PARTIAL | Some facts are stated on the page, others are not found. |
| COULDN'T CONFIRM | The model found support, but a code check doubts it (a number, period, name or coverage gap), sources disagree, or the citation is a homepage. |
| UNSUPPORTED | None of the claim's facts are stated on the cited page. |
| CONTRADICTED | The model says the page contradicts the claim and a verified quote holds a conflicting figure. |
| NO SOURCE GIVEN | The text cites nothing (or the copied text kept only a site name). |
| SOURCE UNREACHABLE | The cited page couldn't be read: blocked, not found, timed out, password-protected or scanned PDF, or content that needs JavaScript. |
| UNVERIFIED | No relevant passage on the page, no checkable fact identified, or the model's quotes aren't on the page. |
| OPINION | Advice or opinion, not a checkable fact. |
| NOT CHECKED | Over the per-audit limits, or the audit time limit was reached. |
| ERROR | The model's reply couldn't be read, or an internal check failed. |

Editorial framing ("dramatic", "robust") is noted, not penalized: verdicts judge factual parts only.

## Accuracy, honestly

Held-out test on 2 reports we had never tuned on, with labels written before running: with Gemini, 10 of 11 checkable claims were labelled correctly in both runs, with zero false greens and zero false reds. This is a small sample.

Later tests (ChatGPT, Perplexity and Gemini reports on 14 Oct 2026) were development checks used to find and fix bugs, not held-out results.

Touchstone checks whether the cited source says what the report claims, not whether the source itself is right.

## Known limits

- Relative dates ("the previous year") aren't resolved.
- A country implied only by a national site's domain isn't counted as named.
- Some stat-block layouts leave stats unchecked.
- Lookalike domains can satisfy "according to X" name checks.
- JavaScript-only pages and sites that block bots come back SOURCE UNREACHABLE.
- Qualitative claims depend on the model's reading.
- A year anywhere in a quote softens a different-date red's wording.
- English and French only.
- Limits of 25 claims and 8 sources per audit, 5 audits per hour.

## Run it locally

Requires Python 3.14.

```
git clone <this repo> touchstone
cd touchstone
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`: set `PROVIDER` (`gemini` or `groq`) and the matching key (`GEMINI_API_KEY` or `GROQ_API_KEY`). The app builds a Groq client at startup, so `GROQ_API_KEY` must be set (any placeholder works when `PROVIDER=gemini`).

Start the web app (same command as production, on a local port):

```
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers
```

Run the tests (no model calls, no keys needed beyond the placeholder above):

```
.venv/bin/python run_tests.py
TOUCHSTONE_OFFLINE=1 .venv/bin/python run_tests.py   # skip the checks that need live sites
```

Audit a report from the command line:

```
.venv/bin/python quote_check.py report.txt --provider gemini --max-claims 10
.venv/bin/python quote_check.py report.txt 4,9 --provider groq --cache report.pages.json --out runs/report_groq.json
```

The optional second argument re-runs only those claim numbers. `--cache` stores fetched pages (default `fetch_results.json`); never commit it, it holds copies of other sites' pages.

## Architecture

- `app.py`: FastAPI app: serves the page, streams audit events, rate limits, proxy-secret check.
- `touchstone.py`: the audit pipeline: claim selection, fetching, model calls, deadlines, multi-source merge.
- `check_numbers.py`: report parsing: claims, links, footnotes, Source lines, tables, stat blocks.
- `fetch_links.py`: SSRF-safe page fetching and text extraction, bot-block detection.
- `pdf_text.py`: PDF text extraction in a resource-limited child process.
- `quote_check.py`: excerpt selection, prompt, quote verification and the label logic (`judge()`).
- `providers.py`: Groq and Gemini clients and calls.
- `entities.py`: name, acronym, country and attribution checks.
- `units.py`, `locnum.py`: unit scaling, rounding and locale number readings.
- `pacing.py`: per-provider token and request pacing.
- `rescore.py`, `compare_runs.py`: replay saved runs through the current checks; compare two runs.
- `static/`: the web page (plain HTML, CSS, JavaScript).
- `cloudflare/worker.js`: the public entry point.

Deployment: the app runs on Railway (EU region) behind a Cloudflare Worker. The Worker sets a client-IP header and a shared secret on every request; with `REQUIRE_PROXY_SECRET=1` the app refuses any request that doesn't carry the secret, so direct traffic to the origin is rejected. See `DEPLOY.md`.

## AI use

- Google Gemini runs inside the product: it splits claims into facts and proposes the quote for each fact. Code verifies everything it returns and decides the label.
- Groq (openai/gpt-oss-120b) was tested and compared as an alternative provider and is still supported.
- The code was written with Claude Code. Planning, review and evaluation design were done with Claude. Several commits carry a Claude co-author trailer.
- Humans chose the design, wrote the evaluation labels, ran and judged the evaluations, and deployed it.

## Team

The git history has one author (git name `aynxitis`), who made all 62 commits and touched every file.

## License

MIT. See `LICENSE`.
