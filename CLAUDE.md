# Project Rules

## Prompt Logging
Every time you receive a new instruction or prompt, append it to prompts.txt in the project root with a timestamp (ISO 8601) and a brief summary of what you did in response. Create the file if it doesn't exist. Keep this log updated throughout all sessions.

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan:
`specs/001-cost-analyst-agent/plan.md`

Active feature: **Cost Analyst Agent** (agno + OpenAI, read-only CLI). Spec,
research, data model, contracts, and quickstart live under
`specs/001-cost-analyst-agent/`. Build target is the `agent/` directory with
`agent.py` as the CLI entry point.
<!-- SPECKIT END -->
