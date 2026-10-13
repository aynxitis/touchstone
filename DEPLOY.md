# Deploying Touchstone on Railway (trial, no card)

Nothing here costs Groq tokens except an actual audit.

## Architecture: user -> Cloudflare Worker -> Railway
**Public URL: https://touchstone.aynx.dev**, a custom domain on the Cloudflare Worker
(`cloudflare/worker.js`). The aynx.dev DNS moved from Name.com to Cloudflare; the portfolio's
records there are DNS-only (not proxied). The Worker's workers.dev URL and its Preview URLs
are disabled, so the custom domain is the only way in through the Worker.

Why a Worker: Ooredoo Algeria mobile data reaches Railway only intermittently.
The service's `*.up.railway.app` domain and a custom domain CNAMEd to Railway timed out on
Ooredoo on 2026-10-08 even with clean DNS (1.1.1.1), and worked on 2026-10-09. The Worker
loads fine on Ooredoo, so it stays permanently: all public traffic goes
user -> Worker -> Railway, and **the railway.app URL is never shared**. It is not in the repo
either: the real hostname lives only in the Worker's `ORIGIN_HOST` variable. Railway can be
made to refuse (403) every request without the Worker's secret, except the health checks, but
only with `REQUIRE_PROXY_SECRET=1`, turned on by the procedure below (off by default).

