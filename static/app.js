// Touchstone frontend. Every piece of report text, page text and model output is
// untrusted: it is only ever rendered with textContent, never innerHTML.
"use strict";

const MAX_CHARS = 20000;
const TONES = {
  "SOURCED": "green", "PARTIAL": "yellow", "UNSUPPORTED": "red", "CONTRADICTED": "red",
  "UNVERIFIED": "blue", "OPINION": "blue", "SOURCE UNREACHABLE": "grey",
  "NO SOURCE GIVEN": "grey", "NOT CHECKED": "grey", "ERROR": "grey",
};
// Summary order and wording: "9 sourced, 3 partial, 1 contradicted, 2 unreachable"
const SUMMARY = [
  ["SOURCED", "sourced"], ["PARTIAL", "partial"], ["UNSUPPORTED", "unsupported"],
  ["CONTRADICTED", "contradicted"], ["UNVERIFIED", "unverified"], ["OPINION", "opinion"],
  ["SOURCE UNREACHABLE", "unreachable"], ["NOT CHECKED", "not checked (time limit)"],
  ["ERROR", "failed"],
];
const STATUS_TEXT = { stated: "stated", missing: "not found", contradicted: "contradicted" };

const $ = (id) => document.getElementById(id);
const str = (v) => (typeof v === "string" ? v : "");
const arr = (v) => (Array.isArray(v) ? v : []);
const int = (v) => (Number.isInteger(v) && v >= 0 ? v : null);

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

function setStatus(text, isError = false) {
  $("status").textContent = text;
  $("status").classList.toggle("error", isError);
}

function updateCount() {
  const n = $("report").value.length;
  $("count").textContent = `${n.toLocaleString()} / ${MAX_CHARS.toLocaleString()}`;
  $("count").classList.toggle("over", n > MAX_CHARS);
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

  const parts = el("ul", "parts");
  for (const f of arr(ev.facts)) {
    if (!f || typeof f !== "object") continue;
    const status = str(f.status);
    const li = el("li");
    const ph = el("div", "part-head");
    ph.append(el("span", "tag", STATUS_TEXT[status] || "unclear"), el("span", "", str(f.fact)));
    li.append(ph);
    if (str(f.quote)) li.append(el("blockquote", "", `“${str(f.quote)}”`));
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

  if (str(ev.reason)) card.append(el("p", "reason", str(ev.reason)));

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

function summaryLine(counts, checked) {
  const bits = SUMMARY.filter(([k]) => counts[k]).map(([k, w]) => `${counts[k]} ${w}`);
  for (const [k, v] of Object.entries(counts)) {
    if (!SUMMARY.some(([s]) => s === k)) bits.push(`${v} ${k.toLowerCase()}`);
  }
  const head = `${checked} claim${checked === 1 ? "" : "s"} checked`;
  return bits.length ? `${head}: ${bits.join(", ")}` : head;
}

function reset() {
  $("cards").replaceChildren();
  $("summary").textContent = "";
  $("scope").textContent = "";
  const box = $("uncited");
  box.hidden = true;
  box.open = false;
  box.querySelector("ul").replaceChildren();
  $("nolinks").hidden = true;
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

async function runAudit() {
  const report = $("report").value;
  if (!report.trim()) { setStatus("Paste a report first.", true); return; }
  if (report.length > MAX_CHARS) {
    setStatus(`Reports are limited to ${MAX_CHARS.toLocaleString()} characters.`, true);
    return;
  }
  reset();
  $("audit").disabled = $("example").disabled = true;
  setStatus("Fetching sources…");

  let total = 0, done = 0, finished = false, noLinks = false, sentences = 0;
  const counts = {};

  const handle = (ev) => {
    if (!ev || typeof ev !== "object") throw new Error("bad event");
    if (ev.type === "start") {
      total = int(ev.checked) ?? 0;
      const cited = int(ev.cited) ?? total;
      if (cited === 0) { noLinks = true; return; }   // screen shown at "done"
      $("scope").textContent = cited > total
        ? `Checked ${total} of ${cited} cited claims (claims with numbers first).`
        : `Checked ${total} of ${cited} cited claims.`;
      setStatus(`Fetching ${total} source${total === 1 ? "" : "s"}…`);
    } else if (ev.type === "claim") {
      if (ev.claim === null) {
        if (noLinks) sentences += countSentences(str(ev.text));
        else addUncited(str(ev.text));
        return;
      }
      done += 1;
      const label = str(ev.label) || "UNKNOWN";
      counts[label] = (counts[label] || 0) + 1;
      $("cards").append(renderCard(ev));
      setStatus(done < total ? `Claim ${done}/${total} done, checking the next…` : `Claim ${done}/${total} done`);
    } else if (ev.type === "done") {
      finished = true;
      if (noLinks) { showNoLinks(sentences); return; }
      if (total) setStatus(`Done. Claim ${done}/${total}.`);
      if (done) $("summary").textContent = summaryLine(counts, done);
    } else if (ev.type === "error") {
      setStatus(str(ev.error) || "The audit failed.", true);
    }
  };

  const showBad = () => {
    const card = el("article", "card tone-grey");
    card.append(el("p", "reason", "One result could not be read and was skipped."));
    $("cards").append(card);
  };

  try {
    const resp = await fetch("/api/audit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ report }),
    });
    if (!resp.ok || !resp.body) {
      let msg = `The server refused the audit (HTTP ${resp.status}).`;
      try { msg = str((await resp.json()).error) || msg; } catch {}
      setStatus(msg, true);
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
        try { handle(JSON.parse(line)); } catch { showBad(); }
      }
      if (eof) break;
    }
    if (!finished && !$("status").classList.contains("error")) {
      setStatus(`The connection ended early. Claim ${done}/${total} done.`, true);
      if (done) $("summary").textContent = summaryLine(counts, done);
    }
  } catch {
    setStatus("Could not reach the server.", true);
  } finally {
    $("audit").disabled = $("example").disabled = false;
  }
}

async function loadExample() {
  try {
    const resp = await fetch("/api/example");
    if (!resp.ok) throw new Error();
    $("report").value = await resp.text();
    updateCount();
    setStatus("Example loaded: an AI research report on Algeria's startup ecosystem. Press Audit.");
  } catch {
    setStatus("Could not load the example.", true);
  }
}

$("report").addEventListener("input", updateCount);
$("audit").addEventListener("click", runAudit);
$("example").addEventListener("click", loadExample);
$("copy-prompt").addEventListener("click", copyPrompt);
updateCount();
