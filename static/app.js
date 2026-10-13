// Touchstone frontend. Every piece of report text, page text and model output is
// untrusted: it is only ever rendered with textContent, never innerHTML.
"use strict";

const MAX_CHARS = 20000;
const TONES = {
  "SOURCED": "green", "PARTIAL": "yellow", "COULDN'T CONFIRM": "yellow",
  "UNSUPPORTED": "red", "CONTRADICTED": "red",
  "UNVERIFIED": "blue", "OPINION": "blue", "SOURCE UNREACHABLE": "grey",
  "NO SOURCE GIVEN": "grey", "NOT CHECKED": "grey", "ERROR": "grey",
};
// Summary order and wording: "9 sourced, 3 partial, 1 contradicted, 2 unreachable"
const SUMMARY = [
  ["SOURCED", "sourced"], ["PARTIAL", "partial"], ["COULDN'T CONFIRM", "couldn't confirm"],
  ["UNSUPPORTED", "unsupported"],
  ["CONTRADICTED", "contradicted"], ["UNVERIFIED", "unverified"], ["OPINION", "opinion"],
  ["SOURCE UNREACHABLE", "unreachable"], ["NOT CHECKED", "not checked (time limit)"],
  ["ERROR", "failed"],
];
const STATUS_TEXT = {
  stated: "stated", missing: "not found", contradicted: "contradicted",
  unconfirmed: "couldn't confirm",   // the model found it; a code check doubts it (never an accusation)
  possible: "possibly stated",       // not in the passages, but a page line has its figures
};

const $ = (id) => document.getElementById(id);
const str = (v) => (typeof v === "string" ? v : "");
const arr = (v) => (Array.isArray(v) ? v : []);
const int = (v) => (Number.isInteger(v) && v >= 0 ? v : null);
const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return str(u); } };

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

