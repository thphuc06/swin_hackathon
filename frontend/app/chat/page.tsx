"use client";

import AppShell from "@/components/AppShell";
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type ChatMessage = { role: "user" | "assistant"; text: string };

export default function ChatPage() {
  const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8010";
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [accessToken, setAccessToken] = useState("");
  const [meta, setMeta] = useState<{
    trace?: string;
    citations?: string;
    disclaimer?: string;
    tools?: string;
    executedTools?: string;
    responseMode?: string;
    responseFallback?: string;
    responseReasonCodes?: string;
    responseStatus?: string;
    responseJobId?: string;
    retryAfterSeconds?: string;
    runtimeSource?: string;
  }>({});

  useEffect(() => {
    const saved = window.localStorage.getItem("jars_access_token");
    if (saved) setAccessToken(saved);
  }, []);

  function handleTokenChange(value: string) {
    setAccessToken(value);
    if (value.trim()) {
      window.localStorage.setItem("jars_access_token", value.trim());
    } else {
      window.localStorage.removeItem("jars_access_token");
    }
  }

  async function handleSend() {
    if (!input.trim() || streaming) return;
    const userText = input.trim();
    setInput("");
    let assistantIndex = -1;
    setMeta({});
    setMessages((prev) => {
      const next: ChatMessage[] = [...prev, { role: "user", text: userText }, { role: "assistant", text: "" }];
      assistantIndex = next.length - 1;
      return next;
    });
    setStreaming(true);

    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const pollHeaders: Record<string, string> = {};
    if (accessToken.trim()) {
      headers.Authorization = `Bearer ${accessToken.trim()}`;
      pollHeaders.Authorization = `Bearer ${accessToken.trim()}`;
    }

    const response = await fetch(`${apiBase}/chat/stream`, {
      method: "POST",
      headers,
      body: JSON.stringify({ prompt: userText }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      setMessages((prev) => {
        const updated = [...prev];
        const idx = assistantIndex >= 0 ? assistantIndex : updated.findLastIndex((m) => m.role === "assistant");
        if (idx >= 0) {
          updated[idx] = {
            role: "assistant",
            text: `Error ${response.status}: ${errorText || response.statusText}`,
          };
        }
        return updated;
      });
      setStreaming(false);
      return;
    }

    if (!response.body) {
      setStreaming(false);
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let current = "";
    let responseStatusSnapshot = "";
    let pendingJobId = "";
    let pendingRetryAfterSeconds = 2;
    const handleSsePart = (part: string) => {
      const eventLines = part.split(/\r?\n/);
      const eventDataLines: string[] = [];
      for (const rawLine of eventLines) {
        if (rawLine.startsWith("data:")) {
          eventDataLines.push(rawLine.replace(/^data:\s?/, ""));
          continue;
        }
        if (
          !rawLine.trim() ||
          rawLine.startsWith(":") ||
          rawLine.startsWith("event:") ||
          rawLine.startsWith("id:") ||
          rawLine.startsWith("retry:")
        ) {
          continue;
        }
        // Tolerate legacy payload fragments that do not repeat "data:" per line.
        eventDataLines.push(rawLine);
      }
      if (eventDataLines.length === 0) {
        return;
      }
      const data = eventDataLines.join("\n");
      const bodyLines: string[] = [];
      for (const rawLine of data.split(/\r?\n/)) {
        const line = rawLine.trim();
        if (line.startsWith("Trace:")) {
          setMeta((prev) => ({ ...prev, trace: line.replace("Trace:", "").trim() }));
          continue;
        }
        if (line.startsWith("Citations:")) {
          setMeta((prev) => ({ ...prev, citations: line.replace("Citations:", "").trim() }));
          continue;
        }
        if (line.startsWith("Disclaimer:")) {
          setMeta((prev) => ({ ...prev, disclaimer: line.replace("Disclaimer:", "").trim() }));
          continue;
        }
        if (line.startsWith("Tools:")) {
          setMeta((prev) => ({ ...prev, tools: line.replace("Tools:", "").trim() }));
          continue;
        }
        if (line.startsWith("ResponseMode:")) {
          setMeta((prev) => ({ ...prev, responseMode: line.replace("ResponseMode:", "").trim() }));
          continue;
        }
        if (line.startsWith("ResponseFallback:")) {
          setMeta((prev) => ({ ...prev, responseFallback: line.replace("ResponseFallback:", "").trim() }));
          continue;
        }
        if (line.startsWith("ResponseReasonCodes:")) {
          setMeta((prev) => ({
            ...prev,
            responseReasonCodes: line.replace("ResponseReasonCodes:", "").trim(),
          }));
          continue;
        }
        if (line.startsWith("ResponseStatus:")) {
          const value = line.replace("ResponseStatus:", "").trim().toLowerCase();
          responseStatusSnapshot = value;
          setMeta((prev) => ({ ...prev, responseStatus: value }));
          continue;
        }
        if (line.startsWith("ResponseJobId:")) {
          const value = line.replace("ResponseJobId:", "").trim();
          pendingJobId = value;
          setMeta((prev) => ({ ...prev, responseJobId: value }));
          continue;
        }
        if (line.startsWith("RetryAfterSeconds:")) {
          const value = line.replace("RetryAfterSeconds:", "").trim();
          const parsed = Number.parseInt(value, 10);
          if (Number.isFinite(parsed) && parsed > 0) {
            pendingRetryAfterSeconds = parsed;
          }
          setMeta((prev) => ({ ...prev, retryAfterSeconds: value }));
          continue;
        }
        if (line.startsWith("ExecutedTools:")) {
          const value = line.replace("ExecutedTools:", "").trim();
          setMeta((prev) => ({ ...prev, executedTools: value }));
          continue;
        }
        if (line.startsWith("RuntimeSource:")) {
          setMeta((prev) => ({ ...prev, runtimeSource: line.replace("RuntimeSource:", "").trim() }));
          continue;
        }
        bodyLines.push(rawLine);
      }
      const body = bodyLines.join("\n").trim();
      if (!body) {
        return;
      }

      // Simulate token-by-token rendering
      for (const ch of body) {
        current += ch;
        setMessages((prev) => {
          const updated = [...prev];
          const idx = assistantIndex >= 0 ? assistantIndex : updated.findLastIndex((m) => m.role === "assistant");
          if (idx >= 0) {
            updated[idx] = { role: "assistant", text: current.trim() };
          }
          return updated;
        });
      }
      current += "\n";
      setMessages((prev) => {
        const updated = [...prev];
        const idx = assistantIndex >= 0 ? assistantIndex : updated.findLastIndex((m) => m.role === "assistant");
        if (idx >= 0) {
          updated[idx] = { role: "assistant", text: current.trim() };
        }
        return updated;
      });
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        handleSsePart(part);
      }
    }
    buffer += decoder.decode();
    const tailParts = buffer.split("\n\n");
    for (const part of tailParts) {
      if (part.trim()) {
        handleSsePart(part);
      }
    }

    if (responseStatusSnapshot === "pending" && pendingJobId) {
      let attempts = 0;
      while (attempts < 20) {
        attempts += 1;
        const pollResponse = await fetch(
          `${apiBase}/chat/jobs/${encodeURIComponent(pendingJobId)}?wait_seconds=8`,
          {
            method: "GET",
            headers: pollHeaders,
          },
        );
        if (!pollResponse.ok) {
          const errorText = await pollResponse.text();
          setMessages((prev) => {
            const updated = [...prev];
            const idx = assistantIndex >= 0 ? assistantIndex : updated.findLastIndex((m) => m.role === "assistant");
            if (idx >= 0) {
              updated[idx] = {
                role: "assistant",
                text: `Error polling job ${pendingJobId}: ${pollResponse.status} ${errorText || pollResponse.statusText}`,
              };
            }
            return updated;
          });
          break;
        }

        const polled = await pollResponse.json();
        const polledMeta =
          polled && typeof polled === "object" && polled.response_meta && typeof polled.response_meta === "object"
            ? polled.response_meta
            : {};
        const polledStatus = String(polled.status || polledMeta.response_status || "")
          .trim()
          .toLowerCase();
        const polledResult = String(polled.result || "");
        const polledTools = Array.isArray(polled.tool_calls)
          ? polled.tool_calls.map((item: unknown) => String(item || "").trim()).filter(Boolean).join(", ")
          : "";
        const polledReasons = Array.isArray(polledMeta.reason_codes)
          ? polledMeta.reason_codes
              .map((item: unknown) => String(item || "").trim())
              .filter(Boolean)
              .join(", ")
          : "";
        const polledExecutedTools = Array.isArray(polledMeta.executed_tools)
          ? polledMeta.executed_tools
              .map((item: unknown) => String(item || "").trim())
              .filter(Boolean)
              .join(", ")
          : "";
        const nextRetryAfter = Number(polled.retry_after_seconds || polledMeta.retry_after_seconds || 0);
        if (Number.isFinite(nextRetryAfter) && nextRetryAfter > 0) {
          pendingRetryAfterSeconds = nextRetryAfter;
        }

        setMeta((prev) => ({
          ...prev,
          responseStatus: polledStatus || prev.responseStatus,
          responseJobId: String(polled.response_id || pendingJobId),
          retryAfterSeconds: String(pendingRetryAfterSeconds),
          responseReasonCodes: polledReasons || prev.responseReasonCodes,
          tools: polledTools || prev.tools,
          executedTools: polledExecutedTools || prev.executedTools,
          trace: String(polled.trace_id || prev.trace || ""),
        }));

        if (polledResult.trim()) {
          setMessages((prev) => {
            const updated = [...prev];
            const idx = assistantIndex >= 0 ? assistantIndex : updated.findLastIndex((m) => m.role === "assistant");
            if (idx >= 0) {
              updated[idx] = { role: "assistant", text: polledResult.trim() };
            }
            return updated;
          });
        }

        if (polledStatus === "completed" || polledStatus === "failed") {
          break;
        }

        await new Promise((resolve) => setTimeout(resolve, Math.max(1, pendingRetryAfterSeconds) * 1000));
      }
    }
    setStreaming(false);
  }

  return (
    <AppShell
      title="Tier2 Advisory"
      subtitle="AgentCore Runtime • LangGraph orchestration • KB citations"
    >
      <section className="card p-6">
        <div className="space-y-4">
          <div className="chat-bubble chat-agent max-w-[80%]">
            Ask about 30/60d summary, largest txn, or housing ETA.
          </div>
          <div className="rounded-2xl border border-slate/10 bg-white/70 p-4">
            <p className="section-title">Access token</p>
            <p className="subtle mt-2">
              Paste Cognito AccessToken to call the secured `/chat/stream`. Leave empty if backend
              is running with `DEV_BYPASS_AUTH=true`.
            </p>
            <input
              className="input mt-3"
              placeholder="Paste AccessToken here (JWT)"
              value={accessToken}
              onChange={(e) => handleTokenChange(e.target.value)}
            />
          </div>
          {messages.map((msg, idx) => (
            <div
              key={idx}
              className={`chat-bubble ${
                msg.role === "user" ? "chat-user ml-auto" : "chat-agent"
              } max-w-[80%]`}
            >
              {msg.role === "assistant" ? (
                <div className="chat-markdown">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.text}</ReactMarkdown>
                </div>
              ) : (
                msg.text
              )}
            </div>
          ))}
        </div>
        {messages.some((m) => m.role === "assistant") &&
        (meta.trace ||
          meta.citations ||
          meta.disclaimer ||
          meta.tools ||
          meta.executedTools ||
          meta.responseMode ||
          meta.responseFallback ||
          meta.responseReasonCodes ||
          meta.responseStatus ||
          meta.responseJobId ||
          meta.retryAfterSeconds ||
          meta.runtimeSource) ? (
          <div className="mt-4 rounded-2xl border border-slate/10 bg-white/80 p-4">
            <p className="section-title">Why this advice?</p>
            {meta.citations ? <p className="subtle mt-2">Citations: {meta.citations}</p> : null}
            {meta.trace ? <p className="subtle mt-2">Trace ID: {meta.trace}</p> : null}
            {meta.tools ? <p className="subtle mt-2">Tools: {meta.tools}</p> : null}
            {meta.executedTools ? <p className="subtle mt-2">Executed tools: {meta.executedTools}</p> : null}
            {meta.runtimeSource ? <p className="subtle mt-2">Runtime: {meta.runtimeSource}</p> : null}
            {meta.responseMode ? <p className="subtle mt-2">Mode: {meta.responseMode}</p> : null}
            {meta.responseStatus ? <p className="subtle mt-2">Status: {meta.responseStatus}</p> : null}
            {meta.responseJobId ? <p className="subtle mt-2">Job ID: {meta.responseJobId}</p> : null}
            {meta.retryAfterSeconds ? <p className="subtle mt-2">Retry after: {meta.retryAfterSeconds}s</p> : null}
            {meta.responseFallback ? <p className="subtle mt-2">Fallback: {meta.responseFallback}</p> : null}
            {meta.responseReasonCodes ? (
              <p className="subtle mt-2">Reason codes: {meta.responseReasonCodes}</p>
            ) : null}
            {meta.disclaimer ? (
              <p className="subtle mt-3">Disclaimer: {meta.disclaimer}</p>
            ) : null}
          </div>
        ) : null}
        <div className="mt-6 flex gap-3">
          <input
            className="input"
            placeholder="Ask about 30/60d summary, goals, what-if..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
          <button className="button" onClick={handleSend} disabled={streaming}>
            {streaming ? "Streaming..." : "Send"}
          </button>
        </div>
      </section>
    </AppShell>
  );
}
