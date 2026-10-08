# Deploying Touchstone on Railway (trial, no card)

Nothing here costs Groq tokens except an actual audit.

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
   30 per IP per hour. From one machine, send 31, each with different forged headers:
   ```sh
   for i in $(seq 1 31); do
     curl -s -o /dev/null -w "%{http_code} " -X POST URL/api/audit \
       -H "Content-Type: application/json" \
       -H "X-Real-IP: 203.0.113.$i" -H "X-Forwarded-For: 198.51.100.$i" \
       -d '{"report":"Algeria has 7,800 startups."}'
   done; echo
   ```
   Expected: thirty `200` then one `429`. If all 31 are `200`, Railway passed the forged
   `X-Real-IP` through: stop and fix before launch (the per-IP limit is bypassable; the daily
   cap still protects the Groq budget).
4. Buckets are per visitor, not shared. Right after step 3, from a different network (phone
   on mobile data, Wi-Fi off), send one more:
   ```sh
   curl -s -w " %{http_code}\n" -X POST URL/api/audit -H "Content-Type: application/json" \
     -d '{"report":"Algeria has 7,800 startups."}'
   ```
   Expected `200`. A `429` means `X-Real-IP` carries a Railway edge IP, so all visitors share
   one limit (the CDN bug above). Users would be blocked early but nothing is bypassable;
   report it before launch.
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
6. From Algeria: open URL on an Algerian connection (mobile data and home internet).

## If abuse happens
Someone with several IPs can use up the 7 daily audits on purpose; IP-based limits can't stop
that without blocking shared-IP pilot users. Fallback, not built yet: invite codes for pilot
users (an audit needs a valid code; codes kept server-side, one per tester or class, each with
its own daily quota). See CLAUDE.md open issue 10.

## Limits to know
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
  closes after 5 minutes with no data. An audit streams a line per claim and is capped at
  300 s, so it fits.
- Every push to the connected branch redeploys (and resets the in-memory counters).
