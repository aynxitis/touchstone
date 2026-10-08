# Deploying Touchstone on Railway (trial, no card)

Nothing here costs Groq tokens except an actual audit.

## Architecture: user -> Cloudflare Worker -> Railway
Ooredoo Algeria mobile data cannot reach Railway at all: `touchstone-project.up.railway.app`
and a custom domain CNAMEd to Railway both time out on Ooredoo, even with clean DNS
(1.1.1.1). A Cloudflare Worker that proxies to Railway (`cloudflare/worker.js`, at
`touchstone.am-belamri-e87.workers.dev`) loads fine on Ooredoo. So all public traffic goes
user -> Worker -> Railway, and **the railway.app URL is never shared publicly** (it stays
reachable, but only for the checks below).

Behind the Worker, Railway's `X-Real-IP` is the Worker's Cloudflare egress IP, so every user
would share one rate-limit bucket. The Worker therefore sends the visitor's IP
(`CF-Connecting-IP`) in `X-Touchstone-Client-IP`, plus a shared secret in
`X-Touchstone-Proxy-Secret`. app.py trusts `X-Touchstone-Client-IP` only when the secret
matches its `PROXY_SECRET` (constant-time compare); otherwise it ignores it and uses
`X-Real-IP` as before. The Worker deletes any client-sent copies of both headers first.

**The secret.** Generate it once: `openssl rand -hex 32`. The same value goes in the Railway
variable `PROXY_SECRET` and in the Worker secret `PROXY_SECRET`. Never commit it, and never
paste it into chats or prompts (including AI assistants); type it straight into the two
dashboards. If it leaks, generate a new one and set it in both places.

**Deploy order.** Set the Railway variable first (Railway redeploys), then deploy the Worker
code. While only Railway has it, nothing changes (Railway traffic never carries the secret);
a Worker deployed without `PROXY_SECRET` or `ORIGIN_HOST` answers 500 "misconfigured" and
forwards nothing.

**Worker setup** (dash.cloudflare.com -> Workers & Pages -> the worker): paste
`cloudflare/worker.js` as the code, then Settings -> Variables and Secrets:

| Name | Type | Value |
|---|---|---|
| `ORIGIN_HOST` | Text | `touchstone-project.up.railway.app` |
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
Replace `URL` with the generated domain (`https://touchstone-production-xxxx.up.railway.app`).

1. Build log shows Python 3.14; deploy log shows `Uvicorn running on http://0.0.0.0:<port>`.
   If the log shows another start command, paste the command above into Custom Start
   Command (it then overrides `railpack.json`).
2. Health: `curl URL/healthz` → `{"ok":true}`.
3. Forged headers are ignored. Link-less reports are free (no fetch, no model) and limited to
   30 per IP per hour. Two tests, each from one machine, 31 requests each. Wait an hour
   between (a) and (b), or run them from different networks: both count against your IP.

   (a) Direct to Railway (`URL` = the railway.app domain), with a forged
   `X-Touchstone-Client-IP` and a wrong secret. The secret check must reject them:
   ```sh
   for i in $(seq 1 31); do
     curl -s -o /dev/null -w "%{http_code} " -X POST URL/api/audit \
       -H "Content-Type: application/json" \
       -H "X-Touchstone-Client-IP: 203.0.113.$i" -H "X-Touchstone-Proxy-Secret: wrong-$i" \
       -d '{"report":"Algeria has 7,800 startups."}'
   done; echo
   ```
   (b) Through the Worker (`WORKER` = `https://touchstone.am-belamri-e87.workers.dev`), with
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
   Expected for both: thirty `200` then one `429`. If all 31 are `200`, a forged header got
   through: stop and fix before launch (the per-IP limit is bypassable; the daily cap still
   protects the Groq budget). Verified on 2026-10-08 before the Worker existed: Railway
   overwrites `X-Real-IP` (31 forged requests gave 30x200 then 429).
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
   curl -s -X POST URL/api/audit -H "Content-Type: application/json" \
     -d '{"report":"- Zzqvx flarnbeck 4242 https://www.iana.org/help/example-domains"}'
   ```
   Expected: a claim with `"label": "UNVERIFIED"` and "No relevant passage found on the
   page." `SOURCE UNREACHABLE` with `TIMEOUT` or `ERROR` means outbound traffic is restricted:
   the account is on the Limited Trial (step 1). This uses one of the 5 hourly audits for
   your IP but not the daily cap.
6. From Algeria: open the Worker URL (not the railway.app one) on Algerian mobile data, on
   Ooredoo, Mobilis and Djezzy, with VPNs and DNS-changing apps (1.1.1.1/WARP, Intra, ...)
   turned off, plus home internet. Load the page and run the example audit to the end.

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
- Every push to the connected branch redeploys (and resets the in-memory counters).