Known minor issue (not triggered today): if the app ever answers with a redirect (e.g.
Starlette's `/static` -> `/static/`), its `Location` names the railway.app host, and the Worker
passes it through (`redirect: "manual"`), sending the user to railway.app. No page links to a
URL that redirects. If one ever does, rewrite `Location` in the Worker.

Behind the Worker, Railway's `X-Real-IP` is the Worker's Cloudflare egress IP, so every user
would share one rate-limit bucket. The Worker therefore sends the visitor's IP
(`CF-Connecting-IP`) in `X-Touchstone-Client-IP`, plus a shared secret in
`X-Touchstone-Proxy-Secret`. app.py trusts `X-Touchstone-Client-IP` only when the secret
matches its `PROXY_SECRET` (constant-time compare); otherwise it uses `X-Real-IP` as before.
The Worker deletes any client-sent copies of both headers first.

**The secret.** Generate it once: `openssl rand -hex 32`. The same value goes in the Railway
variable `PROXY_SECRET` and in the Worker secret `PROXY_SECRET`. Never commit it, and never
paste it into chats or prompts (including AI assistants); type it straight into the two
dashboards. If it leaks, generate a new one and set it in both places.

**Deploy order.** Set the Railway variable and the Worker secret in either order: app.py
only trusts the header when both match, and refuses nothing unless `REQUIRE_PROXY_SECRET=1`.
A Worker deployed without `PROXY_SECRET` or `ORIGIN_HOST` answers 500 "misconfigured" and
forwards nothing.

**Origin lockdown (`REQUIRE_PROXY_SECRET`), off by default.** On 2026-10-11 enforcement went
live unconditionally with a deploy: the whole site answered `{"error":"Forbidden."}` while
`/healthz` (exempt) kept the deploy "healthy", until a rollback. It is now a separate switch,
turned on only after the handshake is proven:
1. Deploy with `REQUIRE_PROXY_SECRET` unset. Nothing is refused (as before 2026-10-11).
2. Through the Worker: `curl https://touchstone.aynx.dev/healthz/proxy` must print
   `{"via_worker":true}`. If it prints `false`, stop: Railway's deploy log has a line
   `touchstone INFO healthz/proxy: via_worker false (...)` saying `missing header` (the
   Worker isn't sending it, or something strips it), `mismatch` (the two values differ:
   regenerate one value and type it into both dashboards again) or `PROXY_SECRET unset on
   the server`. The log never shows the values.
3. Set `REQUIRE_PROXY_SECRET=1` in Railway's variables (Railway redeploys). The app refuses to
   start if `PROXY_SECRET` is empty, so a half-configured switch fails the deploy instead of
   locking everyone out.
4. Verify: https://touchstone.aynx.dev loads and the example audit runs; a direct request
   gets 403:
   ```sh
   curl -s -w " %{http_code}\n" -X POST URL/api/audit -H "Content-Type: application/json" \
     -d '{"report":"Algeria has 7,800 startups."}'
   ```
   (`URL` = the railway.app domain; expected `{"error":"Forbidden."} 403`). Each refusal
   logs `touchstone WARNING proxy check refused <METHOD> <path>: <reason>` (missing header,
   mismatch or malformed client IP), never header values.
5. Rollback: delete `REQUIRE_PROXY_SECRET` in Railway (Railway redeploys; nothing refused).
`/healthz` and `/healthz/proxy` are never refused, so `/healthz` alone can't tell you the site
works: check the page through the Worker after any change to these variables.

**Worker setup** (dash.cloudflare.com -> Workers & Pages -> the worker): paste
`cloudflare/worker.js` as the code, then Settings -> Variables and Secrets:

| Name | Type | Value |
|---|---|---|
| `ORIGIN_HOST` | Text | the service's Railway domain, `<service>.up.railway.app` (only here, never in the repo) |
| `PROXY_SECRET` | Secret (encrypted) | the generated value |

The Worker allows GET, HEAD and POST only, forwards with `redirect: "manual"`, and returns
Railway's response unbuffered so the NDJSON audit stream flows line by line. During an audit
the app sends a `{"type":"heartbeat"}` line after 15 s without output, because Cloudflare
drops idle connections at ~100 s (Railway at 5 min) and a slow model call can be silent.

## What's in the repo
- `railpack.json`: Railpack (Railway's default builder) reads it from the repo root. It pins
  Python 3.14 and sets the start command:
  `uvicorn app:app --host 0.0.0.0 --port $PORT --workers 1 --no-proxy-headers`
- `.python-version` (`3.14`): second source for the Python version.
- No `railway.json`: Railway's Config as Code is deprecated and new services cannot opt into
  it; its replacement (`.railway/railway.ts`) only applies through the Railway CLI. The
  settings below are set once in the dashboard instead.

## 1. Account: you need the FULL trial
Railway gives unverified accounts a **Limited Trial** with restricted outbound network
access. Touchstone fetches arbitrary pages and calls Groq, so on a limited trial every claim
fails. Sign in with a GitHub account (verification is automated, mostly based on the GitHub
account's age and activity) and check the plan shows the full trial, not "Limited Trial".
If it stays limited: try railway.com/verify; Railway does not answer verification requests,
and the only guaranteed way out is the Hobby plan (paid). Step 4 below detects a restricted
network without spending tokens.

The trial is a one-time $5 credit for 30 days (no sleep by default: the service runs all the
time; at ~130 MB of RAM it should stay well inside $5). When the trial ends the account drops
to the Free plan ($1/month credit), which won't keep it running: plan the pilot inside the
30 days.

## 2. Create the service
New Project → Deploy from GitHub repo → this repo. Then in the service:

| Where | Setting | Value |
|---|---|---|
| Settings → Build | Builder | Railpack (default) |
| Settings → Deploy | Custom Start Command | leave empty (`railpack.json` sets it) |
| Settings → Deploy | Healthcheck Path | `/healthz` |
| Settings → Deploy | Regions | EU West Metal, Amsterdam (`europe-west4-drams3a`), closest to Algeria |
| Settings → Deploy | Replicas | 1 |
| Settings → Deploy | Serverless (app sleeping) | off |
| Settings → Networking | Public Networking | Generate Domain |
| Variables | `GROQ_API_KEY` | your key (sealed variable) |
| Variables | `GLOBAL_AUDITS_PER_DAY` | `7` |
| Variables | `PROVIDER` | leave unset (= `groq`); `gemini` only to trial Gemini (see below) |
| Variables | `GEMINI_API_KEY` | only with `PROVIDER=gemini` (sealed variable) |
| Variables | `GEMINI_AUDITS_PER_DAY` | `40` (only with `PROVIDER=gemini`) |
| Variables | `CLIENT_IP_HEADER` | `X-Real-IP` |
| Variables | `PROXY_SECRET` | the shared Worker secret (sealed variable; see Architecture) |

Keep 1 replica and `--workers 1`: the 5-audits/hour limit, the daily cap, the link-less
limit and the one-audit-at-a-time lock are in process memory. More replicas or workers would
multiply the limits and let audits run in parallel past Groq's 8K tokens/minute.

**Why `X-Real-IP`:** Railway's docs name it as the client's remote IP, and staff describe it
as "a single source of truth for the connecting IP". The leftmost `X-Forwarded-For` entry is
not used: reports conflict on whether Railway strips client-supplied values, and if it
doesn't, anyone could dodge the rate limit. One known risk: in March 2026 staff reported a
bug where `X-Real-IP` held the CDN edge IP instead of the visitor's. That fails safe (visitors
share buckets, limits get stricter, never bypassable); step 3 detects it.

## 3. After the first deploy (token-free checks)
Replace `URL` with the generated domain (`https://<service>.up.railway.app`) and `WORKER`
with `https://touchstone.aynx.dev`. With `REQUIRE_PROXY_SECRET=1`, only `URL/healthz` and
`URL/healthz/proxy` answer directly; run the checks through `WORKER` then (3(a) expects 403).

1. Build log shows Python 3.14; deploy log shows `Uvicorn running on http://0.0.0.0:<port>`.
   If the log shows another start command, paste the command above into Custom Start
   Command (it then overrides `railpack.json`).
2. Health: `curl URL/healthz` → `{"ok":true}`.
3. Forged headers are ignored. Link-less reports are free (no fetch, no model) and limited to
   30 per IP per hour.

   (a) Direct to Railway (`URL` = the railway.app domain), with a forged
   `X-Touchstone-Client-IP` and a wrong secret. The forged IP must be ignored: thirty `200`
   then one `429` (with `REQUIRE_PROXY_SECRET=1`: thirty-one `403`):
   ```sh
   for i in $(seq 1 31); do
     curl -s -o /dev/null -w "%{http_code} " -X POST URL/api/audit \
       -H "Content-Type: application/json" \
       -H "X-Touchstone-Client-IP: 203.0.113.$i" -H "X-Touchstone-Proxy-Secret: wrong-$i" \
       -d '{"report":"Algeria has 7,800 startups."}'
   done; echo
   ```
   (b) Through the Worker (`WORKER` = `https://touchstone.aynx.dev`), with
   every IP header forged. The Worker must overwrite them with the real visitor IP:
   ```sh
   for i in $(seq 1 31); do
     curl -s -o /dev/null -w "%{http_code} " -X POST WORKER/api/audit \
       -H "Content-Type: application/json" \
       -H "X-Real-IP: 203.0.113.$i" -H "X-Forwarded-For: 198.51.100.$i" \
       -H "X-Touchstone-Client-IP: 192.0.2.$i" \
       -d '{"report":"Algeria has 7,800 startups."}'
   done; echo
   ```
   Expected for (b): thirty `200` then one `429`. If all 31 are `200`, a forged header got
   through: stop and fix before launch (the per-IP limit is bypassable; the daily cap still
   protects the Groq budget). 3(b) alone does NOT prove the secret matches: with a mismatch,
   app.py keys on `X-Real-IP` (the Worker's egress IP), which a single tester also sees as
   thirty `200` then `429`. `/healthz/proxy` (above) or step 4 proves it. Verified
   on 2026-10-08 before the Worker existed: Railway overwrites `X-Real-IP` (31 forged requests
   gave 30x200 then 429).
4. Buckets are per visitor, not shared. Right after 3(b), from a different network (phone
   on mobile data, Wi-Fi off), send one more through the Worker:
   ```sh
   curl -s -w " %{http_code}\n" -X POST WORKER/api/audit -H "Content-Type: application/json" \
     -d '{"report":"Algeria has 7,800 startups."}'
   ```
   Expected `200`. A `429` means all Worker traffic shares one bucket: `PROXY_SECRET`
   differs between Railway and the Worker (or is unset), so app.py falls back to
   `X-Real-IP`, the Worker's egress IP. Fix the secret before launch.
5. Outbound network works (full trial), still without tokens. This claim shares no words with
   the cited page, so the page is fetched but the model is never called:
   ```sh
   curl -s -X POST WORKER/api/audit -H "Content-Type: application/json" \
     -d '{"report":"- Zzqvx flarnbeck 4242 https://www.iana.org/help/example-domains"}'
   ```
   Expected: a claim with `"label": "UNVERIFIED"` and "No relevant passage found on the
   page." `SOURCE UNREACHABLE` with `TIMEOUT` or `ERROR` means outbound traffic is restricted:
   the account is on the Limited Trial (step 1). This uses one of the 5 hourly audits for
   your IP but not the daily cap.
6. UI check, zero tokens: open https://touchstone.aynx.dev, paste `examples/ui_check.txt`
   (11 nonsense claims citing the IANA example-domains page) and press Audit. No claim shares
   a word, name, title or number with the page, so each one is answered UNVERIFIED ("No
   relevant passage found on the page.") before any model call: no Groq tokens, and the
   daily cap is not touched (it counts an audit at its first model call). It does use one of
   your IP's 5 audits per hour. You should see:
   - PROVIDER=gemini (25 claims, 8 sources per audit): "11 claims checked: 11 unverified" and
     eleven UNVERIFIED cards (Claims 1-11), no "Not checked" list;
   - PROVIDER=groq (10 claims): summary "Checked 10 of 11 claims: 10 unverified", and under it
     "Checked 10 of 11 cited claims, in report order. The rest are listed below as not
     checked."; ten UNVERIFIED cards (Claims 1-10); below them a collapsed "+ Not checked
     (limit of 10 claims per audit): 1 claim" that opens to "Claim 11: Wuzzle crantop 48281".
   If the old wording shows ("claims with numbers first", no Not checked list), the browser
   is running a cached app.js: view the page source; the script tag must read
   `/static/app.js?v=<12 hex chars>`.
7. From Algeria: open https://touchstone.aynx.dev (not the railway.app URL) on Algerian mobile data, on
   Ooredoo, Mobilis and Djezzy, with VPNs and DNS-changing apps (1.1.1.1/WARP, Intra, ...)
   turned off, plus home internet. Load the page and run the example audit to the end.

## Model provider: Groq (default) or Gemini
`PROVIDER` picks the model: unset or `groq` = Groq `openai/gpt-oss-120b`, one call per claim
over ~3,000 chars of excerpts (8K tokens/minute free tier). `gemini` = Google
`gemini-3.5-flash-lite`, one call per cited page with the whole page (up to 100K chars) and
all its claims. Code checks and labels are the same either way. Switching is a variable
change plus redeploy; the page then shows "Reports are processed by Google Gemini (free tier),
which may use inputs to improve Google's products. Don't paste anything private." under the
input.

With `PROVIDER=gemini` set, in Railway: `GEMINI_API_KEY` (sealed; from Google AI Studio,
never pasted anywhere else) and `GEMINI_AUDITS_PER_DAY` (`40`: an audit sends at most 10
requests, one per cited page, and the app paces itself at 13/minute and 450/day under the
free tier's 15 RPM / 500 RPD). The app refuses to start if the key is missing.

**Data use.** With Gemini, the pasted report and the text of every cited page go to Google.
On the free tier, Google's Gemini API terms allow it to use submitted content and responses
to improve its products, and human reviewers may read them; paid (billing-enabled) projects
are excluded. Check the current terms for your project's region before using it with real
users, and don't switch the public site to Gemini without telling users (the on-page line
does that). Groq's free tier has its own data terms; neither is suitable for confidential
reports.

## If abuse happens
Someone with several IPs can use up the 7 daily audits on purpose; IP-based limits can't stop
that without blocking shared-IP pilot users. Fallback, not built yet: invite codes for pilot
users (an audit needs a valid code; codes kept server-side, one per tester or class, each with
its own daily quota). See CLAUDE.md open issue 10.

## Limits to know
- VPN users (e.g. Cloudflare WARP) can show up with rotating exit IPs and get extra buckets.
  Accepted for the MVP: the daily cap below protects the Groq budget.
- Per visitor: 5 audits/hour (IPv6 counted per /64, so rotating addresses doesn't help).
  Shared-IP risk for the pilot: Algerian campus Wi-Fi and mobile carriers (CGNAT) put many
  users behind one IPv4 address, and they all share those 5 audits per hour. If pilot users
  report "Limit of 5 audits per hour reached" without having run 5 themselves, raise
  `RATE_LIMIT` in app.py; the daily cap below still protects the Groq budget. A per-IP daily
  limit was rejected for the same reason.
  Across everyone: `GLOBAL_AUDITS_PER_DAY` (7) audits per UTC day, counted at an audit's
  first model call (audits whose pages are all unreachable don't count). A 10-claim audit is
  up to ~20K tokens; 7 fit Groq's 200K/day free tier with room to spare. Once used up, new
  audits are refused up front ("try again tomorrow"). The counter is in memory and resets on
  every redeploy or restart, so Groq's own daily limit stays the hard ceiling.
- Railway HTTP limits: a request may run up to 15 minutes while data keeps flowing, and
  closes after 5 minutes with no data. An audit streams a line per claim (plus a heartbeat after
  15 s of silence) and is capped at 300 s, so it fits. Cloudflare in front drops connections
  idle for ~100 s; the heartbeat keeps the stream under that.
- PDFs (pypdf, in requirements.txt): parsed in a child process capped at 512 MB address space
  and 20 s (CPU and wall clock), one at a time, first 60 pages, downloads over 15 MB refused.
  With the app's own ~300 MB that stays under the 1 GB plan; a hostile PDF only kills its
  child. Six PDFs in one audit add ~5 s.
- Claims citing several URLs: the first 3 are checked (the rest listed as not checked, never
  fetched), so an audit fetches at most 30 URLs. On Groq that is one call per
  claim AND source (report5's first 10 claims: 12 calls), so a source-heavy report spends
  more of the 7.5K tokens/minute and can hit the 300 s limit (later claims NOT CHECKED); on
  Gemini it adds no requests (one call per cited page either way).
- Every push to the connected branch redeploys (and resets the in-memory counters).
