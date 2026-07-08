import { useCallback, useEffect, useRef, useState } from "react";
import { streamChat, webSearch, type ChatMessage } from "../api";
import { Message, type UIMessage } from "./Message";
import { SearchToggle } from "./SearchToggle";

export interface ChatProps {
  webSearchEnabled: boolean;
}

export function Chat({ webSearchEnabled }: ChatProps) {
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [searchActive, setSearchActive] = useState(false);
  const nextId = useRef(1);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages]);

  const patch = useCallback((id: number, changes: Partial<UIMessage>) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...changes } : m)));
  }, []);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;

    const userMsg: UIMessage = { id: nextId.current++, role: "user", content: text };
    const assistantId = nextId.current++;
    const assistantMsg: UIMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      streaming: true,
    };
    // Build history from the prior turns before adding the new pair.
    const history: ChatMessage[] = messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput("");
    setBusy(true);

    // FR-05: when web search is on, run a Brave search and show results.
    if (searchActive && webSearchEnabled) {
      try {
        const results = await webSearch(text);
        patch(assistantId, { webResults: results });
      } catch (err) {
        patch(assistantId, {
          content: (err as Error).message,
          error: true,
        });
      }
    }

    // FR-04: stream the RAG-grounded answer token by token.
    await streamChat(text, history, {
      onCitations: (citations) => patch(assistantId, { citations }),
      onToken: (token) =>
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? { ...m, content: m.content + token } : m,
          ),
        ),
      onError: (message) => patch(assistantId, { content: message, error: true }),
      onDone: () => {
        patch(assistantId, { streaming: false });
        setBusy(false);
      },
    });
  }, [input, busy, messages, searchActive, webSearchEnabled, patch]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  return (
    <div className="chat">
      <div className="messages" ref={listRef}>
        {messages.length === 0 && (
          <div className="empty-state">
            Escribe una consulta sobre normativa municipal chilena. Las respuestas
            se basan únicamente en el corpus legal cargado en este equipo.
          </div>
        )}
        {messages.map((m) => (
          <Message key={m.id} msg={m} />
        ))}
      </div>

      <div className="composer">
        <div className="composer-toolbar">
          <SearchToggle
            enabled={webSearchEnabled}
            active={searchActive}
            onChange={setSearchActive}
          />
        </div>
        <div className="composer-row">
          <textarea
            value={input}
            placeholder="Escribe tu consulta..."
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            rows={2}
          />
          <button
            type="button"
            className="send-btn"
            disabled={busy || !input.trim()}
            onClick={() => void send()}
          >
            {busy ? "..." : "Enviar"}
          </button>
        </div>
      </div>
    </div>
  );
}
