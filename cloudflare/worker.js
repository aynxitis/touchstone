// Touchstone's public entry point: a Cloudflare Worker that proxies every request to Railway.
// Public URL: https://touchstone.aynx.dev (Worker custom domain; workers.dev and Preview
// URLs are disabled). Why a Worker: Ooredoo Algeria mobile data reaches Railway only
// intermittently (*.up.railway.app and custom domains CNAMEd to Railway), while the Worker
// loads fine. Traffic is user -> this Worker -> Railway; the railway.app URL is never shared.
//
// Behind the Worker, Railway's X-Real-IP is Cloudflare's egress IP, so the Worker sends the
// visitor's IP (CF-Connecting-IP) in X-Touchstone-Client-IP, plus a shared secret in
// X-Touchstone-Proxy-Secret. app.py trusts the IP header only when that secret matches its
// own PROXY_SECRET; anything a client sends in those two headers is deleted here first.
// With REQUIRE_PROXY_SECRET=1 on Railway (opt-in, see DEPLOY.md), the origin refuses (403)
// every request without it except /healthz and /healthz/proxy.
//
// Setup (Worker -> Settings -> Variables and Secrets):
//   ORIGIN_HOST   plain-text variable = the Railway service's domain (<service>.up.railway.app;
//                 the real value lives only in this variable, never in the repo)
//   PROXY_SECRET  encrypted secret, the same value as Railway's PROXY_SECRET variable
//                 (generate with: openssl rand -hex 32; never commit it or paste it anywhere)
// Check https://touchstone.aynx.dev/healthz/proxy shows {"via_worker":true} before turning on
// REQUIRE_PROXY_SECRET.

const ALLOWED = new Set(["GET", "HEAD", "POST"]);

export default {
  async fetch(request, env) {
    if (!ALLOWED.has(request.method)) {
      return new Response("Method not allowed", { status: 405, headers: { Allow: "GET, HEAD, POST" } });
    }
    if (!env.PROXY_SECRET || !env.ORIGIN_HOST) {
      return new Response("misconfigured", { status: 500 });   // never forward without the secret
    }

    const incoming = new URL(request.url);
    // Pin the host and set path/query separately: resolving the path as a relative URL would
    // turn "//evil.example/x" into https://evil.example/x and send it the secret.
    const target = new URL(`https://${env.ORIGIN_HOST}`);
    target.pathname = incoming.pathname;
    target.search = incoming.search;
    if (target.hostname !== env.ORIGIN_HOST) {
      return new Response("Bad request", { status: 400 });
    }

    const headers = new Headers(request.headers);
    headers.delete("X-Touchstone-Client-IP");
    headers.delete("X-Touchstone-Proxy-Secret");
    headers.set("X-Touchstone-Client-IP", request.headers.get("CF-Connecting-IP") || "");
    headers.set("X-Touchstone-Proxy-Secret", env.PROXY_SECRET);

    // The body is streamed, not buffered; the origin's response (NDJSON audits included) is
    // returned as is, so lines reach the browser as Railway sends them.
    return fetch(target, {
      method: request.method,
      headers,
      body: request.method === "POST" ? request.body : null,
      redirect: "manual",
    });
  },
};
