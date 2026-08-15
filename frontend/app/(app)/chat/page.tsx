"use client";

// Chat entry (docs/frontend-design.md §4): three-pane shell with first-message
// empty state (context panel + empty chat column). Starting a conversation
// carries any pre-selected ready documents (US3 AC5).
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import ContextPanel from "@/components/context-panel";
import EmptyState from "@/components/empty-state";
import { createConversation } from "@/lib/api-client";
import { useDocuments } from "@/lib/hooks/use-documents";

export default function ChatPage() {
  const router = useRouter();
  const { documents } = useDocuments();
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const readyDocuments = useMemo(
    () => documents.filter((doc) => doc.status === "ready"),
    [documents],
  );

  const startConversation = async () => {
    if (creating) return;
    setCreating(true);
    setError(null);
    try {
      const conversation = await createConversation({
        document_ids: selectedIds.length > 0 ? selectedIds : undefined,
      });
      router.push(`/chat/${conversation.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the conversation.");
      setCreating(false);
    }
  };

  return (
    <div className="flex h-full">
      <ContextPanel
        readyDocuments={readyDocuments}
        selectedIds={selectedIds}
        setSelectedIds={setSelectedIds}
      />
      <div className="flex min-w-0 flex-1 flex-col items-center justify-center px-8">
        <EmptyState
          icon="forum"
          title="Start your first conversation"
          hint="Select documents in the context panel, then create a conversation to ask questions with cited answers."
        />
        <button
          type="button"
          onClick={() => void startConversation()}
          disabled={creating}
          className="mt-4 flex items-center gap-2 rounded-lg bg-secondary px-4 py-2 font-display text-label-md text-white transition-colors enabled:hover:bg-secondary-fixed-dim disabled:opacity-60"
        >
          <span className="material-symbols-outlined text-label-md" aria-hidden="true">
            add_comment
          </span>
          {creating ? "Creating…" : "New Conversation"}
        </button>
        {error && (
          <p className="mt-3 rounded-lg border border-error-container/40 bg-error-container/60 px-3 py-1.5 text-label-sm text-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}