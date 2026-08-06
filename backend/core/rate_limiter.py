"""API Rate Limiting Middleware for Brute-Force & DDoS Protection."""

import time
from collections import defaultdict
from fastapi import HTTPException, Request, status


class RateLimiter:
  """In-memory sliding window rate limiter per IP / User."""

  def __init__(
      self, max_requests: int = 100, window_seconds: int = 60
  ) -> None:
    self.max_requests = max_requests
    self.window_seconds = window_seconds
    self.requests: dict[str, list[float]] = defaultdict(list)

  def check_rate_limit(self, identifier: str) -> None:
    """Enforce sliding window rate limit.

    Raises HTTPException 429 Too Many Requests if limit exceeded.
    """
    now = time.time()
    window_start = now - self.window_seconds

    # Filter out requests older than window_seconds
    timestamps = [t for t in self.requests[identifier] if t > window_start]
    self.requests[identifier] = timestamps

    if len(timestamps) >= self.max_requests:
      raise HTTPException(
          status_code=status.HTTP_429_TOO_MANY_REQUESTS,
          detail="Rate limit exceeded. Please try again later.",
          headers={"Retry-After": str(self.window_seconds)},
      )

    self.requests[identifier].append(now)


# Global rate limiter instance (100 requests / min per IP)
global_rate_limiter = RateLimiter(max_requests=100, window_seconds=60)
