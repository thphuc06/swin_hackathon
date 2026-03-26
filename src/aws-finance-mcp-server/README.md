# Standalone Finance MCP Server

Legacy compatibility/reference only.

This folder is **not** part of the active production architecture. The current production path uses:

`frontend -> backend -> orchestrator -> gateway -> specialist-agent-mcp -> in-process planner`

## Status

- kept for historical reference and compatibility experiments
- not part of the default AWS deploy flow
- should not be added to the active Gateway target set for the current specialist-first architecture

## If You Open This Folder On Purpose

Use it only when you are explicitly working on:

- legacy comparison
- migration/reference analysis
- standalone MCP experiments outside the main production path

For current deploys and runtime behavior, use:

- [README.md](../../README.md)
- [docs/repo-ownership-map.md](../../docs/repo-ownership-map.md)
- [ops/aws/README.md](../../ops/aws/README.md)
- `src/aws-specialist-agent-mcp-server/`
