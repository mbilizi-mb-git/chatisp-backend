import time
from typing import Optional

class TTLCache:
    """Simple cache with time-to-live (TTL) in seconds."""
    def __init__(self, default_ttl: int = 60):
        self._cache = {}
        self.default_ttl = default_ttl

    def get(self, key: str) -> Optional[bool]:
        """Return cached value if exists and not expired."""
        entry = self._cache.get(key)
        if entry:
            value, expiry = entry
            if time.time() < expiry:
                return value
            else:
                del self._cache[key]
        return None

    def set(self, key: str, value: bool, ttl: Optional[int] = None):
        """Store value with TTL (default 30s)."""
        if ttl is None:
            ttl = self.default_ttl
        expiry = time.time() + ttl
        self._cache[key] = (value, expiry)

# Instance globale pour le cache des emails
email_cache = TTLCache(default_ttl=30)