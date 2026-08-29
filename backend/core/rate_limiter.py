"""Small in-process rate limiters for security-sensitive API operations.

The production deployment should eventually move these counters to Redis so
all API workers share one window.  Keeping the dependency-free implementation
here still gives local development and the single-worker deployment a real
brute-force guard instead of leaving the endpoints unprotected.
"""

import time
from collections import defaultdict
from fastapi import HTTPException, Request, status


class RateLimiter:
  """In-memory sliding window rate limiter per IP / user identifier."""

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
          detail="Too many attempts. Please try again later.",
          headers={"Retry-After": str(self.window_seconds)},
      )

    self.requests[identifier].append(now)


# Global rate limiter instance (100 requests / min per IP)
global_rate_limiter = RateLimiter(max_requests=100, window_seconds=60)

# These are intentionally separate buckets: a user who has exhausted pairing
# attempts should not also be able to exhaust recovery attempts, and normal
# authenticated API traffic must not consume security-operation capacity.
pairing_rate_limiter = RateLimiter(max_requests=20, window_seconds=60)
reclaim_rate_limiter = RateLimiter(max_requests=8, window_seconds=60)
bootstrap_rate_limiter = RateLimiter(max_requests=20, window_seconds=60)
help_call_rate_limiter = RateLimiter(max_requests=12, window_seconds=60)


def _client_identifier(request: Request, bucket: str) -> str:
    """Return a stable limiter key with reverse proxy IP header resolution."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # First IP in X-Forwarded-For is the originating client
        host = forwarded.split(",")[0].strip()
    else:
        host = request.headers.get("X-Real-IP") or (
            request.client.host if request.client else "unknown"
        )
    return f"{bucket}:{host}"


def limit_pairing_attempts(request: Request) -> None:
  """Limit setup-code claim/approval attempts by source IP."""
  pairing_rate_limiter.check_rate_limit(_client_identifier(request, "pairing"))


def limit_reclaim_attempts(request: Request) -> None:
  """Limit recovery-code guesses by source IP."""
  reclaim_rate_limiter.check_rate_limit(_client_identifier(request, "reclaim"))


def limit_bootstrap_attempts(request: Request) -> None:
  """Limit unauthenticated device-account creation attempts by source IP."""
  bootstrap_rate_limiter.check_rate_limit(_client_identifier(request, "bootstrap"))


def limit_help_call_attempts(request: Request) -> None:
  """Limit repeated rings by source IP."""
  help_call_rate_limiter.check_rate_limit(_client_identifier(request, "help-call"))
