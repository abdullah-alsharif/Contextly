// Chat workspace hook (contract C4, research D3): history fetch, optimistic
// user + pending assistant messages, SSE streaming, idempotency key reuse on
// retry, error → retry affordance, done → sources finalize.
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  listMessages,
  streamAnswer,
  type Message,
  type Source,
} from "@/lib/api-client";

export interface StreamingMessage {
  role: "user" | "assistant";
  content: string;
  sources: Source[];
  pending?: boolean;
  failed?: boolean;
  error?: string;
  localId: string;
}

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function useChat(conversationId: string | undefined) {
  const [messages, setMessages] = useState<StreamingMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastQuestion, setLastQuestion] = useState<string | null>(null);
  const idempotencyKeyRef = useRef<string | null>(null);

  // Reset on conversation switch.
  useEffect(() => {
    setMessages([]);
    setLoading(true);
    setStreaming(false);
    setError(null);
    setLastQuestion(null);
    idempotencyKeyRef.current = null;
    if (!conversationId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    listMessages(conversationId)
      .then((rows) => {
        if (cancelled) return;
        setMessages(
          rows.map((row: Message) => ({
            role: row.role,
            content: row.content,
            sources: row.sources ?? [],
            localId: row.id,
          })),
        );
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load messages.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  const send = useCallback(
    async (content: string, onRetry = false) => {
      if (!conversationId || streaming) return;

      // Reuse the failed attempt's key so retries never duplicate (docs/chat.md §6).
      if (onRetry) {
        if (!idempotencyKeyRef.current) return;
      } else {
        idempotencyKeyRef.current = newIdempotencyKey();
      }
      const assistantLocalId = `a-${Date.now()}`;

      setMessages((rows) => {
        const base = rows.filter((row) => !(row.failed && row.role === "assistant"));
        const next = onRetry
          ? base
          : [
              ...base,
              { role: "user" as const, content, sources: [], localId: `u-${Date.now()}` },
            ];
        return [
          ...next,
          {
            role: "assistant",
            content: "",
            sources: [],
            pending: true,
            localId: assistantLocalId,
          },
        ];
      });
      setStreaming(true);
      setError(null);
      setLastQuestion(content);

      await streamAnswer(
        conversationId,
        content,
        idempotencyKeyRef.current,
        {
          onDelta: (text) => {
            setMessages((rows) =>
              rows.map((row) =>
                row.localId === assistantLocalId
                  ? { ...row, content: row.content + text }
                  : row,
              ),
            );
          },
          onDone: ({ sources }) => {
            setMessages((rows) =>
              rows.map((row) =>
                row.localId === assistantLocalId
                  ? { ...row, pending: false, sources }
                  : row,
              ),
            );
            idempotencyKeyRef.current = null;
          },
          onError: (message) => {
            setMessages((rows) =>
              rows.map((row) =>
                row.localId === assistantLocalId
                  ? { ...row, pending: false, failed: true, error: message }
                  : row,
              ),
            );
          },
        },
      );
      setStreaming(false);
    },
    [conversationId, streaming],
  );

  const retry = useCallback(() => {
    if (!lastQuestion) return;
    void send(lastQuestion, true);
  }, [lastQuestion, send]);

  return { messages, loading, streaming, error, send, retry, lastQuestion };
}