// Only http(s) links become clickable: a javascript: URL in a report would be XSS.
function safeUrl(u) {
  try {
    const url = new URL(u);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch { return null; }
}

// "Waiting for capacity… (Ns)" counts down live; any later status ends it.
let waitTimer = null;

function stopWaiting() {
  if (waitTimer) clearInterval(waitTimer);
  waitTimer = null;
}

function showWaiting(seconds) {
  stopWaiting();
  let left = seconds;
  const tick = () => {
    $("status").textContent = left > 0 ? `Waiting for capacity… (${left}s)` : "Resuming…";
    $("status").classList.remove("error");
    left -= 1;
    if (left < 0) stopWaiting();
  };
  tick();
  waitTimer = setInterval(tick, 1000);
}

function setStatus(text, isError = false) {
  stopWaiting();
  $("status").textContent = text;
  $("status").classList.toggle("error", isError);
}

function updateCount() {
  const n = $("report").value.length;
  $("count").textContent = `${n.toLocaleString()} / ${MAX_CHARS.toLocaleString()}`;
  $("count").classList.toggle("over", n > MAX_CHARS);
}

// The reason line restates the rows above it (quote_check.verdict(): "Stated: a; b." per
// status, each fact's note, "Framing not checked: x."). Only what the rows don't show is
// kept: caps, numbers not on the page, sources disagreeing, demoted quotes... Each piece is
// removed only if it is exactly what the rows render, so no other reason can be lost.
const REASON_PREFIX = [
  ["contradicted", "Contradicted by the page"], ["stated", "Stated"],
  ["unconfirmed", "Couldn't confirm (code check)"],
  ["possible", "Possibly stated, check the page line shown"], ["missing", "Not in the checked passages"],
];

function reasonExtra(ev) {
  let reason = str(ev.reason);
  const facts = arr(ev.facts).filter((f) => f && typeof f === "object");
  const shown = [];
  for (const [status, prefix] of REASON_PREFIX) {
    const xs = facts.filter((f) => str(f.status) === status).map((f) => str(f.fact));
    if (xs.length) shown.push(`${prefix}: ${xs.join("; ")}.`);
  }
  for (const f of facts) if (str(f.note)) shown.push(str(f.note));
  const framing = arr(ev.framing).filter((x) => str(x));
  if (framing.length) shown.push(`Framing not checked: ${framing.join("; ")}.`);
  for (const piece of shown) {
    const i = reason.indexOf(piece);
    const end = i + piece.length;
    // A whole piece only: at the start or after a space, and at the end or before one.
    if (i >= 0 && (i === 0 || reason[i - 1] === " ") && (end === reason.length || reason[end] === " ")) {
      reason = reason.slice(0, i) + reason.slice(end);
    }
  }
  return reason.replace(/\s{2,}/g, " ").trim();
}

function renderCard(ev) {
  const label = str(ev.label) || "UNKNOWN";
  const tone = TONES[label] || "grey";
  const card = el("article", `card tone-${tone}`);

  const head = el("div", "card-head");
  head.append(el("span", "badge", label));
  const n = int(ev.claim);
  if (n !== null) head.append(el("span", "num", `Claim ${n}`));
  card.append(head);

  card.append(el("p", "claim", str(ev.text)));
  for (const note of arr(ev.notes)) if (str(note)) card.append(el("p", "note", str(note)));

  const sources = arr(ev.sources).filter((s) => s && typeof s === "object");
  const multi = sources.length > 1;
  const parts = el("ul", "parts");
  for (const f of arr(ev.facts)) {
    if (!f || typeof f !== "object") continue;
    const status = str(f.status);
    const li = el("li");
    const ph = el("div", "part-head");
    ph.append(el("span", "tag", STATUS_TEXT[status] || "unclear"), el("span", "", str(f.fact)));
    li.append(ph);
    // Where the quote is from: the PDF page, and the site when the claim cites several.
    const where = [multi && str(f.source) ? host(f.source) : "", int(f.page) ? `p. ${f.page}` : ""]
      .filter(Boolean).join(", ");
    const quote = (text) => {
      const q = el("blockquote", "", `“${text}”`);
      if (where) q.append(el("span", "where", ` (${where})`));
      return q;
    };
    if (str(f.quote)) li.append(quote(str(f.quote)));
    if (str(f.evidence)) {
      li.append(el("p", "rejected", "Not in the passages checked, but this line on the page has its figures. Check it:"));
      li.append(quote(str(f.evidence)));
    }
    if (str(f.rejected_quote)) {
      li.append(el("p", "rejected", `Quote given by the model, not found on the page: “${str(f.rejected_quote)}”`));
    }
    if (str(f.note)) li.append(el("p", "rejected", str(f.note)));
    parts.append(li);
  }
  for (const x of arr(ev.framing)) {
    if (!str(x)) continue;
    const li = el("li");
    const ph = el("div", "part-head");
    ph.append(el("span", "tag", "framing, not checked"), el("span", "", str(x)));
    li.append(ph);
    parts.append(li);
  }
  if (parts.childElementCount) card.append(parts);

  const extra = reasonExtra(ev);
  if (extra) card.append(el("p", "reason", extra));
  if (str(ev.detail)) card.append(el("p", "detail", `Details: ${str(ev.detail)}`));

  // Several sources: each with its own outcome ("SOURCED", "SOURCE UNREACHABLE: ...").
  if (multi) {
    const list = el("ul", "sources");
    for (const s of sources) {
      const li = el("li");
      const href = safeUrl(str(s.url));
      if (href) {
        const a = el("a", "source", href);
        a.href = href;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        li.append(a);
      } else {
        li.append(el("span", "source-plain", str(s.url)));
      }
      const outcome = str(s.label) === "SOURCE UNREACHABLE" ? str(s.reason) || "Could not be read." : str(s.label);
      li.append(el("span", "outcome", ` \u2014 ${outcome}`));
      if (str(s.note)) li.append(el("span", "outcome", ` (${str(s.note)})`));
      if (str(s.detail)) li.append(el("span", "detail", ` Details: ${str(s.detail)}`));
      list.append(li);
    }
    card.append(list);
    return card;
  }

  const href = safeUrl(str(ev.url));
  if (href) {
    const a = el("a", "source", href);
    a.href = href;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    card.append(a);
  } else if (str(ev.url)) {
    card.append(el("span", "source-plain", str(ev.url)));
  }
  return card;
}

function addUncited(text) {
  const box = $("uncited");
  box.hidden = false;
  box.querySelector("ul").append(el("li", "", text));
  const n = box.querySelector("ul").childElementCount;
  box.querySelector("summary").textContent =
    `No source given (${n} passage${n === 1 ? "" : "s"}): the report cites nothing for these, so they were not checked`;
}

// Cited claims over a per-audit cap (claims, or source links on Gemini): listed (collapsed)
// so nobody reads the results as an audit of the whole report. The summary names each cap
// that left claims out ("limit of 25 claims per audit; limit of 8 sources per audit").
const skippedWhy = new Set();

function addSkipped(ev, reason) {
  const box = $("skipped");
  box.hidden = false;
  const li = el("li", "", `${int(ev.claim) !== null ? `Claim ${ev.claim}: ` : ""}${str(ev.text)}`);
  if (str(ev.url)) li.append(el("span", "source-plain", ` ${str(ev.url)}`));
  box.querySelector("ul").append(li);
  if (reason) skippedWhy.add(reason.replace(/\.$/, "").replace(/^L/, "l"));
  const n = box.querySelector("ul").childElementCount;
  const why = [...skippedWhy].join("; ");
  box.querySelector("summary").textContent =
    `Not checked${why ? ` (${why})` : ""}: ${n} claim${n === 1 ? "" : "s"}`;
}

// "Checked 10 of 11 claims: ..." whenever some cited claims were left out.
function summaryLine(counts, checked, cited) {
  const bits = SUMMARY.filter(([k]) => counts[k]).map(([k, w]) => `${counts[k]} ${w}`);
  for (const [k, v] of Object.entries(counts)) {
    if (!SUMMARY.some(([s]) => s === k)) bits.push(`${v} ${k.toLowerCase()}`);
  }
  const head = cited > checked
    ? `Checked ${checked} of ${cited} claims`
    : `${checked} claim${checked === 1 ? "" : "s"} checked`;
  return bits.length ? `${head}: ${bits.join(", ")}` : head;
}

// The last finished run, for "Download results": built from the events already received,
// nothing is stored on the server. rescore.py re-scores such a file with zero tokens.
let lastRun = null;

function offerDownload(run) {
  run.created ||= new Date().toISOString();
  lastRun = run;
  $("download").hidden = false;
}

function downloadRun() {
  if (!lastRun) return;
  const blob = new Blob([JSON.stringify(lastRun, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `touchstone-run-${lastRun.created.replace(/[:.]/g, "-")}.json`;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function reset() {
  lastRun = null;
  $("download").hidden = true;
  $("cards").replaceChildren();
  $("summary").textContent = "";
  $("scope").textContent = "";
  const box = $("uncited");
  box.hidden = true;
  box.open = false;
  box.querySelector("ul").replaceChildren();
  const skipped = $("skipped");
  skipped.hidden = true;
  skipped.open = false;
  skipped.querySelector("ul").replaceChildren();
  skippedWhy.clear();
  $("nolinks").hidden = true;
  $("replay").hidden = true;
  $("copy-prompt").textContent = "Copy";
}

// A passage can hold several claims: count sentences, not lines.
function countSentences(text) {
  return text.split(/(?<=[.!?])\s+(?=["\u201C(]?[A-Z0-9])/).filter((x) => /[A-Za-z0-9]/.test(x)).length;
}

// Shown instead of claim cards when the report has nothing Touchstone can check.
function showNoLinks(claims) {
  setStatus("");
  $("nolinks-msg").textContent = claims === 1
    ? "This report cites no sources, so its 1 claim can't be checked."
    : `This report cites no sources, so none of its ${claims} claims can be checked.`;
  $("nolinks").hidden = false;
}

async function copyPrompt() {
  const text = $("fix-prompt").textContent;
  try {
    await navigator.clipboard.writeText(text);
    $("copy-prompt").textContent = "Copied";
  } catch {
    // Clipboard blocked: select the text so Ctrl+C works.
    const range = document.createRange();
    range.selectNodeContents($("fix-prompt"));
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    $("copy-prompt").textContent = "Press Ctrl+C";
  }
}

// One results view, fed event by event: a live audit's stream and the saved example's
// replay go through the same handler, so both render with the same card code.
function resultsView(report) {
  let total = 0, cited = 0, limit = null, done = 0, finished = false, noLinks = false, sentences = 0, stopped = "";
  const counts = {};
  // Everything needed to re-check the run later: each claim event as received (facts,
  // quotes, statuses, label, reason, URL, the model's reply), the not-checked claims, and
  // the uncited passages.
  const run = { format: "touchstone-run", version: 1, created: "", report, cited: 0, checked: 0,
                tokens: null, stopped: null, claims: [], not_checked: [], uncited: [] };

  const handle = (ev) => {
    if (!ev || typeof ev !== "object") throw new Error("bad event");
    if (ev.type === "heartbeat") return;   // keep-alive for proxies while a claim is slow
    if (ev.type === "start") {
      total = int(ev.checked) ?? 0;
      cited = int(ev.cited) ?? total;
      run.cited = cited;
      run.checked = total;
      limit = int(ev.limit);
      if (cited === 0) { noLinks = true; return; }   // screen shown at "done"
      $("scope").textContent = cited > total
        ? `Checked ${total} of ${cited} cited claims, in report order. The rest are listed below as not checked.`
        : `Checked ${total} of ${cited} cited claims.`;
      setStatus(`Fetching ${total} source${total === 1 ? "" : "s"}…`);
    } else if (ev.type === "claim") {
      if (ev.claim === null) {
        if (noLinks) sentences += countSentences(str(ev.text));
        else addUncited(str(ev.text));
        run.uncited.push(str(ev.text));
        return;
      }
      const { type, index, ...claim } = ev;
      run.claims.push(claim);
      done += 1;
      const label = str(ev.label) || "UNKNOWN";
      counts[label] = (counts[label] || 0) + 1;
      $("cards").append(renderCard(ev));
      setStatus(done < total ? `Claim ${done}/${total} done, checking the next…` : `Claim ${done}/${total} done`);
    } else if (ev.type === "wait") {
      // Groq's free tier allows ~4 claims a minute: the audit pauses, then carries on.
      showWaiting(int(ev.seconds) ?? 10);
    } else if (ev.type === "skipped") {
      const reason = str(ev.reason) || (limit ? `Limit of ${limit} claims per audit.` : "");
      addSkipped(ev, reason);
      run.not_checked.push({ claim: int(ev.claim), text: str(ev.text), url: str(ev.url),
                             label: "NOT CHECKED", reason });
    } else if (ev.type === "quota") {
      // Out of capacity mid-audit: keep the cards so far, say so once, no per-claim errors.
      stopped = str(ev.message) || "Touchstone's free daily capacity is used up, try again tomorrow.";
      run.stopped = stopped;
      $("scope").textContent = `Stopped after ${done} of ${total} claims. Results so far are kept.`;
    } else if (ev.type === "done") {
      finished = true;
      run.tokens = int(ev.tokens);
      if (noLinks) { showNoLinks(sentences); return; }
      if (done) offerDownload(run);
      if (stopped) {
        setStatus(stopped, true);
        if (done) $("summary").textContent = summaryLine(counts, done, cited);
        return;
      }
      if (total) setStatus(`Done. Claim ${done}/${total}.`);
      if (done) $("summary").textContent = summaryLine(counts, done, cited);
    } else if (ev.type === "error") {
      setStatus(str(ev.error) || "The audit failed.", true);
    }
  };

  // A line that isn't a valid event: one grey card, the rest still render.
  const feed = (ev) => {
    try { handle(ev); } catch {
      const card = el("article", "card tone-grey");
      card.append(el("p", "reason", "One result could not be read and was skipped."));
      $("cards").append(card);
    }
  };

  // The stream ended without "done".
  const endedEarly = () => {
    if (finished || $("status").classList.contains("error")) return;
    setStatus(`The connection ended early. Claim ${done}/${total} done.`, true);
    if (done) $("summary").textContent = summaryLine(counts, done, cited);
    if (done) { run.stopped = "The connection ended early."; offerDownload(run); }
  };

  return { feed, endedEarly, progress: () => ({ done, total }) };
}

// Another visitor's audit holds the server (one at a time, up to 300 s): the page retries on
// its own every 15 s for up to 6 minutes. A busy answer comes before the server's per-hour
// count, so these retries never use up the visitor's audits.
const BUSY_RETRY_S = 15;
const BUSY_MAX_S = 360;
let cancelBusy = null;

const mmss = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

// Resolves true when it's time to retry, false if the visitor pressed Cancel.
function waitWhileBusy(message, since) {
  return new Promise((resolve) => {
    let left = BUSY_RETRY_S, timer = null;
    const finish = (retry) => {
      clearInterval(timer);
      cancelBusy = null;
      $("cancel").hidden = true;
      resolve(retry);
    };
    const tick = () => {
      const waited = mmss(Math.round((Date.now() - since) / 1000));
      setStatus(left > 0 ? `${message} Next try in ${left}s (waiting ${waited}).` : "Trying again…");
      if (left-- <= 0) finish(true);
    };
    cancelBusy = () => finish(false);
    $("cancel").hidden = false;
    tick();
    timer = setInterval(tick, 1000);
  });
}

async function runAudit() {
  const report = $("report").value;
  if (!report.trim()) { setStatus("Paste a report first.", true); return; }
  if (report.length > MAX_CHARS) {
    setStatus(`Reports are limited to ${MAX_CHARS.toLocaleString()} characters.`, true);
    return;
  }
  reset();
  $("audit").disabled = $("example").disabled = $("run-live").disabled = true;
  setStatus("Fetching sources…");
  const view = resultsView(report);

  try {
    const since = Date.now();
    let resp;
    for (;;) {
      resp = await withWakeNotice(() => fetch("/api/audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ report }),
      }));
      if (isWakePage(resp, "application/x-ndjson")) { setStatus(WAKE_RETRY, true); return; }
      if (resp.ok && resp.body) break;
      let body = null;
      try { body = await resp.json(); } catch {}
      const msg = body && typeof body === "object" ? str(body.error) : "";
      if (resp.status === 503 && body && body.busy === true) {
        if (Date.now() - since >= BUSY_MAX_S * 1000) { setStatus("Still busy — please try again later.", true); return; }
        if (!(await waitWhileBusy(msg || "Another audit is running.", since))) { setStatus("Cancelled."); return; }
        continue;
      }
      setStatus(msg || `The server refused the audit (HTTP ${resp.status}).`, true);
      return;
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done: eof } = await reader.read();
      buf += decoder.decode(value || new Uint8Array(), { stream: !eof });
      const lines = buf.split("\n");
      buf = eof ? "" : lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        let ev;
        try { ev = JSON.parse(line); } catch { ev = null; }
        view.feed(ev);
      }
      if (eof) break;
    }
    view.endedEarly();
  } catch {
    setStatus("Could not reach the server.", true);
  } finally {
    // Never leave a waiting/countdown status behind once the audit is over (B4).
    if (waitTimer || /^(Waiting for capacity|Resuming)/.test($("status").textContent)) {
      const { done, total } = view.progress();
      setStatus(done ? `Done. Claim ${done}/${total}.` : "The audit ended.");
    }
    if (cancelBusy) cancelBusy();
    $("audit").disabled = $("example").disabled = $("run-live").disabled = false;
  }
}

// A sleeping or cold-starting host can take up to a minute to answer the first request.
const WAKE_AFTER_MS = 5000;
const WAKE_RETRY = "The server is waking up after a quiet spell. Try again in a minute.";

async function withWakeNotice(request) {
  const timer = setTimeout(() => setStatus(
    "Waking up the server: the first request after a quiet spell can take up to a minute\u2026"), WAKE_AFTER_MS);
  try { return await request(); } finally { clearTimeout(timer); }
}

// While waking, the host may answer with its own HTML loading page instead of our data:
// never parse that as results or load it into the textarea.
function isWakePage(resp, expected) {
  const type = (resp.headers.get("content-type") || "").toLowerCase();
  return resp.ok && !type.startsWith(expected);
}

// "Try an example": loads examples/demo.txt and replays its saved run (examples/demo_run.json,
// a Download-button file) through the live renderer: no audit, no tokens, no limit used.
// No saved run, or one that isn't a run of this exact text: the text alone, as before.
const EXAMPLE_LOADED = "Example loaded: a Perplexity answer on Africa's smartphone market. Press Audit.";

function validRun(run, report) {
  return !!run && typeof run === "object" && run.format === "touchstone-run" && run.version === 1
    && typeof run.report === "string" && run.report.trim() === report.trim()
    && Array.isArray(run.claims) && run.claims.length > 0
    && typeof run.created === "string" && !Number.isNaN(Date.parse(run.created));
}

// The saved run as the events a live audit would have streamed.
function runEvents(run) {
  const obj = (x) => (x && typeof x === "object" && !Array.isArray(x) ? x : null);
  return [
    { type: "start", cited: run.cited, checked: run.checked, limit: null },
    ...arr(run.uncited).map((text) => ({ type: "claim", claim: null, text })),
    ...run.claims.map((c) => (obj(c) && c.claim !== null ? { ...c, type: "claim" } : null)),
    ...arr(run.not_checked).map((c) => (obj(c) ? { ...c, type: "skipped" } : null)),
    ...(str(run.stopped) ? [{ type: "quota", message: run.stopped }] : []),
    { type: "done", tokens: run.tokens },
  ];
}

function replay(run) {
  reset();
  const view = resultsView(run.report);
  for (const ev of runEvents(run)) view.feed(ev);
  lastRun = run;   // "Download results" gives the saved file as it is
  const date = new Date(run.created).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
  setStatus("");
  $("replay-msg").textContent = `Saved example run from ${date}. This is a real Perplexity answer; `
    + "we changed one figure (Samsung 18% → 19%) to show a catch.";
  $("replay").hidden = false;
}

async function loadExample() {
  let text;
  try {
    const resp = await withWakeNotice(() => fetch("/api/example"));
    if (isWakePage(resp, "text/plain")) { setStatus(WAKE_RETRY, true); return; }
    if (!resp.ok) throw new Error();
    text = await resp.text();
  } catch {
    setStatus("Could not load the example.", true);
    return;
  }
  $("report").value = text;
  updateCount();
  let run = null;
  try {
    const resp = await fetch("/api/example-run");
    if (resp.ok && !isWakePage(resp, "application/json")) run = await resp.json();
  } catch {}
  if (validRun(run, text)) replay(run);
  else { reset(); setStatus(EXAMPLE_LOADED); }
}

$("report").addEventListener("input", updateCount);
$("audit").addEventListener("click", runAudit);
$("example").addEventListener("click", loadExample);
$("copy-prompt").addEventListener("click", copyPrompt);
$("download").addEventListener("click", downloadRun);
$("run-live").addEventListener("click", runAudit);
$("cancel").addEventListener("click", () => { if (cancelBusy) cancelBusy(); });
updateCount();
