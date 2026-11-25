import { useEffect, useRef, useState } from "react";
import { ApiError, getHealth, sendChat } from "./api";
import { Composer } from "./components/Composer";
import { MessageBubble } from "./components/MessageBubble";
import { SystemPromptPanel } from "./components/SystemPromptPanel";
import type { ChatItem, HealthResponse } from "./types";

function createSessionId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `s-${crypto.randomUUID()}`;
  }
  return `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function formatError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 422) {
      return `Invalid message: ${err.detail}`;
    }
    if (err.status === 503) {
      return "All AI providers are unavailable right now. Please try again.";
    }
    return err.detail;
  }
  return "Unexpected error communicating with the server.";
}

export function App() {
  // Fresh session ID generated per page load and kept in memory only.
  const [sessionId] = useState<string>(() => createSessionId());
  const [items, setItems] = useState<ChatItem[]>([]);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [pending, setPending] = useState(false);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState(false);

  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    getHealth()
      .then((res) => {
        setHealth(res);
        setHealthError(false);
      })
      .catch(() => {
        setHealthError(true);
      });
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [items, pending]);

  const handleSend = async (message: string) => {
    const userItem: ChatItem = {
      id: `u-${Date.now()}-${Math.random()}`,
      kind: "user",
      content: message,
    };
    setItems((prev) => [...prev, userItem]);
    setPending(true);

    try {
      const resp = await sendChat({
        session_id: sessionId,
        message,
        system_prompt: systemPrompt || undefined,
      });
      const assistantItem: ChatItem = {
        id: `a-${Date.now()}-${Math.random()}`,
        kind: "assistant",
        content: resp.reply,
        metadata: resp.metadata,
      };
      setItems((prev) => [...prev, assistantItem]);
    } catch (err) {
      const errorItem: ChatItem = {
        id: `e-${Date.now()}-${Math.random()}`,
        kind: "error",
        content: formatError(err),
      };
      setItems((prev) => [...prev, errorItem]);
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="header-title">
          <span className="brand-dot" />
          <h1>Lyftr AI Gateway Chat</h1>
        </div>
        <div className="header-status">
          <span className="status-pill" title="Active in-memory session ID">
            Session: {sessionId.slice(0, 12)}…
          </span>
          {health ? (
            <span className="status-pill status-ok">
              API OK · {health.keys_configured} keys · {health.cache_enabled ? "Cache ON" : "Cache OFF"}
            </span>
          ) : healthError ? (
            <span className="status-pill status-bad">Backend Offline</span>
          ) : (
            <span className="status-pill">Checking API…</span>
          )}
        </div>
      </header>

      <SystemPromptPanel value={systemPrompt} onChange={setSystemPrompt} disabled={pending} />

      <main className="chat-thread">
        {items.length === 0 && (
          <div className="empty-state">
            <h2>Start a conversation</h2>
            <p>
              Messages keep multi-turn context in SQLite per session. Repeat an identical first
              prompt after refreshing to observe <code>LLM_CACHE</code> hits.
            </p>
          </div>
        )}

        {items.map((item) => (
          <MessageBubble key={item.id} item={item} />
        ))}

        {pending && (
          <div className="message-row assistant-row">
            <div className="bubble assistant-bubble typing-bubble">
              <div className="bubble-role">Assistant</div>
              <div className="typing-dots">Thinking…</div>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </main>

      <footer className="composer-footer">
        <Composer onSend={handleSend} disabled={pending} />
      </footer>
    </div>
  );
}

