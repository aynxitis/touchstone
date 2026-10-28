# Touchstone

Paste an AI research report (ChatGPT, Perplexity, Gemini). Touchstone opens every cited page and checks whether it actually says what the report claims — and shows the exact quote as proof.

Live: the landing page is at https://touchstone.aynx.dev and the app at https://touchstone.aynx.dev/app. "Try the example" replays a saved run (no model call).

## The problem

We built this after hitting the problem ourselves. While doing market research for a project in October 2026, I asked ChatGPT for gaps in a market; it answered confidently, with sources that were years out of date or didn't say what it claimed. Checking each link by hand is exactly the work Touchstone does for you.

Students use ChatGPT, Perplexity and Gemini for research. The citations in those reports often don't support the claim they sit next to, and checking every link by hand is slow, so most people don't.

Our own small tests, not a study: we asked all three the same question ("internet access and the digital economy in Algeria", 14 Oct 2026).

- Gemini gave 18 citations. Of the 13 citations we could check, at most 2 were backed by the cited page. It cited the 2024 edition of a report for 2026 figures, attributed UNCTAD figures to the World Bank, and cited bare homepages.
- Perplexity cited a page for figures that page doesn't contain (possibly because Perplexity's copied text dropped some of its sources).
- ChatGPT was mostly accurate, but its copied text replaces inline links with site icons; Touchstone maps them back to the full links listed at the end of the report.

## How it works

The model reports, the code decides.

1. Parse the report into claims and the links each claim cites (inline links, footnotes, "Source:" lines, tables, ChatGPT's copied favicon chips).
2. Fetch the cited pages (HTML and PDF), public addresses only.
3. The model splits each claim into facts and proposes a quote from the page for each fact.
4. Code verifies that each quote exists verbatim on the page (or as a near-exact match with identical numbers), then checks numbers (rounding, units, locale formats, qualifiers like "over" or "nearly"), table columns, periods (Q2, H1), years and names.
5. Code assigns the label.

Red always rests on a conflicting value found on the page: either the model's quote, confirmed word for word, gives a different figure or date, or the claim's own row and period column in a table on the page gives a different figure. When the model finds a fact stated and only a code check doubts it, the result is amber (COULDN'T CONFIRM), never red.

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

## Use it from an AI agent

Touchstone is also a remote MCP server with one tool, `check_claims`: an agent sends the claims it is about to make, each with the URLs it cites, and gets a label per claim before it answers. The server is at `https://touchstone.aynx.dev/mcp`. It needs no sign-in or API key.

- **claude.ai:** Customize → Connectors → Add custom connector, URL `https://touchstone.aynx.dev/mcp`, no sign-in.
- **Claude Code:** `claude mcp add --transport http touchstone https://touchstone.aynx.dev/mcp`
- **ChatGPT, Cursor:** untested. Any client that supports remote MCP servers over Streamable HTTP should work.

Limits: 5 claims per call (1 to 3 URLs each, 5 distinct URLs), about 90 seconds per call, one call at a time, and 15 calls a day (up to 5 claims each) shared by everyone (separate from the website's limits). Labels are the same as on the website. Text copied from the pages or written by the checking model comes only in fields named `untrusted_*`, so the agent can treat it as data.

Claims and the text of the cited pages are processed by Google Gemini's free tier, which may use them to improve Google's products. Don't send anything private.

## Accuracy, honestly

Held-out test on 2 reports we had never tuned on, with labels written before running: with Gemini, 10 of 11 checkable claims were labelled correctly in both runs, with zero false greens and zero false reds. This is a small sample.

Later tests (ChatGPT, Perplexity and Gemini reports on 14 Oct 2026) were development checks used to find and fix bugs, not held-out results.

Testing the MCP server surfaced a false-green path in claims with several sources: when one cited page contradicted a claim that another cited page supported, the claim could come out SOURCED. That is now fixed and covered by tests.

Touchstone checks whether the cited source says what the report claims, not whether the source itself is right.

## Known limits

- Relative dates ("the previous year") aren't resolved.
- A country implied only by a national site's domain isn't counted as named.
- Some stat-block layouts leave stats unchecked.
- Lookalike domains can satisfy "according to X" name checks.
- JavaScript-only pages and sites that block bots come back SOURCE UNREACHABLE.
- Qualitative claims depend on the model's reading.
- A year anywhere in a quote softens a different-date red's wording.
- When a copied report drops some of its citations (ChatGPT's '+1' chips, possibly Perplexity), Touchstone can only check the sources that are visible.
- English and French only.
- Limits of 25 claims and 8 sources per audit, 5 audits per hour.

## Run it locally

Requires Python 3.14.

```
git clone https://github.com/aynxitis/touchstone.git touchstone
cd touchstone
python dev.py
```

That is the whole setup: `dev.py` creates `.venv` and installs `requirements.txt` on the first
run, then starts the same entry point as production (`uvicorn app:app`) with `--reload`.

- `http://127.0.0.1:8031/` — the landing page (`landing/`)
- `http://127.0.0.1:8031/app` — the app itself

Options: `python dev.py --port 9000`, `python dev.py --no-reload`. Without a `.env` the app
starts on the default provider and the "Try an example" replay works (no key, no model call);
real checks need `GEMINI_API_KEY` or `GROQ_API_KEY`. Copy `.env.example` to `.env` and set
`PROVIDER` to match.

Production sets the provider the same way and runs
`uvicorn app:app --host 0.0.0.0 --port $PORT --workers 1 --no-proxy-headers` (see
`railpack.json`); there is deliberately no `package.json`, so Railway's builder keeps
detecting a Python app.

Run the tests (no model calls, no keys needed):

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

- `app.py`: FastAPI app: serves the landing page at `/` and the app at `/app`, streams audit events, rate limits, proxy-secret check.
- `dev.py`: the one command for local runs: bootstraps `.venv`, then starts `uvicorn app:app` with `--reload`.
- `mcp_server.py`: the remote MCP server (`check_claims` at `POST /mcp`), on only with `MCP_ENABLED=1`.
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

## What's next

- "Find a source": for claims with no source or a failed one, search the web neutrally, check what's found with the same strict rules, and show whether other pages support it, contradict it, or say nothing.
- A second opinion from a stronger model on amber claims, with the code still deciding the label.
- MCP: bring your own Gemini key, sent in a request header and never stored, so heavy users don't share the daily 15.
- MCP: a quote-supplied mode, where the agent sends the quote it relies on with each claim and Touchstone verifies it on the page with code checks only, at no model cost.
- Bring your own Gemini key on the website, kept in the browser for one session and never stored.
- Arabic support.
- A larger held-out test: fresh reports, labels written before running, so the accuracy figure rests on more than 11 claims.

## AI use

- Google Gemini runs inside the product: it splits claims into facts and proposes the quote for each fact. Code verifies everything it returns and decides the label.
- Groq (openai/gpt-oss-120b) was tested and compared as an alternative provider and is still supported.
- The code was written with Claude Code. Planning, review and evaluation design were done with Claude. Several commits carry a Claude co-author trailer.
- Humans chose the design, wrote the evaluation labels, ran and judged the evaluations, and deployed it.

## Team

- Mohamed Anis Belamri (aynxitis): checking engine, evaluation, deployment (Railway, Cloudflare Worker), MCP server, the first interface and the phone layout.
- TechyTails (VCoder18): the redesigned interface (two-pane review workspace, document modes and Markdown tools, outcome key) and the demo video.

## License

MIT. See `LICENSE`.
