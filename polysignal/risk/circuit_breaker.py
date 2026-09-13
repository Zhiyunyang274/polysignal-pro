"""

Circuit Breaker - system-halt state machine (D12 resolution)

IMPORTANT:
- Consumes the `circuit_breaker` section of config/risk.yaml
  (max_api_failures / max_ws_disconnects / stale_data_threshold_seconds).
- Pure in-process state machine: it counts consecutive failures and flips
  tripped flags; it never places orders or mutates global state.
- Runners feed it evidence (record_api_failure / record_api_success / ...) and
  mirror its health into RiskContext so Risk Governor hard rejects fire
  (api_unhealthy / websocket_unhealthy).
- Recovery is evidence-based (standard half-open -> closed transition): one
  API success clears the API counter and un-trips the API channel; one
  successful (re)connect clears the WS counter and un-trips the WS channel.
  reset() is the manual operator override.
"""

from __future__ import annotations

from datetime import datetime

from polysignal.utils.time import ensure_utc, utc_now


class CircuitBreaker:
    """Consecutive-failure breaker for the API and WebSocket channels."""

    def __init__(
        self,
        max_api_failures: int = 5,
        max_ws_disconnects: int = 3,
        stale_data_threshold_seconds: int = 60,
    ):
        if max_api_failures <= 0:
            raise ValueError("max_api_failures must be positive")
        if max_ws_disconnects <= 0:
            raise ValueError("max_ws_disconnects must be positive")
        if stale_data_threshold_seconds < 0:
            raise ValueError("stale_data_threshold_seconds must be >= 0")

        self.max_api_failures = max_api_failures
        self.max_ws_disconnects = max_ws_disconnects
        self.stale_data_threshold_seconds = stale_data_threshold_seconds

        self._consecutive_api_failures = 0
        self._ws_disconnects = 0
        self._api_tripped = False
        self._ws_tripped = False

    # ------------------------------------------------------------------
    # API channel
    # ------------------------------------------------------------------

    def record_api_failure(self) -> bool:
        """Record one API failure; returns True if this trip the breaker."""
        self._consecutive_api_failures += 1
        if self._consecutive_api_failures >= self.max_api_failures:
            self._api_tripped = True
        return self._api_tripped

    def record_api_success(self) -> None:
        """One observed success proves the channel works again: clears the
        consecutive-failure counter and un-trips the breaker."""
        self._consecutive_api_failures = 0
        self._api_tripped = False

    @property
    def api_tripped(self) -> bool:
        return self._api_tripped

    @property
    def api_healthy(self) -> bool:
        return not self._api_tripped

    # ------------------------------------------------------------------
    # WebSocket channel
    # ------------------------------------------------------------------

    def record_ws_disconnect(self) -> bool:
        """Record one WS disconnect; returns True if this trip the breaker."""
        self._ws_disconnects += 1
        if self._ws_disconnects >= self.max_ws_disconnects:
            self._ws_tripped = True
        return self._ws_tripped

    def record_ws_connected(self) -> None:
        """A successful (re)connect proves the channel works again: clears the
        disconnect counter and un-trips the breaker."""
        self._ws_disconnects = 0
        self._ws_tripped = False

    @property
    def ws_tripped(self) -> bool:
        return self._ws_tripped

    @property
    def websocket_healthy(self) -> bool:
        return not self._ws_tripped

    # ------------------------------------------------------------------
    # Data staleness
    # ------------------------------------------------------------------

    def is_data_stale(self, last_seen: datetime, now: datetime | None = None) -> bool:
        """True when the observation is older than the configured threshold.

        Naive timestamps are assumed UTC (see polysignal.utils.time).
        """
        seen = ensure_utc(last_seen)
        reference = ensure_utc(now) if now is not None else utc_now()
        assert reference is not None
        if seen is None:
            return True
        age = (reference - seen).total_seconds()
        return age > self.stale_data_threshold_seconds

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Manual operator recovery: clears counters and tripped flags."""
        self._consecutive_api_failures = 0
        self._ws_disconnects = 0
        self._api_tripped = False
        self._ws_tripped = False
