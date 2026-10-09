"""Groq per-minute pacing (free tier: 8K tokens/minute, ~1.7K per claim). Fast page fetches
let an audit fire claims faster than that, so instead of stopping on a per-minute 429 the
audit waits: proactively (TokenPacer, from each response's usage) and reactively (a 429's
retry-after). Clock injectable: tests never really sleep."""
import re
import time
from collections import deque

WINDOW = 60.0           # seconds
BUDGET = 7_500          # tokens per window: under Groq's 8K with a margin
DEFAULT_ESTIMATE = 1_800  # tokens for a claim before any has been measured
RETRY_FALLBACK = 10.0   # seconds to wait on a per-minute 429 that names no wait
RETRY_MAX = 60.0


class TokenPacer:
    """Tokens spent in the trailing WINDOW seconds. One per process (app.py): consecutive
    audits share Groq's minute."""

    def __init__(self, budget=BUDGET, window=WINDOW, clock=time.monotonic):
        self.budget, self.window, self.clock = budget, window, clock
        self.spent = deque()              # (time, tokens)
        self.recent = deque(maxlen=10)    # tokens of the last calls, for the estimate

    def _expire(self, now):
        while self.spent and self.spent[0][0] <= now - self.window:
            self.spent.popleft()

    def record(self, tokens):
        if tokens > 0:
            now = self.clock()
            self.spent.append((now, tokens))
            self.recent.append(tokens)

    def estimate(self):
        return max(self.recent) if self.recent else DEFAULT_ESTIMATE

    def wait_needed(self):
        """Seconds to wait before the next call fits in the window (0 if it fits now)."""
        now = self.clock()
        self._expire(now)
        need, used = self.estimate(), sum(t for _, t in self.spent)
        if used + need <= self.budget:
            return 0.0
        for ts, tokens in self.spent:     # oldest first: when does enough expire?
            used -= tokens
            if used + need <= self.budget:
                return max(0.0, ts + self.window - now)
        return 0.0                        # unreachable: the empty window always fits


RETRY_IN = re.compile(r"try again in (?:(\d{1,4})m)?(\d{1,5}(?:\.\d{1,6})?)(ms|s)\b", re.I)


def retry_after(err):
    """Seconds a per-minute 429 asks us to wait: the Retry-After header, else Groq's message
    ("Please try again in 7.66s" / "1m2.5s" / "450ms"), else RETRY_FALLBACK. Capped."""
    headers = getattr(getattr(err, "response", None), "headers", None) or {}
    try:
        secs = float(headers.get("retry-after"))
    except (TypeError, ValueError):
        m = RETRY_IN.search(f"{err} {getattr(err, 'body', '')}")
        if m:
            secs = int(m[1] or 0) * 60 + float(m[2]) / (1000 if m[3].lower() == "ms" else 1)
        else:
            secs = RETRY_FALLBACK
    return min(max(secs, 0.0) + 0.5, RETRY_MAX)   # +0.5 s: land after the window frees up
