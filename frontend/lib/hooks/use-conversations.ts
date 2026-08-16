// Conversation detail hook (contract C3): detail (documents), PATCH
// selection replace. Listing and row actions (rename/pin/archive/delete)
// live in the sidebar.
"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getConversation,
  updateConversation,
  type ConversationDetail,
} from "@/lib/api-client";

export function useConversationDetail(conversationId: string | undefined) {
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!conversationId) return;
    if (!silent) setLoading(true);
    try {
      setDetail(await getConversation(conversationId));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load conversation.");
    } finally {
      if (!silent) setLoading(false);
    }
  }, [conversationId]);

  useEffect(() => {
    // Deferred so the initial fetch's setState isn't synchronous with render.
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const setDocuments = useCallback(
    async (documentIds: string[]) => {
      if (!conversationId || !detail) return;
      await updateConversation(conversationId, { document_ids: documentIds });
      const added = documentIds.some((id) => !detail.documents.some((doc) => doc.id === id));
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
      // PATCH returns the conversation only, so additions refetch silently.
      if (added) await load(true);
    },
    [conversationId, detail, load],
  );

  const reload = useCallback(() => void load(), [load]);

  return {
    detail,
    documents: detail?.documents ?? [],
    loading,
    error,
    setDocuments,
    reload,
  };
}
