"use client";

import AppShell from "@/components/AppShell";
import { useEffect, useState } from "react";

export default function ChatPage() {
  const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8010";
  const [messages, setMessages] = useState<
    { role: "user" | "assistant"; text: string }[]
  >([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [accessToken, setAccessToken] = useState("");
  const [meta, setMeta] = useState<{ trace?: string; citations?: string; disclaimer?: string }>({});

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
      const next = [...prev, { role: "user", text: userText }, { role: "assistant", text: "" }];
      assistantIndex = next.length - 1;
      return next;
    });
    setStreaming(true);

    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (accessToken.trim()) {
      headers.Authorization = `Bearer ${accessToken.trim()}`;
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
    const decoder = new TextDecoder();
    let buffer = "";
    let current = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        if (part.startsWith("data:")) {
          const data = part.replace(/^data:\s?/, "");
          if (data.startsWith("Trace:")) {
            setMeta((prev) => ({ ...prev, trace: data.replace("Trace:", "").trim() }));
            continue;
          }
          if (data.startsWith("Citations:")) {
            setMeta((prev) => ({ ...prev, citations: data.replace("Citations:", "").trim() }));
            continue;
          }
          if (data.startsWith("Disclaimer:")) {
            setMeta((prev) => ({ ...prev, disclaimer: data.replace("Disclaimer:", "").trim() }));
            continue;
          }

          // Simulate token-by-token rendering
          for (const ch of data) {
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
        }
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
              {msg.text}
            </div>
          ))}
        </div>
        {messages.some((m) => m.role === "assistant") && (meta.trace || meta.citations || meta.disclaimer) ? (
          <div className="mt-4 rounded-2xl border border-slate/10 bg-white/80 p-4">
            <p className="section-title">Why this advice?</p>
            {meta.citations ? <p className="subtle mt-2">Citations: {meta.citations}</p> : null}
            {meta.trace ? <p className="subtle mt-2">Trace ID: {meta.trace}</p> : null}
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
