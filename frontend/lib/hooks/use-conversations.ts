// Conversation detail hook (contract C3): detail (documents), PATCH
// selection replace. Listing and row actions (rename/pin/archive/delete)
// live in the sidebar.
"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getConversation,
  updateConversation,
  type ConversationDetail,
  type Document,
} from "@/lib/api-client";

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

  const reload = useCallback(() => void load(), [load]);

  return {
    detail,
    documents: detail?.documents ?? [],
    readyDocuments,
    loading,
    error,
    setDocuments,
    reload,
  };
}
