"""T027 — PrometheusTools: 31-day clamp, metric allow-list, GET-only."""

import json

from cost_analyst.tools.prometheus_tools import MAX_LOOKBACK_DAYS, PrometheusTools


class _FakeResp:
    def __init__(self):
        self.captured = None

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": {"result": [{"metric": {"__name__": "up"}, "values": []}]}}


def _patch_requests(monkeypatch, capture):
    import requests

    resp = _FakeResp()

    def fake_get(url, params=None, timeout=None):
        capture["url"] = url
        capture["params"] = params
        return resp

    monkeypatch.setattr(requests, "get", fake_get)


def test_lookback_is_clamped_to_31_days(monkeypatch):
    capture = {}
    _patch_requests(monkeypatch, capture)
    tools = PrometheusTools(base_url="http://prom:9090", metrics=["up"])

    tools.query_range(metric="up", lookback_days=90, step="1h")

    span_days = (capture["params"]["end"] - capture["params"]["start"]) / 86400
    assert span_days <= MAX_LOOKBACK_DAYS
    assert capture["url"].endswith("/api/v1/query_range")


def test_unconfigured_metric_is_rejected_without_querying(monkeypatch):
    capture = {}
    _patch_requests(monkeypatch, capture)
    tools = PrometheusTools(base_url="http://prom:9090", metrics=["up"])

    out = json.loads(tools.query_range(metric="node_cpu_seconds_total", lookback_days=7))
    assert "error" in out
    assert capture == {}  # no HTTP call was made


def test_list_configured_metrics_reports_allow_list():
    tools = PrometheusTools(base_url="http://prom:9090", metrics=["up", "node_load1"])
    out = json.loads(tools.list_configured_metrics())
    assert out["metrics"] == ["up", "node_load1"]
    assert out["max_lookback_days"] == MAX_LOOKBACK_DAYS
