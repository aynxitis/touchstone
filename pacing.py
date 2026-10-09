"""Per-provider rate pacing. Free tiers cap tokens per minute (TPM), requests per minute (RPM)
and requests per day (RPD). Fast page fetches let an audit fire calls faster than that, so
instead of stopping on a per-minute 429 the audit waits: proactively (TokenPacer, from each
response's usage) and reactively (a 429's retry-after). Clock injectable: tests never sleep.

Limits (with a safety margin under each provider's published free-tier numbers):
  groq   openai/gpt-oss-120b      8K TPM -> 7,500   (RPM/RPD not paced: TPM binds first)
  gemini gemini-3.5-flash-lite    250K TPM -> 225,000, 15 RPM -> 13, 500 RPD -> 450"""
import re
import time
from collections import deque
from datetime import datetime, timezone

WINDOW = 60.0           # seconds
BUDGET = 7_500          # Groq tokens per window: under 8K with a margin (default limits)
DEFAULT_ESTIMATE = 1_800  # tokens for a Groq claim before any has been measured
RETRY_FALLBACK = 10.0   # seconds to wait on a per-minute 429 that names no wait
RETRY_MAX = 60.0
DAY_FULL = float("inf")  # wait_needed() result: the provider's requests for today are used up

LIMITS = {
    "groq": {"tpm": 7_500, "rpm": None, "rpd": None},
    "gemini": {"tpm": 225_000, "rpm": 13, "rpd": 450},
}


def utc_day():
    return datetime.now(timezone.utc).date()


class TokenPacer:
    """Tokens and requests in the trailing WINDOW seconds, plus requests per UTC day. One per
    process and provider (app.py): consecutive audits share the provider's minute and day."""

    def __init__(self, budget=BUDGET, window=WINDOW, clock=time.monotonic, rpm=None, rpd=None,
                 day=utc_day):
        self.budget, self.window, self.clock = budget, window, clock
        self.rpm, self.rpd, self.day = rpm, rpd, day
        self.spent = deque()              # (time, tokens)
        self.requests = deque()           # times of recent requests (RPM)
        self.today, self.day_count = None, 0
        self.recent = deque(maxlen=10)    # tokens of the last calls, for the estimate

    @classmethod
    def for_provider(cls, name, **kw):
        lim = LIMITS[name]
        return cls(budget=lim["tpm"], rpm=lim["rpm"], rpd=lim["rpd"], **kw)

    def _expire(self, now):
        while self.spent and self.spent[0][0] <= now - self.window:
            self.spent.popleft()
        while self.requests and self.requests[0] <= now - self.window:
            self.requests.popleft()

    def _roll_day(self):
        if self.day() != self.today:
            self.today, self.day_count = self.day(), 0

    def record(self, tokens):
        if tokens > 0:
            now = self.clock()
            self.spent.append((now, tokens))
            self.recent.append(tokens)

    def note_request(self):
        """A request is about to go out (counts for RPM/RPD even if it then fails)."""
        self._roll_day()
        self.day_count += 1
        self.requests.append(self.clock())

    def estimate(self):
        return max(self.recent) if self.recent else DEFAULT_ESTIMATE

    def wait_needed(self, need=None):
        """Seconds to wait before a call of `need` tokens (default: estimate()) fits the
        minute's token and request budgets; 0 if it fits now; DAY_FULL if today's request
        budget is used up (waiting won't help)."""
        if self.rpd is not None:
            self._roll_day()
            if self.day_count >= self.rpd:
                return DAY_FULL
        now = self.clock()
        self._expire(now)
        waits = [0.0]
        if self.rpm is not None and len(self.requests) >= self.rpm:
            waits.append(self.requests[len(self.requests) - self.rpm] + self.window - now)
        need = self.estimate() if need is None else need
        used = sum(t for _, t in self.spent)
        if used + need > self.budget:
            for ts, tokens in self.spent:     # oldest first: when does enough expire?
                used -= tokens
                if used + need <= self.budget:
                    waits.append(ts + self.window - now)
                    break
        return max(0.0, max(waits))


RETRY_IN = re.compile(r"(?:try again|retry) in (?:(\d{1,4})m)?(\d{1,5}(?:\.\d{1,6})?)(ms|s)\b", re.I)
RETRY_DELAY = re.compile(r"retryDelay['\"]?\s{0,3}:\s{0,3}['\"](\d{1,5}(?:\.\d{1,6})?)s", re.I)


def retry_after(err):
    """Seconds a per-minute 429 asks us to wait: the Retry-After header, else the message
    (Groq "Please try again in 7.66s" / "1m2.5s" / "450ms"; Gemini "Please retry in 34.5s" or
    "retryDelay": "34s"), else RETRY_FALLBACK. Capped."""
    headers = getattr(getattr(err, "response", None), "headers", None) or {}
    try:
        secs = float(headers.get("retry-after"))
    except (TypeError, ValueError):
        text = f"{err} {getattr(err, 'body', '')} {getattr(err, 'details', '')}"
        if m := RETRY_IN.search(text):
            secs = int(m[1] or 0) * 60 + float(m[2]) / (1000 if m[3].lower() == "ms" else 1)
        elif m := RETRY_DELAY.search(text):
            secs = float(m[1])
        else:
            secs = RETRY_FALLBACK
    return min(max(secs, 0.0) + 0.5, RETRY_MAX)   # +0.5 s: land after the window frees up
