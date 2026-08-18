// Source viewer (docs/api.md C5): persistent right panel at xl+, bottom
// sheet below so citation taps are never dead. Excerpt with <mark> highlight;
// "Open Document" streams the PDF bytes via blob URL (FR-011).
"use client";

import { useEffect, useMemo, useState } from "react";
import { downloadDocument, type Source } from "@/lib/api-client";

const STOP_WORDS = new Set([
  "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "been",
  "to", "of", "in", "on", "for", "with", "about", "this", "that", "what", "how",
  "does", "do", "did", "can", "could", "would", "should", "i", "you", "me", "my",
]);

function highlightQuestionTerms(excerpt: string, question: string): React.ReactNode {
  const terms = question
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((term) => term.length >= 4 && !STOP_WORDS.has(term));
  if (terms.length === 0) return excerpt;

  const pattern = new RegExp(`(${terms.sort((a, b) => b.length - a.length).join("|")})`, "ig");
  const parts = excerpt.split(pattern);
  return parts.map((part, index) =>
    pattern.test(part) ? (
      <mark key={index} className="rounded bg-secondary-fixed-dim/50 px-1 text-on-surface">
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

function SourceCard({
  source,
  question,
  objectUrl,
  openError,
  onOpen,
}: {
  source: Source;
  question?: string;
  objectUrl: string | null;
  openError: string | null;
  onOpen: () => void;
}) {
  const excerpt = useMemo(
    () =>
      highlightQuestionTerms(
        source.excerpt ?? "Excerpt unavailable — the source may have been removed.",
        question ?? "",
      ),
    [source.excerpt, question],
  );

  return (
    <div className="mb-4 overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest shadow-sm">
      <div className="flex items-center gap-2 border-b border-outline-variant bg-tertiary-fixed px-3 py-2">
        <span className="font-display text-label-md font-bold text-on-tertiary-fixed">[1]</span>
        <span className="truncate font-display text-label-md text-on-tertiary-fixed">
          {source.filename}
        </span>
        <span className="ml-auto font-display text-label-sm text-on-tertiary-fixed/70">
          Page {source.page_number}
        </span>
      </div>
      <div className="p-4">
        <p className="text-justify leading-relaxed text-body-sm text-on-surface">{excerpt}</p>
      </div>
      <div className="flex justify-end border-t border-surface-variant bg-surface-container-low p-2">
        <button
          type="button"
          onClick={onOpen}
          disabled={!objectUrl}
          className="flex items-center gap-1 font-display text-label-sm text-secondary hover:underline disabled:cursor-not-allowed disabled:opacity-50"
        >
          Open Document
          <span className="material-symbols-outlined text-[14px]">open_in_new</span>
        </button>
      </div>
      {openError && (
        <p className="px-3 pb-2 text-center text-label-sm text-error" role="alert">
          {openError}
        </p>
      )}
    </div>
  );
}

export default function SourceViewer({
  source,
  question,
  onClose,
}: {
  source: Source;
  question?: string;
  onClose: () => void;
}) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);

  // Reset on source change, derived during render.
  const [prevDocId, setPrevDocId] = useState(source.document_id);
  if (source.document_id !== prevDocId) {
    setPrevDocId(source.document_id);
    setObjectUrl(null);
    setOpenError(null);
  }

  // Prefetch the bytes so the click opens synchronously — an await in the
  // handler would lose the user gesture and the popup would be blocked.
  useEffect(() => {
    let cancelled = false;
    void downloadDocument(source.document_id)
      .then((blob) => {
        if (!cancelled) setObjectUrl(URL.createObjectURL(blob));
      })
      .catch(() => {
        if (!cancelled) setOpenError("Could not open the document. Try again.");
      });
    return () => {
      cancelled = true;
    };
  }, [source.document_id]);

  const openDocument = () => {
    if (!objectUrl) return;
    window.open(objectUrl, "_blank", "noopener");
  };

  return (
    <>
      {/* Desktop / wide tablet: persistent right panel */}
      <aside className="relative z-10 hidden w-80 shrink-0 flex-col border-l border-surface-variant bg-surface shadow-[-5px_0_15px_-3px_rgba(0,0,0,0.05)] xl:flex">
        <div className="sticky top-0 flex items-center justify-between border-b border-surface-variant bg-surface p-stack-md">
          <h2 className="flex items-center gap-2 font-display text-title-lg text-on-surface">
            <span className="material-symbols-outlined">plagiarism</span>
            Source Viewer
          </h2>
          <button
            type="button"
            onClick={onClose}
            title="Close source viewer"
            aria-label="Close source viewer"
            className="rounded p-1 text-on-surface-variant transition-colors hover:bg-surface-container hover:text-secondary"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        <div className="custom-scrollbar flex-1 overflow-y-auto p-stack-md">
          <SourceCard
            source={source}
            question={question}
            objectUrl={objectUrl}
            openError={openError}
            onOpen={openDocument}
          />
        </div>
      </aside>

      {/* Mobile / tablet: bottom sheet */}
      <div
        className="fixed inset-0 z-50 xl:hidden"
        role="dialog"
        aria-modal="true"
        aria-label="Source viewer"
      >
        <div
          className="fade-in absolute inset-0 bg-black/40"
          onClick={onClose}
          aria-hidden="true"
        />
        <aside className="sheet-in absolute inset-x-0 bottom-0 flex max-h-[75dvh] w-full flex-col rounded-t-2xl border-t border-surface-variant bg-surface pb-[env(safe-area-inset-bottom)] shadow-[0_-10px_30px_-10px_rgba(0,0,0,0.2)]">
          <div
            className="mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-surface-variant"
            aria-hidden="true"
          />
          <div className="flex shrink-0 items-center justify-between border-b border-surface-variant px-4 py-3">
            <h2 className="flex items-center gap-2 font-display text-title-lg text-on-surface">
              <span className="material-symbols-outlined">plagiarism</span>
              Source Viewer
            </h2>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close source viewer"
              className="flex h-10 w-10 items-center justify-center rounded-lg text-on-surface-variant transition-colors hover:bg-surface-container hover:text-secondary"
            >
              <span className="material-symbols-outlined">close</span>
            </button>
          </div>
          <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto p-4">
            <SourceCard
              source={source}
              question={question}
              objectUrl={objectUrl}
              openError={openError}
              onOpen={openDocument}
            />
          </div>
        </aside>
      </div>
    </>
  );
}
