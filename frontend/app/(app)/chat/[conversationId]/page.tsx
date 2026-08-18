"use client";

// Chat workspace: context panel + streaming message list + composer; citation
// chips open the source viewer; archived conversations swap the composer for
// an archived notice + Unarchive action.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import ChatComposer from "@/components/chat-composer";
import ChatMessage from "@/components/chat-message";
import ContextPanel from "@/components/context-panel";
import DocumentPicker from "@/components/document-picker";
import EmptyState from "@/components/empty-state";
import SourceViewer from "@/components/source-viewer";
import { updateConversation, type Source } from "@/lib/api-client";
import { notifyCrossTab, subscribeCrossTab } from "@/lib/cross-tab";
import { useChat } from "@/lib/hooks/use-chat";
import { useConversationDetail } from "@/lib/hooks/use-conversations";
import { useDocuments } from "@/lib/hooks/use-documents";

export default function ConversationPage() {
  const params = useParams<{ conversationId: string }>();
  const conversationId = params.conversationId;

  const {
    detail,
    loading: conversationLoading,
    error: conversationError,
    setDocuments,
    reload,
  } = useConversationDetail(conversationId);
  const { messages, loading: messagesLoading, streaming, error, send, retry, lastQuestion } =
    useChat(conversationId);
  const { readyDocuments: allReadyDocuments } = useDocuments();

  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [activeSource, setActiveSource] = useState<Source | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Selection resets derive during render: switch clears, detail load
  // restores the persisted set.
  const [prevConversationId, setPrevConversationId] = useState(conversationId);
  const [prevDetailId, setPrevDetailId] = useState<string | null>(null);
  if (conversationId !== prevConversationId) {
    setPrevConversationId(conversationId);
    setSelectedIds([]);
    setPrevDetailId(null);
  }
  if (detail && detail.conversation.id !== prevDetailId) {
    setPrevDetailId(detail.conversation.id);
    setSelectedIds(
      detail.documents
        .filter((doc) => doc.status === "ready")
        .map((doc) => doc.id),
    );
  }

  const persistSelection = useCallback(
    (ids: string[]) => {
      setSelectedIds(ids);
      if (detail && conversationId) void setDocuments(ids);
    },
    [setDocuments, detail, conversationId],
  );

  const selectedDocuments = useMemo(
    () => allReadyDocuments.filter((doc) => selectedIds.includes(doc.id)),
    [allReadyDocuments, selectedIds],
  );

  // AI Context Bar glow follows the streaming state.
  useEffect(() => {
    document
      .getElementById("ai-context-bar")
      ?.classList.toggle("active", streaming);
    return () => document.getElementById("ai-context-bar")?.classList.remove("active");
  }, [streaming]);

  // Sidebar rename/archive reloads this page (same tab + cross-tab).
  useEffect(() => {
    const onConversationsUpdated = () => reload();
    window.addEventListener("conversations:updated", onConversationsUpdated);
    const unsubscribe = subscribeCrossTab("conversations:updated", onConversationsUpdated);
    return () => {
      window.removeEventListener("conversations:updated", onConversationsUpdated);
      unsubscribe();
    };
  }, [reload]);

  const archived = detail?.conversation.archived ?? false;

  // Auto-scroll: pin to the bottom until the user scrolls away. The latch
  // keeps mid-stream renders from fighting the user's scroll gesture.
  const stickToBottom = useRef(true);
  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    const onScroll = () => {
      const atBottom =
        container.scrollHeight - container.scrollTop - container.clientHeight < 24;
      if (atBottom !== stickToBottom.current) stickToBottom.current = atBottom;
    };
    container.addEventListener("scroll", onScroll, { passive: true });
    return () => container.removeEventListener("scroll", onScroll);
  }, []);
  useEffect(() => {
    const container = scrollRef.current;
    if (!container || !stickToBottom.current) return;
    container.scrollTop = container.scrollHeight;
  });

  // Opening a source pauses auto-follow: the side panel narrows the column
  // and reflows messages taller, so pinning would yank the viewport away.
  const handleCite = useCallback(
    (source: Source) => {
      stickToBottom.current = false;
      setActiveSource(source);
    },
    [],
  );

  // Unarchive; the sidebar refreshes via the event.
  const handleUnarchive = useCallback(async () => {
    if (!conversationId) return;
    try {
      await updateConversation(conversationId, { archived: false });
      window.dispatchEvent(new CustomEvent("conversations:updated"));
      notifyCrossTab("conversations:updated");
      reload();
    } catch {
      // stay archived; the action remains available
    }
  }, [conversationId, reload]);

  const loading = conversationLoading || messagesLoading;

  return (
    <div className="flex h-full bg-surface-container-lowest">
      <ContextPanel
        readyDocuments={allReadyDocuments}
        selectedIds={selectedIds}
        setSelectedIds={persistSelection}
        defaultSelectedOnly
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <div
          ref={scrollRef}
          className="custom-scrollbar [overflow-anchor:none] flex-1 overflow-y-auto px-4 py-5 md:px-6 md:py-6"
        >
          {loading ? (
            <EmptyState icon="hourglass_empty" title="Loading conversation…" />
          ) : conversationError ? (
            <div className="rounded-xl border border-error-container/40 bg-error-container/60 px-4 py-3 text-body-sm text-error" role="alert">
              {conversationError}
            </div>
          ) : messages.length === 0 ? (
            archived ? (
              <EmptyState icon="archive" title="This conversation has no messages" />
            ) : (
              <EmptyState
                icon="waving_hand"
                title={
                  selectedDocuments.length ? "Ask anything" : "Pick documents, then ask"
                }
                hint={
                  selectedDocuments.length ? (
                    "Your question will be answered from the selected documents with cited sources."
                  ) : (
                    <>
                      <span className="lg:hidden">
                        Tap the + below the message box to add documents from your
                        library, then ask your first question.
                      </span>
                      <span className="hidden lg:inline">
                        Select at least one ready document in the panel on the left,
                        then ask your first question.
                      </span>
                    </>
                  )
                }
              />
            )
          ) : (
            <div className="mx-auto flex w-full max-w-4xl flex-col gap-stack-lg">
              {messages.map((message) => (
                <div key={message.localId}>
                  <ChatMessage
                    role={message.role}
                    content={message.content}
                    sources={message.sources ?? []}
                    pending={message.pending}
                    failed={message.failed}
                    onCite={message.role === "assistant" ? handleCite : undefined}
                  />
                  {message.failed && message.role === "assistant" && (
                    <div className="mt-1.5 flex items-center gap-2 pl-11">
                      <p className="text-label-sm text-error">{message.error}</p>
                      <button
                        type="button"
                        onClick={() => void retry()}
                        disabled={streaming}
                        className="rounded-lg bg-secondary px-3 py-1 font-display text-label-sm text-white transition-colors enabled:hover:bg-secondary-fixed-dim disabled:opacity-50"
                      >
                        Retry
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
          {error && !streaming && (
            <p className="mt-4 text-center text-label-sm text-error">{error}</p>
          )}
        </div>

        {archived ? (
          <div className="flex flex-col items-center gap-3 border-t border-surface-variant bg-surface-container-lowest px-4 py-4">
            <p className="text-center text-[15px] text-[#626262]">
              This conversation is archived. To continue, please unarchive it first.
            </p>
            <button
              type="button"
              onClick={() => void handleUnarchive()}
              className="flex h-10 cursor-pointer items-center justify-center gap-2 rounded-full bg-[#0D0D0D] px-6 text-white transition-colors duration-150 hover:bg-[#1F1F1F] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0D0D0D] focus-visible:ring-offset-2"
            >
              <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
                unarchive
              </span>
              <span className="font-display text-label-md">Unarchive</span>
            </button>
          </div>
        ) : (
          <ChatComposer
            selectedDocuments={selectedDocuments}
            onAddDocuments={() => setPickerOpen(true)}
            onSend={(content) => void send(content)}
            busy={streaming}
          />
        )}
      </div>

      {pickerOpen && (
        <DocumentPicker
          readyDocuments={allReadyDocuments}
          selectedIds={selectedIds}
          onAdd={(ids) => {
            persistSelection(Array.from(new Set([...selectedIds, ...ids])));
            setPickerOpen(false);
          }}
          onClose={() => setPickerOpen(false)}
        />
      )}

      {activeSource && (
        <SourceViewer
          source={activeSource}
          question={lastQuestion ?? undefined}
          onClose={() => setActiveSource(null)}
        />
      )}
    </div>
  );
}