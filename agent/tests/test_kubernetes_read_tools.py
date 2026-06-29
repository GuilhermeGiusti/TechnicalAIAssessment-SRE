"""T023 — KubernetesReadTools: read-only shape, resource-gap detection."""

import json
import types

from cost_analyst.tools.kubernetes_read_tools import KubernetesReadTools


def _container(name, requests=None, limits=None):
    res = types.SimpleNamespace(requests=requests, limits=limits)
    return types.SimpleNamespace(name=name, resources=res)


def _pod(namespace, name, containers, phase="Running"):
    meta = types.SimpleNamespace(namespace=namespace, name=name)
    spec = types.SimpleNamespace(containers=containers)
    status = types.SimpleNamespace(phase=phase)
    return types.SimpleNamespace(metadata=meta, spec=spec, status=status)


class _FakeCore:
    def __init__(self, pods):
        self._pods = pods

    def list_pod_for_all_namespaces(self):
        return types.SimpleNamespace(items=self._pods)

    def list_namespaced_pod(self, namespace):
        return types.SimpleNamespace(
            items=[p for p in self._pods if p.metadata.namespace == namespace]
        )


def test_get_workload_resources_flags_missing_limits(monkeypatch):
    pods = [
        _pod("default", "good", [_container("c", requests={"cpu": "100m"}, limits={"cpu": "200m"})]),
        _pod("default", "bad", [_container("c", requests=None, limits=None)]),
    ]
    tools = KubernetesReadTools(kube_config_path="/dummy")
    monkeypatch.setattr(tools, "_core", lambda: _FakeCore(pods))

    gaps = json.loads(tools.get_workload_resources())["workloads_with_resource_gaps"]
    flagged = {g["pod"] for g in gaps}
    assert "bad" in flagged and "good" not in flagged


def test_list_pods_returns_structured_data(monkeypatch):
    pods = [_pod("ns1", "p1", [_container("c", requests={"cpu": "100m"})])]
    tools = KubernetesReadTools(kube_config_path="/dummy")
    monkeypatch.setattr(tools, "_core", lambda: _FakeCore(pods))
    out = json.loads(tools.list_pods())
    assert out[0]["name"] == "p1" and out[0]["namespace"] == "ns1"


def test_only_read_verbs_registered():
    tools = KubernetesReadTools(kube_config_path="/dummy")
    for name in tools.functions:
        assert name.split("_")[0] in {"list", "read", "get"}, f"unexpected verb: {name}"
