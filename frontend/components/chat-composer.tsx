// Chat composer: rounded surface card with textarea, ghost add-documents
// action and accent send; blocks send when no documents are selected.
"use client";

import { useRef, useState, type KeyboardEvent } from "react";

interface ChatComposerProps {
  selectedDocuments: { id: string; filename: string }[];
  onAddDocuments: () => void;
  onSend: (content: string) => void;
  busy: boolean;
}

export default function ChatComposer({
  selectedDocuments,
  onAddDocuments,
  onSend,
  busy,
}: ChatComposerProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const canSend = value.trim().length > 0 && selectedDocuments.length > 0 && !busy;
  const blockedReason =
    selectedDocuments.length === 0
      ? "Add documents to this conversation first"
      : null;

  const submit = (content: string) => {
    const trimmed = content.trim();
    if (!trimmed || selectedDocuments.length === 0 || busy) return;
    onSend(trimmed);
    setValue("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit(value);
    }
  };

  return (
    <div className="border-t border-surface-variant bg-surface-container-lowest px-3 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] md:px-4 md:py-4">
      <div className="flex items-end gap-2 rounded-2xl border border-outline-variant bg-surface-container-lowest p-3 shadow-sm md:p-4">
        <button
          type="button"
          onClick={onAddDocuments}
          title="Add documents"
          aria-label="Add documents"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-on-surface-variant transition-colors hover:bg-surface-container hover:text-secondary lg:hidden"
        >
          <span className="material-symbols-outlined" aria-hidden="true">
            add
          </span>
        </button>
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            event.target.style.height = "auto";
            event.target.style.height = `${Math.min(event.target.scrollHeight, 200)}px`;
          }}
          onKeyDown={onKeyDown}
          rows={2}
          placeholder={
            busy
              ? "Thinking…"
              : blockedReason
                ? blockedReason
                : "Ask a question about your documents..."
          }
          aria-label="Message"
          className="custom-scrollbar min-w-0 flex-1 resize-none bg-transparent text-body-md outline-none placeholder:text-on-surface-variant/70"
        />
        <button
          type="button"
          disabled={!canSend}
          onClick={() => submit(value)}
          aria-label="Send message"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-secondary p-2 text-on-secondary shadow-sm transition-transform hover:bg-secondary/90 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <span className="material-symbols-outlined fill">send</span>
        </button>
      </div>

      <p className="mt-2 flex items-center justify-center gap-1 font-display text-label-sm text-on-surface-variant">
        {busy ? (
          <span className="inline-flex items-center">
            Contextly is answering
            <span
              className="typing-dot ml-1 h-1 w-1 rounded-full bg-on-surface-variant"
              style={{ animationDelay: "0ms" }}
            />
            <span
              className="typing-dot ml-1 h-1 w-1 rounded-full bg-on-surface-variant"
              style={{ animationDelay: "150ms" }}
            />
            <span
              className="typing-dot ml-1 h-1 w-1 rounded-full bg-on-surface-variant"
              style={{ animationDelay: "300ms" }}
            />
          </span>
        ) : blockedReason ? (
          `${blockedReason} (the API rejects questions without selected documents).`
        ) : (
          "AI can make mistakes. Consider verifying important information."
        )}
      </p>
    </div>
  );
}