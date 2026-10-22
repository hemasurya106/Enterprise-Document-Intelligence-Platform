"""
Simple in-process circuit breaker + hard timeout wrapper for Gemini API calls.

States
------
  CLOSED    — normal operation; failures are counted.
  OPEN      — threshold breached; calls are rejected immediately (fast-fail).
  HALF_OPEN — recovery probe; one call is allowed through.

Configuration (module-level constants — tune via env vars if needed):
  FAILURE_THRESHOLD  = 3    consecutive failures to trip the breaker
  RECOVERY_TIMEOUT_S = 60   seconds before OPEN → HALF_OPEN probe
  CALL_TIMEOUT_S     = 15   hard timeout per Gemini API call

Why in-process instead of Redis-backed?
  Each Celery worker is a separate OS process running the same blocking
  SDK calls.  A per-process breaker provides isolation: one worker tripping
  doesn't immediately block the others, which is the right behaviour when
  a single worker is overwhelmed.  If you want coordinated state across all
  workers, replace _state with Redis keys (straightforward to add later).

Usage
-----
    from app.utils.gemini_circuit_breaker import gemini_breaker

    result = gemini_breaker.call(model.generate_content, [prompt, img])
    if result is None:
        # breaker is OPEN or call timed out — use fallback
        ...
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("app.gemini_circuit_breaker")

FAILURE_THRESHOLD  = int(3)
RECOVERY_TIMEOUT_S = float(60)
CALL_TIMEOUT_S     = float(15)


class _State(Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


class GeminiCircuitBreaker:
    """Thread-safe circuit breaker for synchronous Gemini SDK calls."""

    def __init__(
        self,
        failure_threshold:  int   = FAILURE_THRESHOLD,
        recovery_timeout_s: float = RECOVERY_TIMEOUT_S,
        call_timeout_s:     float = CALL_TIMEOUT_S,
    ) -> None:
        self._threshold        = failure_threshold
        self._recovery_timeout = recovery_timeout_s
        self._call_timeout     = call_timeout_s

        self._state:             _State = _State.CLOSED
        self._failure_count:     int    = 0
        self._last_failure_time: float  = 0.0
        self._lock:              threading.Lock = threading.Lock()

        # Dedicated executor so Gemini calls don't consume the main thread pool
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="gemini_cb")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def call(self, fn: Callable, *args: Any, **kwargs: Any) -> Any | None:
        """
        Execute `fn(*args, **kwargs)` with timeout and circuit-breaker logic.

        Returns the call's return value on success, or ``None`` on:
          - circuit OPEN (fast-fail)
          - call timeout
          - unhandled exception from fn

        Callers should treat ``None`` as "Gemini unavailable, use fallback".
        """
        with self._lock:
            state = self._state
            if state == _State.OPEN:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self._recovery_timeout:
                    logger.info(
                        "Circuit breaker: OPEN → HALF_OPEN after %.0fs",
                        elapsed,
                        extra={"circuit_state": "half_open"},
                    )
                    self._state = _State.HALF_OPEN
                    state = _State.HALF_OPEN
                else:
                    logger.warning(
                        "Circuit breaker OPEN — fast-failing Gemini call "
                        "(%.0fs until probe)",
                        self._recovery_timeout - elapsed,
                        extra={"circuit_state": "open"},
                    )
                    return None

        # Execute the call outside the lock so other threads aren't blocked
        try:
            future = self._executor.submit(fn, *args, **kwargs)
            result = future.result(timeout=self._call_timeout)
            self._on_success()
            return result

        except FutureTimeoutError:
            logger.warning(
                "Circuit breaker: Gemini call timed out after %.0fs",
                self._call_timeout,
                extra={"circuit_state": self._state.value, "timeout_s": self._call_timeout},
            )
            self._on_failure()
            return None

        except Exception as exc:
            logger.warning(
                "Circuit breaker: Gemini call raised %s: %s",
                type(exc).__name__,
                exc,
                extra={"circuit_state": self._state.value},
            )
            self._on_failure()
            return None

    @property
    def state(self) -> str:
        return self._state.value

    # ------------------------------------------------------------------
    # Internal state transitions
    # ------------------------------------------------------------------

    def _on_success(self) -> None:
        with self._lock:
            if self._state == _State.HALF_OPEN:
                logger.info(
                    "Circuit breaker: HALF_OPEN → CLOSED (probe succeeded)",
                    extra={"circuit_state": "closed"},
                )
            self._state         = _State.CLOSED
            self._failure_count = 0

    def _on_failure(self) -> None:
        with self._lock:
            self._failure_count    += 1
            self._last_failure_time = time.monotonic()

            if self._state == _State.HALF_OPEN:
                # Probe failed — go back to OPEN immediately
                logger.warning(
                    "Circuit breaker: HALF_OPEN probe failed → OPEN",
                    extra={"circuit_state": "open"},
                )
                self._state = _State.OPEN
                return

            if self._failure_count >= self._threshold:
                logger.error(
                    "Circuit breaker: CLOSED → OPEN after %d consecutive failures",
                    self._failure_count,
                    extra={
                        "circuit_state": "open",
                        "failures":      self._failure_count,
                        "threshold":     self._threshold,
                    },
                )
                self._state = _State.OPEN


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere Gemini Vision is called
# ---------------------------------------------------------------------------
gemini_breaker = GeminiCircuitBreaker()
