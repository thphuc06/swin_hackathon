#!/usr/bin/env node
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import { createServer } from "node:http";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  Tool,
} from "@modelcontextprotocol/sdk/types.js";
import {
  BedrockAgentRuntimeClient,
  RetrieveCommand,
  RetrieveCommandInput,
} from "@aws-sdk/client-bedrock-agent-runtime";

// AWS client initialization
const hasStaticCreds =
  Boolean(process.env.AWS_ACCESS_KEY_ID) &&
  Boolean(process.env.AWS_SECRET_ACCESS_KEY);

const bedrockClient = new BedrockAgentRuntimeClient({
  region: process.env.AWS_REGION,
  ...(hasStaticCreds
    ? {
        credentials: {
          accessKeyId: process.env.AWS_ACCESS_KEY_ID!,
          secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY!,
        },
      }
    : {}),
});

interface RAGSource {
  id: string;
  fileName: string;
  snippet: string;
  score: number;
}

async function retrieveContext(
  query: string,
  knowledgeBaseId: string,
  n: number = 3
): Promise<{
  context: string;
  isRagWorking: boolean;
  ragSources: RAGSource[];
}> {
  try {
    if (!knowledgeBaseId) {
      console.error("knowledgeBaseId is not provided");
      return {
        context: "",
        isRagWorking: false,
        ragSources: [],
      };
    }

    const input: RetrieveCommandInput = {
      knowledgeBaseId: knowledgeBaseId,
      retrievalQuery: { text: query },
      retrievalConfiguration: {
        vectorSearchConfiguration: { numberOfResults: n },
      },
    };

    const command = new RetrieveCommand(input);
    const response = await bedrockClient.send(command);
    const rawResults = response?.retrievalResults || [];
    const ragSources: RAGSource[] = rawResults
      .filter((res) => res?.content?.text)
      .map((result, index) => {
        const uri = result?.location?.s3Location?.uri || "";
        const fileName = uri.split("/").pop() || `Source-${index}.txt`;
        return {
          id: (result.metadata?.["x-amz-bedrock-kb-chunk-id"] as string) || `chunk-${index}`,
          fileName: fileName.replace(/_/g, " ").replace(".txt", ""),
          snippet: result.content?.text || "",
          score: (result.score as number) || 0,
        };
      })
      .slice(0, 3);

    const context = rawResults
      .filter((res): res is { content: { text: string } } => res?.content?.text !== undefined)
      .map(res => res.content.text)
      .join("\n\n");

    return {
      context,
      isRagWorking: true,
      ragSources,
    };
  } catch (error) {
    console.error("RAG Error:", error);
    return { context: "", isRagWorking: false, ragSources: [] };
  }
}

// Define the retrieval tool
const RETRIEVAL_TOOL: Tool = {
  name: "retrieve_from_aws_kb",
  description: "Performs retrieval from the AWS Knowledge Base using the provided query and Knowledge Base ID.",
  inputSchema: {
    type: "object",
    properties: {
      query: { type: "string", description: "The query to perform retrieval on" },
      knowledgeBaseId: { type: "string", description: "The ID of the AWS Knowledge Base" },
      n: { type: "number", default: 3, description: "Number of results to retrieve" },
    },
    required: ["query", "knowledgeBaseId"],
  },
};

// Server setup
const server = new Server(
  {
    name: "aws-kb-retrieval-server",
    version: "0.2.0",
  },
  {
    capabilities: {
      tools: {},
    },
  },
);

// Request handlers
server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [RETRIEVAL_TOOL],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  if (name === "retrieve_from_aws_kb") {
    const { query, knowledgeBaseId, n = 3 } = args as Record<string, any>;
    try {
      const result = await retrieveContext(query, knowledgeBaseId, n);
      if (result.isRagWorking) {
        return {
          content: [
            { type: "text", text: `Context: ${result.context}` },
            { type: "text", text: `RAG Sources: ${JSON.stringify(result.ragSources)}` },
          ],
        };
      } else {
        return {
          content: [{ type: "text", text: "Retrieval failed or returned no results." }],
        };
      }
    } catch (error) {
      return {
        content: [{ type: "text", text: `Error occurred: ${error}` }],
      };
    }
  } else {
    return {
      content: [{ type: "text", text: `Unknown tool: ${name}` }],
      isError: true,
    };
  }
});

// Server startup (SSE over HTTP)
const transports = new Map<string, SSEServerTransport>();

const httpServer = createServer(async (req, res) => {
  try {
    if (!req.url) {
      res.writeHead(400).end("Missing URL");
      return;
    }

    const url = new URL(req.url, `http://${req.headers.host}`);

    const ssePaths = new Set(["/sse", "/mcp", "/mcp/sse"]);
    const messagePaths = new Set(["/message", "/mcp/message"]);

    if (req.method === "GET" && ssePaths.has(url.pathname)) {
      const messagePath =
        url.pathname.startsWith("/mcp") ? "/mcp/message" : "/message";
      const transport = new SSEServerTransport(messagePath, res);
      transports.set(transport.sessionId, transport);
      transport.onclose = () => transports.delete(transport.sessionId);
      await server.connect(transport);
      return;
    }

    if (req.method === "POST" && messagePaths.has(url.pathname)) {
      const sessionId = url.searchParams.get("sessionId");
      if (!sessionId || !transports.has(sessionId)) {
        res.writeHead(400).end("Invalid or missing sessionId");
        return;
      }
      const transport = transports.get(sessionId)!;
      await transport.handlePostMessage(req, res);
      return;
    }

    res.writeHead(404).end("Not found");
  } catch (error) {
    console.error("HTTP server error:", error);
    res.writeHead(500).end("Internal server error");
  }
});

const port = Number.parseInt(process.env.PORT || "3000", 10);
httpServer.listen(port, () => {
  console.error(`AWS KB Retrieval Server listening on :${port} (SSE)`);
});
