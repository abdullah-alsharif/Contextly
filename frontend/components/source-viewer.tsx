// Source viewer — mirrors prototypes/chat.html right panel: w-80 persistent
// panel (xl:flex) with source card — tertiary-fixed header `[1] filename ·
// Page N`, excerpt with <mark> highlight, "Open Document" link via signed URL
// (contract C5). Excerpt comes from the stored source payload (FR-011).
"use client";

import { useMemo, useState } from "react";
import { getDownloadUrl, type Source } from "@/lib/api-client";

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

export default function SourceViewer({
  source,
  question,
  onClose,
}: {
  source: Source;
  question?: string;
  onClose: () => void;
}) {
  const [openError, setOpenError] = useState<string | null>(null);

  const excerpt = useMemo(
    () => highlightQuestionTerms(source.excerpt ?? "Excerpt unavailable — the source may have been removed.", question ?? ""),
    [source.excerpt, question],
  );

  const openDocument = async () => {
    setOpenError(null);
    try {
      const { url } = await getDownloadUrl(source.document_id);
      window.open(url, "_blank", "noopener");
    } catch {
      setOpenError("Could not open the document. Try again.");
    }
  };

  return (
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
              onClick={() => void openDocument()}
              className="flex items-center gap-1 font-display text-label-sm text-secondary hover:underline"
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
      </div>
    </aside>
  );
}