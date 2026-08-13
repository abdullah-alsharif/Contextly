// Chat composer — mirrors prototypes/chat.html: rounded-2xl surface card
// with border + shadow, body-md textarea, ghost attach/mic actions, square
// accent send with shadow, centered disclaimer. Blocks send when no
// documents are selected (pre-empts the backend 400, docs/chat.md §6).
"use client";

import { useRef, useState, type KeyboardEvent } from "react";

interface ChatComposerProps {
  selectedDocuments: { id: string; filename: string }[];
  onRemoveDocument: (id: string) => void;
  onSend: (content: string) => void;
  busy: boolean;
}

export default function ChatComposer({
  selectedDocuments,
  onRemoveDocument,
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
    <div className="border-t border-surface-variant bg-surface-container-lowest px-4 py-4">
      {selectedDocuments.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <span className="font-display text-label-sm text-on-surface-variant">Using:</span>
          {selectedDocuments.map((document) => (
            <span
              key={document.id}
              className="inline-flex max-w-48 items-center gap-1 rounded-full bg-surface-container-high px-2.5 py-0.5"
            >
              <span className="truncate font-display text-label-sm text-on-surface">
                {document.filename}
              </span>
              <button
                type="button"
                onClick={() => onRemoveDocument(document.id)}
                aria-label={`Remove ${document.filename}`}
                className="text-on-surface-variant transition-colors hover:text-secondary"
              >
                <span className="material-symbols-outlined text-sm">close</span>
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="rounded-2xl border border-outline-variant bg-surface-container-lowest shadow-sm">
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
          className="custom-scrollbar w-full resize-none bg-transparent p-4 text-body-md outline-none placeholder:text-on-surface-variant/70"
        />
        <div className="flex items-center justify-between px-4 pb-3">
          <div className="flex gap-2">
            <button
              type="button"
              title="Attach file"
              className="rounded p-1 text-on-surface-variant transition-colors hover:bg-surface-container hover:text-secondary"
            >
              <span className="material-symbols-outlined">attach_file</span>
            </button>
            <button
              type="button"
              title="Voice input"
              className="rounded p-1 text-on-surface-variant transition-colors hover:bg-surface-container hover:text-secondary"
            >
              <span className="material-symbols-outlined">mic</span>
            </button>
          </div>
          <button
            type="button"
            disabled={!canSend}
            onClick={() => submit(value)}
            aria-label="Send message"
            className="flex items-center justify-center rounded-lg bg-secondary p-2 text-on-secondary shadow-sm transition-transform hover:bg-secondary/90 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <span className="material-symbols-outlined fill">send</span>
          </button>
        </div>
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