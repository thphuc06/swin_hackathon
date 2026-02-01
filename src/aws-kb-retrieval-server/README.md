# AWS Knowledge Base Retrieval MCP Server

Custom MCP server for retrieving context from Amazon Bedrock Knowledge Bases.
Used by the AgentCore Gateway in this repo.

## Features

- **RAG retrieval** from Knowledge Bases for Bedrock
- **JSON-RPC** endpoint for Gateway integration
- **SSE** transport for MCP clients

## Tool

- **retrieve_from_aws_kb**
  - Inputs:
    - `query` (string): search query
    - `knowledgeBaseId` (string): Knowledge Base ID
    - `n` (number, optional): number of results (default: 3)

## Endpoints

- `POST /mcp` JSON-RPC (recommended for Gateway)
- `GET /mcp` health text
- `GET /mcp/sse` (or `/sse`) SSE transport
- `POST /mcp/message` (or `/message`) SSE message channel

## Configuration

Environment variables:

- `AWS_REGION` (required)
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (optional, for static creds)
- `PORT` (optional, default: 3000)

If static creds are not set, the AWS SDK uses the default credential chain.

## Run locally

```bash
cd src/aws-kb-retrieval-server
npm install
npm run build
node dist/index.js
```

Example JSON-RPC test:

```bash
curl -s http://localhost:3000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"tools-1","method":"tools/list"}'
```

## Docker

Build from repo root:

```bash
docker build -t mcp/aws-kb-retrieval -f src/aws-kb-retrieval-server/Dockerfile .
```

Run:

```bash
docker run -p 3000:3000 \
  -e AWS_REGION=us-east-1 \
  -e AWS_ACCESS_KEY_ID=... \
  -e AWS_SECRET_ACCESS_KEY=... \
  mcp/aws-kb-retrieval
```

## AgentCore Gateway notes

- Configure the Gateway target URL to `/mcp`.
- Gateway tool names can be prefixed (for example: `target-xyz___retrieve_from_aws_kb`).
- The agent can auto-discover tool names, or set `AGENTCORE_GATEWAY_TOOL_NAME`.

## License

MIT
