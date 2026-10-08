# Deploying Touchstone on Render (free plan)

Nothing here costs Groq tokens except an actual audit.

## Create the service
Either way works; the Blueprint is less error-prone.

**Blueprint:** Render dashboard → New → Blueprint → pick this repo. Render reads `render.yaml`
and asks for `GROQ_API_KEY`. Paste the key there, never in the repo.

**Manual:** New → Web Service → this repo, then:

| Setting | Value |
|---|---|
| Runtime | Python |
| Region | Frankfurt (can't be changed later) |
| Instance type | Free |
| Build command | `pip install -r requirements.txt` |
| Start command | `uvicorn app:app --host 0.0.0.0 --port $PORT --workers 1 --no-proxy-headers` |
| Health check path | `/healthz` |
| Env `PYTHON_VERSION` | `3.14.7` |
| Env `CLIENT_IP_HEADER` | `True-Client-IP` |
| Env `GROQ_API_KEY` | your key (secret) |

Keep `--workers 1`: the 5-audits/hour limit, the 30/hour link-less limit and the
one-audit-at-a-time lock are in process memory. More workers would multiply the limits and
let audits run in parallel past Groq's 8K tokens/minute.

## After the first deploy (token-free checks)
Replace `URL` with the service URL (`https://touchstone-xxxx.onrender.com`).

1. Health: `curl URL/healthz` → `{"ok":true}`.
2. Client IP can't be forged. Link-less reports are free (no fetch, no model) and limited to
   30 per IP per hour. Send 31, each with a different forged header:
   ```sh
   for i in $(seq 1 31); do
     curl -s -o /dev/null -w "%{http_code} " -X POST URL/api/audit \
       -H "Content-Type: application/json" \
       -H "True-Client-IP: 203.0.113.$i" -H "X-Forwarded-For: 198.51.100.$i" \
       -d '{"report":"Algeria has 7,800 startups."}'
   done; echo
   ```
   Expected: thirty `200` then one `429`. If all 31 are `200`, Render passes the forged
   header through: set `CLIENT_IP_HEADER` to `CF-Connecting-IP`, redeploy, and repeat. If you
   get `429` from the very first request, the header is missing and everyone shares one IP:
   check which header carries your IP and fix `CLIENT_IP_HEADER`.
3. Cold start: leave the service idle for 15+ minutes, open the page. Render shows its own
   loading page for about a minute. With the page already open, Audit/Example show
   "Waking up the server…" after 5 seconds and never treat Render's loading page as results.
4. From Algeria: open the URL on an Algerian connection (mobile data and home internet) to
   confirm `*.onrender.com` is reachable.

## Limits to know
- Free instance: 512 MB RAM (peak use measured locally: ~130 MB), 0.1 vCPU, sleeps after
  15 idle minutes. The rate-limit tables reset on every sleep.
- Bandwidth: free workspaces now get 5 GB/month outbound (third-party report, April 2026).
  With no card on file, Render suspends the service if it is exceeded.
- `autoDeployTrigger: commit`: every push to `main` redeploys.
