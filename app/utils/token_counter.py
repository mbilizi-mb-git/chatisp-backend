import asyncio
import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)


class TokenCounter:
    """
    Thread‑safe token counter with daily quota and automatic reset.

    All methods are asynchronous and protected by a lock to allow use
    in concurrent environments (e.g., multiple requests).

    Attributes:
        daily_quota: Maximum tokens allowed per day.
    """

    def __init__(self, daily_quota: int):
        self.daily_quota = daily_quota
        self._total: int = 0
        self._reset_day: date = date.today()
        self._lock = asyncio.Lock()

    async def add(self, tokens: int) -> bool:
        """
        Add tokens to the counter if the quota is not exceeded.

        Returns:
            True if the tokens were added, False if the quota would be exceeded.
        """
        async with self._lock:
            await self._maybe_reset()
            if self._total + tokens > self.daily_quota:
                logger.warning(
                    "Token quota would be exceeded: current %d, requested %d, quota %d",
                    self._total,
                    tokens,
                    self.daily_quota,
                )
                return False
            self._total += tokens
            logger.debug("Added %d tokens, total now %d", tokens, self._total)
            return True

    async def remaining(self) -> int:
        """Return the number of tokens remaining for today."""
        async with self._lock:
            await self._maybe_reset()
            return max(0, self.daily_quota - self._total)

    async def can_add(self, tokens: int) -> bool:
        """
        Check whether adding the given number of tokens would stay within the quota.
        Does not modify the counter.
        """
        async with self._lock:
            await self._maybe_reset()
            return self._total + tokens <= self.daily_quota

    async def _maybe_reset(self) -> None:
        """Reset the counter if the day has changed."""
        today = date.today()
        if today > self._reset_day:
            logger.info(
                "Resetting token counter: previous day %s, total %d",
                self._reset_day,
                self._total,
            )
            self._total = 0
            self._reset_day = today