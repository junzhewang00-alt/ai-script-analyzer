from collections import defaultdict, deque
import time
from functools import wraps
from flask import request, jsonify, flash, redirect, url_for


class RateLimiter:
    """Simple in-memory sliding-window rate limiter with automatic cleanup."""

    def __init__(self, cleanup_interval_s: float = 300):
        self._windows: dict[str, deque[float]] = defaultdict(deque)
        self._last_cleanup = time.monotonic()
        self._cleanup_interval_s = cleanup_interval_s

    def is_allowed(self, key: str, max_requests: int, window_s: float = 60) -> bool:
        now = time.monotonic()
        cutoff = now - window_s
        bucket = self._windows[key]

        # lazy cleanup of expired entries for this key
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        if len(bucket) >= max_requests:
            return False

        bucket.append(now)

        # periodic cleanup of stale keys
        if now - self._last_cleanup > self._cleanup_interval_s:
            self._purge_expired_keys(now)
            self._last_cleanup = now

        return True

    def _purge_expired_keys(self, now: float):
        """Remove keys whose buckets are entirely empty."""
        stale = [k for k, v in self._windows.items() if not v]
        for k in stale:
            del self._windows[k]


_limiter = RateLimiter()


def rate_limit(max_requests: int, window_s: int = 60):
    """Decorator for JSON endpoints: 429 + json message."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            ip = request.remote_addr or "127.0.0.1"
            key = f"rl:{request.path}:{ip}"
            if not _limiter.is_allowed(key, max_requests, window_s):
                return jsonify({"error": "请求过于频繁，请稍后再试"}), 429
            return f(*args, **kwargs)
        return wrapper
    return decorator


def rate_limit_form(max_requests: int, window_s: int = 60, fallback: str = "auth.login"):
    """Decorator for HTML form endpoints: flash + redirect to fallback."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            ip = request.remote_addr or "127.0.0.1"
            key = f"rl:{request.path}:{ip}"
            if not _limiter.is_allowed(key, max_requests, window_s):
                flash("请求过于频繁，请稍后再试", "error")
                return redirect(url_for(fallback))
            return f(*args, **kwargs)
        return wrapper
    return decorator
