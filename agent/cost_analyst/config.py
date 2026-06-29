"""Configuration & capability gating for the Cost Analyst Agent.

Precedence for every non-secret parameter: **CLI flag > environment variable >
default** (FR-023). Secrets (OPENAI_API_KEY, AWS credentials) are NEVER CLI flags
— they come from the environment / a `.env` file (FR-024), loaded here via
python-dotenv.

A capability is "active" only when its configuration resolves AND its backend is
reachable; otherwise its tools are never registered (FR-010/012/020).
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

from .persona import Capabilities

# Hard cap on the Prometheus lookback window to conserve tokens/queries (FR-014).
MAX_PROMETHEUS_LOOKBACK_DAYS = 31
DEFAULT_MODEL = "gpt-4o"
DEFAULT_PROMETHEUS_LOOKBACK_DAYS = 7


class UsageError(Exception):
    """Invalid invocation — maps to exit code 2."""


class MissingApiKeyError(Exception):
    """OPENAI_API_KEY not available — maps to exit code 3."""


@dataclass
class AppConfig:
    csv_path: str
    model: str = DEFAULT_MODEL
    period: str | None = None
    kube_config_path: str | None = None
    prometheus_path: str | None = None
    prometheus_metrics: list[str] | None = None
    prometheus_lookback_days: int = DEFAULT_PROMETHEUS_LOOKBACK_DAYS
    output: str | None = None
    debug: bool = False


def _load_dotenv() -> None:
    """Load `.env` into the environment. No-op if python-dotenv is absent."""
    try:
        from dotenv import load_dotenv
    except Exception:  # pragma: no cover - dotenv is a declared dependency
        return
    load_dotenv()


def _resolve(cli_value, env_name: str, default=None):
    """CLI flag > environment variable > default."""
    if cli_value is not None:
        return cli_value
    env_value = os.environ.get(env_name)
    if env_value is not None and env_value != "":
        return env_value
    return default


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent.py",
        description="Read-only AWS cost analysis agent (agno + OpenAI). "
        "Secrets come from a .env file; non-secret options are flags below.",
    )
    p.add_argument("--CSV_PATH", dest="CSV_PATH", help="Path to the AWS cost export CSV (required).")
    p.add_argument("--MODEL", dest="MODEL", help=f"OpenAI model id (default: {DEFAULT_MODEL}).")
    p.add_argument("--PERIOD", dest="PERIOD", help="Analysis window, e.g. 2026-03:2026-05.")
    p.add_argument("--KUBE_CONFIG_PATH", dest="KUBE_CONFIG_PATH", help="Path to kubeconfig (enables Kubernetes capability).")
    p.add_argument("--PROMETHEUS_PATH", dest="PROMETHEUS_PATH", help="Prometheus endpoint URL (enables Prometheus capability with metrics).")
    p.add_argument("--PROMETHEUS_METRICS", dest="PROMETHEUS_METRICS", help="Comma-separated metric list (enables Prometheus capability with endpoint).")
    p.add_argument("--PROMETHEUS_LOOKBACK_DAYS", dest="PROMETHEUS_LOOKBACK_DAYS", help=f"Lookback days (hard-capped at {MAX_PROMETHEUS_LOOKBACK_DAYS}).")
    p.add_argument("--OUTPUT", dest="OUTPUT", help="Write the report to this file instead of stdout.")
    p.add_argument("--DEBUG", dest="DEBUG", action="store_true", default=None, help="Verbose logging.")
    return p


def _parse_metrics(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    metrics = [m.strip() for m in raw.split(",") if m.strip()]
    return metrics or None


def _resolve_bool(cli_flag: bool | None, env_name: str) -> bool:
    """True if the CLI flag was passed or the env var is truthy."""
    if cli_flag:
        return True
    return os.environ.get(env_name, "").strip().lower() in ("1", "true", "yes", "on")


def _clamp_lookback(raw) -> int:
    try:
        days = int(raw)
    except (TypeError, ValueError):
        days = DEFAULT_PROMETHEUS_LOOKBACK_DAYS
    return max(1, min(days, MAX_PROMETHEUS_LOOKBACK_DAYS))


def load_config(argv: list[str] | None = None) -> AppConfig:
    """Parse args + environment into an AppConfig. Raises UsageError on misuse."""
    _load_dotenv()
    args = build_parser().parse_args(argv)

    csv_path = _resolve(args.CSV_PATH, "CSV_PATH")
    if not csv_path:
        raise UsageError("--CSV_PATH is required (or set CSV_PATH in the environment).")
    if not os.path.isfile(csv_path):
        raise UsageError(f"CSV file not found: {csv_path}")

    return AppConfig(
        csv_path=csv_path,
        model=_resolve(args.MODEL, "MODEL", DEFAULT_MODEL),
        period=_resolve(args.PERIOD, "PERIOD"),
        kube_config_path=_resolve(args.KUBE_CONFIG_PATH, "KUBE_CONFIG_PATH"),
        prometheus_path=_resolve(args.PROMETHEUS_PATH, "PROMETHEUS_PATH"),
        prometheus_metrics=_parse_metrics(_resolve(args.PROMETHEUS_METRICS, "PROMETHEUS_METRICS")),
        prometheus_lookback_days=_clamp_lookback(
            _resolve(args.PROMETHEUS_LOOKBACK_DAYS, "PROMETHEUS_LOOKBACK_DAYS", DEFAULT_PROMETHEUS_LOOKBACK_DAYS)
        ),
        output=_resolve(args.OUTPUT, "OUTPUT"),
        debug=_resolve_bool(args.DEBUG, "DEBUG"),
    )


# --------------------------------------------------------------------------- #
# Gating / reachability checks. Each is module-level so tests can monkeypatch.
# --------------------------------------------------------------------------- #

def aws_credentials_available() -> bool:
    """True if the standard boto3 credential chain resolves any credentials."""
    try:
        import boto3  # lazy: avoids a hard dependency at import time

        creds = boto3.Session().get_credentials()
        return creds is not None
    except Exception:
        return False


def kube_reachable(kube_config_path: str | None, timeout_seconds: int = 5) -> bool:
    """True if the kubeconfig path exists and the cluster answers a read call."""
    if not kube_config_path or not os.path.isfile(kube_config_path):
        return False
    try:
        from kubernetes import client, config

        config.load_kube_config(config_file=kube_config_path)
        client.VersionApi().get_code(_request_timeout=timeout_seconds)
        return True
    except Exception:
        return False


def prometheus_reachable(base_url: str | None, timeout_seconds: int = 5) -> bool:
    """True if the Prometheus endpoint answers a trivial query."""
    if not base_url:
        return False
    try:
        import requests

        resp = requests.get(
            f"{base_url.rstrip('/')}/api/v1/query",
            params={"query": "1"},
            timeout=timeout_seconds,
        )
        return resp.ok
    except Exception:
        return False


def resolve_capabilities(config: AppConfig, check_reachability: bool = True) -> Capabilities:
    """Decide which capabilities are active for this run (deterministic given inputs)."""
    aws = aws_credentials_available()

    kube = bool(config.kube_config_path)
    if kube and check_reachability:
        kube = kube_reachable(config.kube_config_path)

    prom = bool(config.prometheus_path and config.prometheus_metrics)
    if prom and check_reachability:
        prom = prometheus_reachable(config.prometheus_path)

    return Capabilities(csv=True, aws_live=aws, kubernetes=kube, prometheus=prom)


def require_openai_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise MissingApiKeyError(
            "OPENAI_API_KEY is not set. Add it to your .env file or environment."
        )
    return key
