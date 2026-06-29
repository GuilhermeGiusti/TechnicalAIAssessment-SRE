"""KubernetesReadTools — read-only Kubernetes access for the Cost Analyst Agent.

Loads a kubeconfig from a path (lazily, on first use) and exposes read verbs only
(`list_*`, `read_*`). Intended to run against a read-only ServiceAccount/RBAC
(verbs: get/list/watch). Used to find missing/oversized resource requests/limits
and over-provisioning.

READ-ONLY: no create/patch/delete/replace calls exist.
"""

from __future__ import annotations

import json

from agno.tools import Toolkit


class KubernetesReadTools(Toolkit):
    def __init__(self, kube_config_path: str, **kwargs):
        self._kube_config_path = kube_config_path
        self._loaded = False
        super().__init__(
            name="kubernetes_read_tools",
            tools=[
                self.list_nodes,
                self.list_pods,
                self.list_deployments,
                self.get_workload_resources,
            ],
            **kwargs,
        )

    # -- internal ---------------------------------------------------------- #
    def _ensure_loaded(self) -> None:
        if not self._loaded:
            from kubernetes import config

            config.load_kube_config(config_file=self._kube_config_path)
            self._loaded = True

    def _core(self):
        from kubernetes import client

        self._ensure_loaded()
        return client.CoreV1Api()

    def _apps(self):
        from kubernetes import client

        self._ensure_loaded()
        return client.AppsV1Api()

    @staticmethod
    def _ok(payload) -> str:
        return json.dumps(payload, default=str)

    @staticmethod
    def _err(message: str) -> str:
        return json.dumps({"error": message})

    # -- reads ------------------------------------------------------------- #
    def list_nodes(self) -> str:
        """List cluster nodes with capacity/allocatable (for utilization context)."""
        try:
            nodes = self._core().list_node()
            out = []
            for n in nodes.items:
                out.append(
                    {
                        "name": n.metadata.name,
                        "capacity": n.status.capacity,
                        "allocatable": n.status.allocatable,
                    }
                )
            return self._ok(out)
        except Exception as exc:
            return self._err(f"list_nodes failed: {exc}")

    def list_pods(self, namespace: str | None = None) -> str:
        """List pods (optionally in one namespace) with their container resources."""
        try:
            core = self._core()
            pods = (
                core.list_namespaced_pod(namespace)
                if namespace
                else core.list_pod_for_all_namespaces()
            )
            out = []
            for p in pods.items:
                containers = []
                for c in p.spec.containers or []:
                    res = c.resources
                    containers.append(
                        {
                            "name": c.name,
                            "requests": (res.requests if res else None),
                            "limits": (res.limits if res else None),
                        }
                    )
                out.append(
                    {
                        "namespace": p.metadata.namespace,
                        "name": p.metadata.name,
                        "phase": p.status.phase if p.status else None,
                        "containers": containers,
                    }
                )
            return self._ok(out)
        except Exception as exc:
            return self._err(f"list_pods failed: {exc}")

    def list_deployments(self, namespace: str | None = None) -> str:
        """List deployments with replica counts and container resource requests/limits."""
        try:
            apps = self._apps()
            deps = (
                apps.list_namespaced_deployment(namespace)
                if namespace
                else apps.list_deployment_for_all_namespaces()
            )
            out = []
            for d in deps.items:
                containers = []
                for c in d.spec.template.spec.containers or []:
                    res = c.resources
                    containers.append(
                        {
                            "name": c.name,
                            "requests": (res.requests if res else None),
                            "limits": (res.limits if res else None),
                        }
                    )
                out.append(
                    {
                        "namespace": d.metadata.namespace,
                        "name": d.metadata.name,
                        "replicas": d.spec.replicas,
                        "containers": containers,
                    }
                )
            return self._ok(out)
        except Exception as exc:
            return self._err(f"list_deployments failed: {exc}")

    def get_workload_resources(self, namespace: str | None = None) -> str:
        """Summarize workloads with missing or absent resource requests/limits."""
        try:
            core = self._core()
            pods = (
                core.list_namespaced_pod(namespace)
                if namespace
                else core.list_pod_for_all_namespaces()
            )
            issues = []
            for p in pods.items:
                for c in p.spec.containers or []:
                    res = c.resources
                    missing_requests = not (res and res.requests)
                    missing_limits = not (res and res.limits)
                    if missing_requests or missing_limits:
                        issues.append(
                            {
                                "namespace": p.metadata.namespace,
                                "pod": p.metadata.name,
                                "container": c.name,
                                "missing_requests": missing_requests,
                                "missing_limits": missing_limits,
                            }
                        )
            return self._ok({"workloads_with_resource_gaps": issues})
        except Exception as exc:
            return self._err(f"get_workload_resources failed: {exc}")
