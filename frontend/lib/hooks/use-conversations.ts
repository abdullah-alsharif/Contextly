// Conversations hook (contract C3): list (updated_at desc), create with
// document_ids, detail (documents), PATCH selection replace, delete.
"use client";

import { useCallback, useEffect, useState } from "react";
import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  updateConversation,
  type Conversation,
  type ConversationDetail,
  type Document,
} from "@/lib/api-client";

export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      setConversations(await listConversations());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load conversations.");
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const create = useCallback(
    async (init?: { title?: string; document_ids?: string[] }) => {
      const conversation = await createConversation(init ?? {});
      setConversations((rows) => [conversation, ...rows]);
      return conversation;
    },
    [],
  );

  const remove = useCallback(async (id: string) => {
    try {
      await deleteConversation(id);
    } catch {
      // 404-tolerant — row disappears either way
    }
    setConversations((rows) => rows.filter((row) => row.id !== id));
  }, []);

  return { conversations, loading, error, refresh, create, remove };
}

export function useConversationDetail(conversationId: string | undefined) {
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!conversationId) return;
    setLoading(true);
    try {
      setDetail(await getConversation(conversationId));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load conversation.");
    } finally {
      setLoading(false);
    }
  }, [conversationId]);

  useEffect(() => {
    void load();
  }, [load]);

  const setDocuments = useCallback(
    async (documentIds: string[]) => {
      if (!conversationId || !detail) return;
      await updateConversation(conversationId, { document_ids: documentIds });
      setDetail((current) =>
        current
          ? {
              ...current,
              documents: current.documents.filter((doc) =>
                documentIds.includes(doc.id),
              ),
            }
          : current,
      );
    },
    [conversationId, detail],
  );

  const readyDocuments = (detail?.documents ?? []).filter(
    (doc: Document) => doc.status === "ready",
  );

  return { detail, documents: detail?.documents ?? [], readyDocuments, loading, error, setDocuments };
}