"""Model providers. PROVIDER=groq (default) checks one claim per call against ~3,000 chars of
selected excerpts (Groq's free tier allows 8K tokens/minute). PROVIDER=gemini sends each cited
page once, whole (up to PAGE_CHARS), with every claim citing it, and gets one result per claim.
Either way the model only reports: judge() (quote_check.py) applies the same code checks and
decides every label."""
import json
import os

from pydantic import BaseModel, Field

from quote_check import GROQ_TIMEOUT, MODEL as GROQ_MODEL, SYSTEM_MULTI, ask, best_excerpts, finish, safe_judge

GEMINI_MODEL = "gemini-3.5-flash-lite"   # verified in Google's model list, 2026-10-09
PAGE_CHARS = 100_000                     # page text per Gemini call (~25K tokens)
GEMINI_TIMEOUT_MS = 90_000               # a 100K-char page takes longer than one excerpt
OUTPUT_TOKENS_PER_CLAIM = 600            # for the pacing estimate only
CLAIMS_PER_CALL = 10                     # a page cited by more claims gets several calls
# Reply cap per call. The model allows 65,536 output tokens (models.get, 2026-10-11) and
# thinks by default; thinking counts against this cap. 10 claims x ~600 tokens of JSON is
# ~6K, so 32K leaves room for thinking while bounding a runaway reply. A reply cut off here
# is unparseable: its claims become ERROR, never a verdict.
MAX_OUTPUT_TOKENS = 32_768


def provider_name():
    name = os.environ.get("PROVIDER", "groq").strip().lower() or "groq"
    if name not in ("groq", "gemini"):
        raise SystemExit(f"PROVIDER must be groq or gemini, not {name!r}")
    return name


def make_client(name):
    """The provider's SDK client, key from the environment only (never logged)."""
    if name == "gemini":
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise SystemExit("GEMINI_API_KEY missing (set it in .env or the host's variables)")
        from google import genai
        from google.genai import types
        return genai.Client(api_key=key, http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS))
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise SystemExit("GROQ_API_KEY missing from .env")
    from groq import Groq
    # max_retries=0: audit() does the retrying (pacing.py), visibly.
    return Groq(api_key=key, timeout=GROQ_TIMEOUT, max_retries=0)


# Response schema for Gemini: the per-claim JSON judge() already consumes, in a list.
class Part(BaseModel):
    text: str
    kind: str = Field(description='"fact" or "framing"')
    status: str = Field(description='facts: "stated", "missing" or "contradicted"; framing: ""')
    quote: str = Field(description='for stated/contradicted: one sentence copied exactly from the excerpts; else ""')


class ClaimResult(BaseModel):
    id: int
    opinion: bool
    parts: list[Part]


class Results(BaseModel):
    claims: list[ClaimResult]


def page_for_model(page, claims, cap=PAGE_CHARS):
    """The page text to send: all of it up to `cap` chars. A longer page keeps the lines of
    each claim's anchor-selected passages (best_excerpts) and grows outward from them, line
    by line, until the cap; skipped stretches show as "[...]". Lines stay verbatim, so
    quotes still verify against the page."""
    if len(page) <= cap:
        return page
    lines = page.split("\n")
    where = {}
    for i, line in enumerate(lines):
        where.setdefault(line.strip(), i)
    keep, total = set(), 0
    seeds = [where[x.strip()] for c in claims for p in best_excerpts(c, page) for x in p.split("\n")
             if x.strip() in where]

    def add(i):
        nonlocal total
        if 0 <= i < len(lines) and i not in keep and total + len(lines[i]) + 1 <= cap:
            keep.add(i)
            total += len(lines[i]) + 1
            return True
        return False

    for i in dict.fromkeys(seeds):
        add(i)
    for r in range(1, len(lines)):
        grew = [add(i - r) | add(i + r) for i in sorted(set(seeds))]
        if not any(grew) or total >= cap - 200:
            break
    if not keep:                                  # no anchors (or one giant line): the top
        return page[:cap]
    out, prev = [], -1
    for i in sorted(keep):
        if i != prev + 1:
            out.append("[...]")
        out.append(lines[i])
        prev = i
    if prev != len(lines) - 1:
        out.append("[...]")
    return "\n".join(out)


