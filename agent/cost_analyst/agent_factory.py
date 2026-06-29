"""Assemble the agno Agent from resolved config + capabilities.

`build_tools` builds the read-only tool list conditionally (the canonical agno
gating pattern — disabled capabilities are never registered). `build_agent` wraps
it into an `Agent` constrained to the `CostReport` output schema.
"""

from __future__ import annotations

import logging

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.csv_toolkit import CsvTools

from .config import AppConfig, resolve_capabilities
from .models import CostReport
from .persona import Capabilities, build_instructions
from .tools import AwsCostTools, KubernetesReadTools, PrometheusTools

logger = logging.getLogger(__name__)


def build_tools(config: AppConfig, capabilities: Capabilities) -> list:
    """Build the read-only tool list for the active capabilities.

    Always: CsvTools (read + DuckDB SQL query over the CSV). Conditionally:
    AwsCostTools / KubernetesReadTools / PrometheusTools. A disabled capability
    contributes no tools at all.

    PandasTools is intentionally NOT registered: its `create_pandas_dataframe` /
    `run_dataframe_operation` functions expose a `Dict[str, Any]` parameter, which
    agno renders with JSON-Schema `propertyNames` — a construct the OpenAI
    function-calling API rejects (`invalid_function_parameters`). CsvTools'
    `query_csv_file` (DuckDB SQL) covers aggregation/analysis read-only.
    """
    tools: list = [CsvTools(csvs=[config.csv_path])]

    if capabilities.aws_live:
        tools.append(AwsCostTools())
    if capabilities.kubernetes:
        tools.append(KubernetesReadTools(kube_config_path=config.kube_config_path))
    if capabilities.prometheus:
        tools.append(
            PrometheusTools(
                base_url=config.prometheus_path,
                metrics=config.prometheus_metrics or [],
                default_lookback_days=config.prometheus_lookback_days,
            )
        )

    logger.info("Registered tools: %s", [type(t).__name__ for t in tools])
    return tools


def build_agent(
    config: AppConfig, capabilities: Capabilities | None = None
) -> tuple[Agent, Capabilities]:
    """Build the Cost Analyst agno Agent. Does not require OPENAI_API_KEY at build
    time (the entry point checks it), so this is unit-testable."""
    if capabilities is None:
        capabilities = resolve_capabilities(config)

    model = OpenAIChat(id=config.model)
    tools = build_tools(config, capabilities)
    instructions = build_instructions(capabilities)

    agent = Agent(
        name="Cost Analyst",
        model=model,
        tools=tools,
        instructions=instructions,
        markdown=True,
        output_schema=CostReport,
        # JSON mode (not OpenAI strict structured outputs). The CostReport schema
        # uses constructs OpenAI's strict `response_format` validator rejects —
        # enum fields with a default render as a `$ref` carrying a sibling
        # `default` ("$ref cannot have keywords {'default'}"), plus `min_length` /
        # `ge` constraints. In JSON mode agno injects the schema into the prompt
        # and parses the reply via `CostReport.model_validate_json`, so every
        # Pydantic validator (evidence-required, needs_data) still runs.
        use_json_mode=True,
        debug_mode=config.debug,
    )
    return agent, capabilities
