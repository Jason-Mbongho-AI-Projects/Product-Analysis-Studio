"""Token-bucket rate limiting (spec 41).

In-process and per-key. That is the right size for a single-instance deployment
and honest about its limit: running two API processes would give each its own
bucket, so a shared store would be needed before horizontal scaling.

A token bucket rather than a fixed window because a fixed window lets a caller
burst 2x the limit across a boundary — 60 requests at 11:59:59 and 60 more at
12:00:00.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class Bucket:
    capacity: float
    tokens: float
    refill_per_second: float
    last_refill: float = field(default_factory=time.monotonic)

    def consume(self, amount: float = 1.0) -> tuple[bool, float]:
        """Try to take a token. Returns ``(allowed, retry_after_seconds)``."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.last_refill = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_second)

        if self.tokens >= amount:
            self.tokens -= amount
            return True, 0.0

        needed = amount - self.tokens
        return False, needed / self.refill_per_second if self.refill_per_second else 60.0


class RateLimiter:
    """Per-key token buckets, safe across request threads."""

    def __init__(self, *, burst_multiplier: float = 1.5) -> None:
        self._buckets: dict[str, Bucket] = {}
        self._lock = threading.Lock()
        self._burst_multiplier = burst_multiplier

    def check(self, key: str, per_minute: int) -> tuple[bool, float]:
        """Consume one token for ``key``. Returns ``(allowed, retry_after)``."""
        per_minute = max(1, int(per_minute))
        # A little burst headroom, so a legitimate client issuing a short batch
        # is not punished for a rate it stays under on average.
        capacity = per_minute * self._burst_multiplier

        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None or bucket.capacity != capacity:
                bucket = Bucket(
                    capacity=capacity,
                    tokens=capacity,
                    refill_per_second=per_minute / 60.0,
                )
                self._buckets[key] = bucket
            return bucket.consume()

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._buckets.clear()
            else:
                self._buckets.pop(key, None)

    def prune(self, max_buckets: int = 10_000) -> int:
        """Drop the least recently refilled buckets if the map grows unbounded."""
        with self._lock:
            if len(self._buckets) <= max_buckets:
                return 0
            ordered = sorted(self._buckets.items(), key=lambda item: item[1].last_refill)
            drop = len(self._buckets) - max_buckets
            for key, _bucket in ordered[:drop]:
                self._buckets.pop(key, None)
            return drop


#: Process-wide limiter shared by every API worker thread.
limiter = RateLimiter()