def gemini_prompt(claims, text, sentences=None):
    """sentences: per claim, the full sentence a fragment claim was cut from ("" if none)."""
    sentences = sentences or [""] * len(claims)
    numbered = "\n".join(f"[{i}] {c}" + (f"\n    FULL SENTENCE (context only): {s}" if s else "")
                         for i, (c, s) in enumerate(zip(claims, sentences), 1))
    return "CLAIMS:\n" + numbered + "\n\nEXCERPTS:\n<<<\n" + text + "\n>>>"


class Groq:
    """One call per claim (quote_check.check): unchanged behaviour. audit() retries ask()
    only; finish() runs the code checks once, outside the retries."""
    name, model, per_source = "groq", GROQ_MODEL, False

    def __init__(self, client):
        self.client = client

    def ask(self, claim, page, timeout=None, sentence=""):
        return ask(self.client, claim, page, timeout, sentence)

    def finish(self, got, claim, page, url, meta=None, context=""):
        return finish(got, claim, page, url, meta, context)

    def check(self, claim, page, url, meta=None, context=""):
        return self.finish(self.ask(claim, page), claim, page, url, meta, context)


class Gemini:
    """One call per cited page, with all its claims."""
    name, model, per_source = "gemini", GEMINI_MODEL, True
    claims_per_call = CLAIMS_PER_CALL
    show_raw = False                              # CLI --show-raw: print the model's reply

    def __init__(self, client):
        self.client = client

    def estimate(self, claims, page):
        """Tokens a call will use, for pacing: ~4 chars per token in, plus output."""
        sent = len(SYSTEM_MULTI) + len(gemini_prompt(claims, page_for_model(page, claims)))
        return sent // 4 + OUTPUT_TOKENS_PER_CLAIM * len(claims)

    def ask_source(self, claims, page, timeout=None, sentences=None):
        """The model call (retried by audit()): (raw reply, tokens). timeout: seconds left
        before the audit's deadline; the request is abandoned (connection closed) after it."""
        from google.genai import types
        text = page_for_model(page, claims)
        ms = GEMINI_TIMEOUT_MS if timeout is None else max(1000, min(GEMINI_TIMEOUT_MS, int(timeout * 1000)))
        resp = self.client.models.generate_content(
            model=self.model, contents=gemini_prompt(claims, text, sentences),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_MULTI, temperature=0, seed=0, max_output_tokens=MAX_OUTPUT_TOKENS,
                response_mime_type="application/json", response_schema=Results,
                http_options=types.HttpOptions(timeout=ms)))
        raw = resp.text or ""
        if self.show_raw:
            print("---- raw Gemini reply ----\n" + raw + "\n--------------------------")
        usage = getattr(resp, "usage_metadata", None)
        return raw, (getattr(usage, "total_token_count", 0) or 0) if usage else 0

    def finish_source(self, got, claims, page, url, meta=None, contexts=None):
        """Results for `claims` (all citing this page), same order, and the call's tokens.
        Each result is judge() output plus "tokens" (the call's total, split evenly)."""
        raw, tokens = got
        return map_results(raw, claims, page, url, meta, tokens, contexts), tokens

    def check_source(self, claims, page, url, meta=None, contexts=None):
        return self.finish_source(self.ask_source(claims, page), claims, page, url, meta, contexts)


def map_results(raw, claims, page, url, meta, tokens, contexts=None):
    """Model JSON -> one judge() result per claim, by id. Untrusted: anything malformed or
    missing becomes that claim's ERROR, never a verdict."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        data = {}
    items = data.get("claims") if isinstance(data, dict) and isinstance(data.get("claims"), list) else []
    by_id = {}
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("id"), int) and item["id"] not in by_id:
            by_id[item["id"]] = item
    share = [tokens // len(claims) + (1 if i < tokens % len(claims) else 0) for i in range(len(claims))]
    out = []
    for i, claim in enumerate(claims, 1):
        item = by_id.get(i)
        if item is None:
            r = {"label": "ERROR", "quote": "", "reason": "The model returned no result for this claim.",
                 "facts": [], "framing": [], "model": None}
        else:
            reply = {"opinion": item.get("opinion") is True, "parts": item.get("parts")}
            r = safe_judge(reply, claim, page, url, json.dumps(item)[:200], meta,
                           (contexts or [""] * len(claims))[i - 1])
        r["tokens"] = share[i - 1]
        out.append(r)
    return out


def make_provider(name, client):
    return (Gemini if name == "gemini" else Groq)(client)
