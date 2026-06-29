"""PrometheusTools — read-only Prometheus access for the Cost Analyst Agent.

Wraps the HTTP `GET /api/v1/query_range` endpoint. Two hard constraints enforced
in code (defense in depth, so a prompt cannot bypass them):
  - only metrics in the configured allow-list may be queried;
  - the lookback window is clamped to at most ``max_lookback_days`` (31).

READ-ONLY: HTTP GET against the query API only; no admin/TSDB endpoints.
"""

from __future__ import annotations

import json
import time

from agno.tools import Toolkit

MAX_LOOKBACK_DAYS = 31


class PrometheusTools(Toolkit):
    def __init__(
        self,
        base_url: str,
        metrics: list[str],
        max_lookback_days: int = MAX_LOOKBACK_DAYS,
        default_lookback_days: int = 7,
        **kwargs,
    ):
        self._base_url = base_url.rstrip("/")
        self._metrics = list(metrics or [])
        self._max_lookback_days = max(1, min(max_lookback_days, MAX_LOOKBACK_DAYS))
        self._default_lookback_days = max(1, min(default_lookback_days, self._max_lookback_days))
        super().__init__(
            name="prometheus_tools",
            tools=[self.list_configured_metrics, self.query_range],
            **kwargs,
        )

    @staticmethod
    def _err(message: str) -> str:
        return json.dumps({"error": message})

    def list_configured_metrics(self) -> str:
        """Return the predefined metric allow-list this agent may query."""
        return json.dumps({"metrics": self._metrics, "max_lookback_days": self._max_lookback_days})

    def _clamp_days(self, lookback_days) -> int:
        try:
            days = int(lookback_days)
        except (TypeError, ValueError):
            days = self._default_lookback_days
        return max(1, min(days, self._max_lookback_days))

    def query_range(self, metric: str, lookback_days: int | None = None, step: str = "1h") -> str:
        """Query a configured metric over a bounded time window (read-only).

        Args:
            metric: must be one of the configured metrics.
            lookback_days: window size; clamped to <= 31 days regardless of value.
            step: resolution, e.g. "1h" or "5m".
        """
        if metric not in self._metrics:
            return self._err(
                f"Metric '{metric}' is not in the configured allow-list: {self._metrics}"
            )
        days = self._clamp_days(self._default_lookback_days if lookback_days is None else lookback_days)
        try:
            import requests

            end = int(time.time())
            start = end - days * 86400
            resp = requests.get(
                f"{self._base_url}/api/v1/query_range",
                params={"query": metric, "start": start, "end": end, "step": step},
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
            return json.dumps(
                {
                    "metric": metric,
                    "lookback_days": days,
                    "step": step,
                    "result": payload.get("data", {}).get("result", []),
                },
                default=str,
            )
        except Exception as exc:
            return self._err(f"query_range failed: {exc}")
