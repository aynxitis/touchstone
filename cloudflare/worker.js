// Touchstone's public entry point: a Cloudflare Worker that proxies every request to Railway.
// Why: Ooredoo Algeria mobile data cannot reach Railway at all (*.up.railway.app and custom
// domains CNAMEd to Railway time out), while workers.dev loads fine. Traffic is
// user -> this Worker -> Railway; the railway.app URL is never shared publicly.
//
// Behind the Worker, Railway's X-Real-IP is Cloudflare's egress IP, so the Worker sends the
// visitor's IP (CF-Connecting-IP) in X-Touchstone-Client-IP, plus a shared secret in
// X-Touchstone-Proxy-Secret. app.py trusts the IP header only when that secret matches its
// own PROXY_SECRET; anything a client sends in those two headers is deleted here first.
//
// Setup (Worker -> Settings -> Variables and Secrets):
//   ORIGIN_HOST   plain-text variable = touchstone-project.up.railway.app
//   PROXY_SECRET  encrypted secret, the same value as Railway's PROXY_SECRET variable
//                 (generate with: openssl rand -hex 32; never commit it or paste it anywhere)
// Deploy order: set PROXY_SECRET on Railway first, then deploy this Worker.

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
    const target = new URL(incoming.pathname + incoming.search, `https://${env.ORIGIN_HOST}`);

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
