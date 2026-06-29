#!/usr/bin/env python3
"""Cost Analyst Agent — CLI entry point.

    python agent.py --CSV_PATH ./examples/example_costs.csv [options]

Secrets (OPENAI_API_KEY, AWS credentials) come from a `.env` file / the
environment — never from CLI flags. All non-secret parameters are flags
(see `--help`). The agent is strictly read-only.

Exit codes: 0 ok · 2 usage (missing/invalid --CSV_PATH) · 3 missing OPENAI_API_KEY
· 1 unexpected runtime error.
"""

from __future__ import annotations

import logging
import sys

# The script's own directory (agent/) is on sys.path automatically, so the
# cost_analyst package imports whether invoked as `python agent.py` (from agent/)
# or `python agent/agent.py` (from the repo root).
from cost_analyst import config as cfg
from cost_analyst.agent_factory import build_agent
from cost_analyst.persona import Capabilities

logger = logging.getLogger("cost_analyst")


def build_prompt(config: cfg.AppConfig, capabilities: Capabilities) -> str:
    period = f" The analysis period is {config.period}." if config.period else ""
    return (
        f"Analyze the AWS cost CSV located at '{config.csv_path}'. Inspect its "
        "columns and rows, identify the largest cost drivers and the most likely "
        "sources of waste, and produce a prioritized CostReport whose every "
        f"recommendation cites concrete evidence.{period} Use the tools available "
        "to you. Set capabilities_used to exactly: "
        f"{', '.join(capabilities.active_sources())}."
    )


def main(argv: list[str] | None = None) -> int:
    # 1) Parse config (usage errors → exit 2).
    try:
        config = cfg.load_config(argv)
    except cfg.UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=logging.DEBUG if config.debug else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # 2) Require the model secret (→ exit 3).
    try:
        cfg.require_openai_key()
    except cfg.MissingApiKeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    # 3) Resolve capabilities, build the agent, run it.
    try:
        capabilities = cfg.resolve_capabilities(config)
        logger.info("Active capabilities: %s", capabilities.active_sources())

        agent, capabilities = build_agent(config, capabilities)
        result = agent.run(build_prompt(config, capabilities))

        report = getattr(result, "content", result)
        text = report.render_markdown() if hasattr(report, "render_markdown") else str(report)

        if config.output:
            with open(config.output, "w", encoding="utf-8") as fh:
                fh.write(text)
            logger.info("Report written to %s", config.output)
        else:
            print(text)
        return 0
    except Exception as exc:  # pragma: no cover - top-level safety net
        logger.exception("Cost analysis failed")
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
