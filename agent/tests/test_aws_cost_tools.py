"""T019 — AwsCostTools: correct CE params, read-only shape, graceful degradation."""

import json

from cost_analyst.tools.aws_cost_tools import AwsCostTools


class _FakeCE:
    def __init__(self):
        self.calls = []

    def get_cost_and_usage(self, **kwargs):
        self.calls.append(("get_cost_and_usage", kwargs))
        return {"ResultsByTime": [{"TimePeriod": {"Start": "2026-03-01"}, "Total": {}}]}


class _FakeEC2:
    def describe_volumes(self):
        return {
            "Volumes": [
                {"VolumeId": "vol-attached", "Size": 100, "VolumeType": "gp2",
                 "State": "in-use", "Attachments": [{"InstanceId": "i-1"}]},
                {"VolumeId": "vol-orphan", "Size": 50, "VolumeType": "gp2",
                 "State": "available", "Attachments": []},
            ]
        }


def test_get_cost_and_usage_builds_correct_params(monkeypatch):
    fake = _FakeCE()
    tools = AwsCostTools()
    monkeypatch.setattr(tools, "_client", lambda service, region=None: fake)

    out = json.loads(
        tools.get_cost_and_usage(start="2026-03-01", end="2026-06-01", group_by="SERVICE")
    )
    assert isinstance(out, list) and out  # ResultsByTime returned
    _, kwargs = fake.calls[0]
    assert kwargs["TimePeriod"] == {"Start": "2026-03-01", "End": "2026-06-01"}
    assert kwargs["Granularity"] == "MONTHLY"
    assert kwargs["Metrics"] == ["UnblendedCost"]
    assert kwargs["GroupBy"] == [{"Type": "DIMENSION", "Key": "SERVICE"}]


def test_list_ebs_volumes_flags_unattached(monkeypatch):
    tools = AwsCostTools()
    monkeypatch.setattr(tools, "_client", lambda service, region=None: _FakeEC2())
    vols = {v["VolumeId"]: v for v in json.loads(tools.list_ebs_volumes())}
    assert vols["vol-orphan"]["Unattached"] is True
    assert vols["vol-attached"]["Unattached"] is False


def test_methods_degrade_gracefully_without_credentials(monkeypatch):
    tools = AwsCostTools()

    def _boom(*_a, **_k):
        raise RuntimeError("no credentials")

    monkeypatch.setattr(tools, "_client", _boom)
    out = json.loads(tools.get_cost_and_usage(start="2026-03-01", end="2026-06-01"))
    assert "error" in out  # returns an error payload, does not raise


def test_no_mutating_methods_registered():
    tools = AwsCostTools()
    for name in tools.functions:
        assert name.split("_")[0] in {"get", "list"}, f"unexpected verb: {name}"
