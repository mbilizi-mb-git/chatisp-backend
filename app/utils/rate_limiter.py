import asyncio
import logging
import time
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)


class RateLimitExceeded(Exception):
    """Raised when the rate limit is exceeded and the required wait time exceeds max_wait."""

    def __init__(self, wait_time: int):
        self.wait_time = wait_time
        super().__init__(f"Rate limit exceeded. Try again in {wait_time} seconds.")


class RateLimiter:
    """
    Asynchronous rate limiter using a sliding window of timestamps.

    Attributes:
        max_calls: Maximum number of calls allowed in the period.
        period: Time window in seconds.
        max_wait: Maximum time (seconds) the caller is willing to wait.
                  If the required wait exceeds this, RateLimitExceeded is raised.
    """

    def __init__(self, max_calls: int, period: int, max_wait: int):
        self.max_calls = max_calls
        self.period = period
        self.max_wait = max_wait
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """
        Acquire permission to proceed. If the rate limit is exceeded, either wait
        (if wait time <= max_wait) or raise RateLimitExceeded.

        Raises:
            RateLimitExceeded: if required wait time > max_wait.
        """
        async with self._lock:
            now = time.monotonic()
            # Remove calls older than the period
            while self._calls and self._calls[0] < now - self.period:
                self._calls.popleft()

            if len(self._calls) < self.max_calls:
                # Room available, record this call and proceed
                self._calls.append(now)
                return

            # Rate limit reached; calculate wait time until next slot
            earliest = self._calls[0]
            wait_time = earliest + self.period - now
            if wait_time > self.max_wait:
                logger.warning(
                    "Rate limit exceeded, required wait %ds > max wait %ds",
                    wait_time,
                    self.max_wait,
                )
                raise RateLimitExceeded(int(wait_time))

            # Wait and then record
            logger.debug("Rate limit reached, waiting %.2f seconds", wait_time)
            await asyncio.sleep(wait_time)

            # After waiting, record the call
            now = time.monotonic()
            # Clean up again (though the wait might have shifted things)
            while self._calls and self._calls[0] < now - self.period:
                self._calls.popleft()
            self._calls.append(now)