"""T028 — the read-only guarantee, asserted against the assembled tool set.

This is the safety backstop for Constitution Principle III + FR-015..018: the
agent must have no way to mutate any system.
"""

import re

from cost_analyst.agent_factory import build_tools
from cost_analyst.config import AppConfig
from cost_analyst.persona import Capabilities

# Verbs that would imply mutating an external system.
MUTATING = re.compile(
    r"(?i)(create|delete|modify|put|update|patch|replace|^run|exec|terminate|"
    r"stop|start|write|destroy|remove|attach|detach|scale|drain|cordon|apply)"
)

CUSTOM_TOOLKITS = {"AwsCostTools", "KubernetesReadTools", "PrometheusTools"}


def _all_caps_config(example_csv) -> AppConfig:
    return AppConfig(
        csv_path=example_csv,
        kube_config_path="/dummy/kubeconfig",
        prometheus_path="http://prom:9090",
        prometheus_metrics=["up"],
    )


def test_custom_toolkits_expose_no_mutating_functions(example_csv):
    caps = Capabilities(csv=True, aws_live=True, kubernetes=True, prometheus=True)
    tools = build_tools(_all_caps_config(example_csv), caps)

    custom = [t for t in tools if type(t).__name__ in CUSTOM_TOOLKITS]
    assert len(custom) == 3, "all three custom toolkits should be registered"

    for toolkit in custom:
        for fn_name in toolkit.functions:
            assert not MUTATING.search(fn_name), (
                f"{type(toolkit).__name__}.{fn_name} looks mutating"
            )


def test_shell_and_python_toolkits_are_never_registered(example_csv):
    caps = Capabilities(csv=True, aws_live=True, kubernetes=True, prometheus=True)
    names = {type(t).__name__ for t in build_tools(_all_caps_config(example_csv), caps)}
    assert "ShellTools" not in names
    assert "PythonTools" not in names


def test_csv_only_surface_is_minimal(example_csv):
    caps = Capabilities(csv=True)
    names = {type(t).__name__ for t in build_tools(AppConfig(csv_path=example_csv), caps)}
    assert names == {"CsvTools", "PandasTools"}
