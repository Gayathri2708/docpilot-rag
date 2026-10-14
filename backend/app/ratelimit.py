"""In-memory rate limits for a public deployment: a per-client sliding window and a global daily cap.

The daily cap is the hard guarantee for the LLM budget: it cannot be dodged by changing IP or
spoofing headers. Limits live in process memory, so they assume a single worker process (which is
how the Dockerfile runs DocPilot) and reset on restart.
"""

import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime


class RateLimiter:
    def __init__(self, clock=time.monotonic, today=lambda: datetime.now(UTC).date()):
        self._clock = clock
        self._today = today
        self._lock = threading.Lock()
        self._windows: dict[str, deque[float]] = defaultdict(deque)
        self._day = None
        self._day_count = 0

    def check_client(self, client: str, per_minute: int) -> float | None:
        """Record a request from `client`. Returns None if allowed, else seconds until it would be."""
        if per_minute <= 0:
            return None
        now = self._clock()
        with self._lock:
            window = self._windows[client]
            while window and window[0] <= now - 60:
                window.popleft()
            if len(window) >= per_minute:
                return max(0.0, window[0] + 60 - now)
            window.append(now)
            if len(self._windows) > 10_000:  # forget idle clients so memory stays bounded
                for key in [k for k, w in self._windows.items() if not w or w[-1] <= now - 60]:
                    del self._windows[key]
            return None

    def check_daily(self, per_day: int) -> bool:
        """Record one request against the global daily cap (UTC days). Returns False once it is used up."""
        if per_day <= 0:
            return True
        today = self._today()
        with self._lock:
            if today != self._day:
                self._day, self._day_count = today, 0
            if self._day_count >= per_day:
                return False
            self._day_count += 1
            return True

    def reset(self) -> None:
        with self._lock:
            self._windows.clear()
            self._day, self._day_count = None, 0
