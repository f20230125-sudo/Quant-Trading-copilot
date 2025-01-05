import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    """In-memory per-key limit of ``limit`` hits per ``window_s`` seconds.

    Good enough for a single-process demo; a multi-instance deployment would need Redis.
    """

    def __init__(self, limit: int, window_s: float = 60.0):
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        hits = self._hits[key]
        while hits and hits[0] <= now - self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True
