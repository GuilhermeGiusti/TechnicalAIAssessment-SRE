"""AwsCostTools — read-only AWS access for the Cost Analyst Agent.

Wraps Cost Explorer (`get_cost_and_usage`, `get_cost_forecast`) and
describe/list calls for EC2/EBS/S3/RDS. boto3 reads credentials from the standard
chain (env vars from `.env`, shared config, or role). Cost Explorer is global, so
its client is pinned to us-east-1.

READ-ONLY: only get_*/describe_*/list_* calls are made. No mutating method exists.
"""

from __future__ import annotations

import json

from agno.tools import Toolkit


class AwsCostTools(Toolkit):
    def __init__(self, region: str = "us-east-1", **kwargs):
        self._region = region
        self._session = None
        super().__init__(
            name="aws_cost_tools",
            tools=[
                self.get_cost_and_usage,
                self.get_cost_forecast,
                self.list_ec2_instances,
                self.list_ebs_volumes,
                self.list_s3_buckets,
                self.list_rds_instances,
            ],
            **kwargs,
        )

    # -- internal ---------------------------------------------------------- #
    def _client(self, service: str, region: str | None = None):
        import boto3

        if self._session is None:
            self._session = boto3.Session()
        return self._session.client(service, region_name=region or self._region)

    @staticmethod
    def _ok(payload) -> str:
        return json.dumps(payload, default=str)

    @staticmethod
    def _err(message: str) -> str:
        return json.dumps({"error": message})

    # -- Cost Explorer (read-only) ---------------------------------------- #
    def get_cost_and_usage(
        self,
        start: str,
        end: str,
        granularity: str = "MONTHLY",
        metrics: str = "UnblendedCost",
        group_by: str = "SERVICE",
    ) -> str:
        """Get AWS cost & usage from Cost Explorer (read-only).

        Args:
            start: inclusive start date, YYYY-MM-DD.
            end: exclusive end date, YYYY-MM-DD.
            granularity: DAILY, MONTHLY, or HOURLY.
            metrics: comma-separated CE metrics, e.g. "UnblendedCost,UsageQuantity".
            group_by: a CE DIMENSION key (e.g. SERVICE, REGION) or "NONE".
        """
        try:
            ce = self._client("ce", region="us-east-1")
            params = {
                "TimePeriod": {"Start": start, "End": end},
                "Granularity": granularity,
                "Metrics": [m.strip() for m in metrics.split(",") if m.strip()],
            }
            if group_by and group_by.upper() != "NONE":
                params["GroupBy"] = [{"Type": "DIMENSION", "Key": group_by.upper()}]
            resp = ce.get_cost_and_usage(**params)
            return self._ok(resp.get("ResultsByTime", []))
        except Exception as exc:  # graceful degradation
            return self._err(f"get_cost_and_usage failed: {exc}")

    def get_cost_forecast(
        self,
        start: str,
        end: str,
        granularity: str = "MONTHLY",
        metric: str = "UNBLENDED_COST",
    ) -> str:
        """Forecast future AWS spend from Cost Explorer (read-only). Dates YYYY-MM-DD."""
        try:
            ce = self._client("ce", region="us-east-1")
            resp = ce.get_cost_forecast(
                TimePeriod={"Start": start, "End": end},
                Granularity=granularity,
                Metric=metric,
            )
            return self._ok(
                {
                    "Total": resp.get("Total"),
                    "ForecastResultsByTime": resp.get("ForecastResultsByTime", []),
                }
            )
        except Exception as exc:
            return self._err(f"get_cost_forecast failed: {exc}")

    # -- Resource inventory (read-only) ----------------------------------- #
    def list_ec2_instances(self, region: str | None = None) -> str:
        """List EC2 instances (id, type, state) to spot idle/over-provisioned ones."""
        try:
            ec2 = self._client("ec2", region=region)
            out = []
            for res in ec2.describe_instances().get("Reservations", []):
                for inst in res.get("Instances", []):
                    out.append(
                        {
                            "InstanceId": inst.get("InstanceId"),
                            "InstanceType": inst.get("InstanceType"),
                            "State": inst.get("State", {}).get("Name"),
                            "LaunchTime": inst.get("LaunchTime"),
                        }
                    )
            return self._ok(out)
        except Exception as exc:
            return self._err(f"list_ec2_instances failed: {exc}")

    def list_ebs_volumes(self, region: str | None = None) -> str:
        """List EBS volumes; flags unattached (available) volumes as waste candidates."""
        try:
            ec2 = self._client("ec2", region=region)
            out = []
            for vol in ec2.describe_volumes().get("Volumes", []):
                out.append(
                    {
                        "VolumeId": vol.get("VolumeId"),
                        "SizeGiB": vol.get("Size"),
                        "VolumeType": vol.get("VolumeType"),
                        "State": vol.get("State"),
                        "Unattached": len(vol.get("Attachments", [])) == 0,
                    }
                )
            return self._ok(out)
        except Exception as exc:
            return self._err(f"list_ebs_volumes failed: {exc}")

    def list_s3_buckets(self) -> str:
        """List S3 buckets (name, creation date) for storage-class/lifecycle review."""
        try:
            s3 = self._client("s3")
            buckets = s3.list_buckets().get("Buckets", [])
            return self._ok(
                [{"Name": b.get("Name"), "CreationDate": b.get("CreationDate")} for b in buckets]
            )
        except Exception as exc:
            return self._err(f"list_s3_buckets failed: {exc}")

    def list_rds_instances(self, region: str | None = None) -> str:
        """List RDS instances (id, class, engine, status) for rightsizing/RI review."""
        try:
            rds = self._client("rds", region=region)
            out = []
            for db in rds.describe_db_instances().get("DBInstances", []):
                out.append(
                    {
                        "DBInstanceIdentifier": db.get("DBInstanceIdentifier"),
                        "DBInstanceClass": db.get("DBInstanceClass"),
                        "Engine": db.get("Engine"),
                        "Status": db.get("DBInstanceStatus"),
                        "MultiAZ": db.get("MultiAZ"),
                    }
                )
            return self._ok(out)
        except Exception as exc:
            return self._err(f"list_rds_instances failed: {exc}")
