"""T011 — config & gating: required --CSV_PATH, CLI>env precedence, clamp, gating."""

import pytest

from cost_analyst import config as cfg


def test_missing_csv_path_raises_usage_error(monkeypatch):
    monkeypatch.delenv("CSV_PATH", raising=False)
    with pytest.raises(cfg.UsageError):
        cfg.load_config([])


def test_nonexistent_csv_raises_usage_error(monkeypatch):
    monkeypatch.delenv("CSV_PATH", raising=False)
    with pytest.raises(cfg.UsageError):
        cfg.load_config(["--CSV_PATH", "/no/such/file.csv"])


def test_cli_flag_overrides_env(monkeypatch, example_csv):
    monkeypatch.setenv("CSV_PATH", "/nonexistent-from-env.csv")
    config = cfg.load_config(["--CSV_PATH", example_csv])
    assert config.csv_path == example_csv  # CLI wins over env


def test_env_used_when_no_cli_flag(monkeypatch, example_csv):
    monkeypatch.setenv("CSV_PATH", example_csv)
    config = cfg.load_config([])
    assert config.csv_path == example_csv


def test_model_default_and_override(example_csv):
    assert cfg.load_config(["--CSV_PATH", example_csv]).model == cfg.DEFAULT_MODEL
    overridden = cfg.load_config(["--CSV_PATH", example_csv, "--MODEL", "gpt-4o-mini"])
    assert overridden.model == "gpt-4o-mini"


def test_prometheus_lookback_is_clamped_to_31(example_csv):
    config = cfg.load_config(["--CSV_PATH", example_csv, "--PROMETHEUS_LOOKBACK_DAYS", "90"])
    assert config.prometheus_lookback_days == cfg.MAX_PROMETHEUS_LOOKBACK_DAYS


def test_metrics_parsed_to_list(example_csv):
    config = cfg.load_config(
        ["--CSV_PATH", example_csv, "--PROMETHEUS_METRICS", "a, b ,c"]
    )
    assert config.prometheus_metrics == ["a", "b", "c"]


def test_gating_all_off_by_default(monkeypatch, example_csv):
    monkeypatch.setattr(cfg, "aws_credentials_available", lambda: False)
    config = cfg.load_config(["--CSV_PATH", example_csv])
    caps = cfg.resolve_capabilities(config)
    assert caps.csv is True
    assert caps.aws_live is False
    assert caps.kubernetes is False
    assert caps.prometheus is False


def test_gating_enables_capabilities(monkeypatch, example_csv):
    monkeypatch.setattr(cfg, "aws_credentials_available", lambda: True)
    monkeypatch.setattr(cfg, "kube_reachable", lambda *_: True)
    monkeypatch.setattr(cfg, "prometheus_reachable", lambda *_: True)
    config = cfg.load_config(
        [
            "--CSV_PATH", example_csv,
            "--KUBE_CONFIG_PATH", example_csv,  # any existing file
            "--PROMETHEUS_PATH", "http://localhost:9090",
            "--PROMETHEUS_METRICS", "up",
        ]
    )
    caps = cfg.resolve_capabilities(config)
    assert (caps.aws_live, caps.kubernetes, caps.prometheus) == (True, True, True)


def test_prometheus_needs_both_path_and_metrics(monkeypatch, example_csv):
    monkeypatch.setattr(cfg, "aws_credentials_available", lambda: False)
    monkeypatch.setattr(cfg, "prometheus_reachable", lambda *_: True)
    config = cfg.load_config(
        ["--CSV_PATH", example_csv, "--PROMETHEUS_PATH", "http://localhost:9090"]
    )  # no metrics
    assert cfg.resolve_capabilities(config).prometheus is False
