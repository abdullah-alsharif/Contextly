// Context panel — mirrors prototypes/chat.html left panel: w-72, sticky
// header on surface-container-lowest, ready-doc rows with checkbox +
// secondary icon + meta, empty state when no ready documents.
"use client";

import { useMemo } from "react";
import type { Document } from "@/lib/api-client";

function fileIcon(filename: string): string {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return "picture_as_pdf";
  if (["txt", "md", "csv", "json"].includes(ext)) return "description";
  return "text_snippet";
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export default function ContextPanel({
  readyDocuments,
  selectedIds,
  setSelectedIds,
}: {
  readyDocuments: Document[];
  selectedIds: string[];
  setSelectedIds: (ids: string[]) => void;
}) {
  const toggle = (id: string) => {
    setSelectedIds(
      selectedIds.includes(id)
        ? selectedIds.filter((x) => x !== id)
        : [...selectedIds, id],
    );
  };

  const label = useMemo(() => {
    const count = readyDocuments.length;
    return count === 1 ? "1 ready document" : `${count} ready documents`;
  }, [readyDocuments.length]);

  return (
    <aside className="hidden w-72 shrink-0 flex-col border-r border-surface-variant bg-surface lg:flex">
      <div className="sticky top-0 border-b border-surface-variant bg-surface-container-lowest p-stack-md">
        <h2 className="font-display text-title-lg text-on-surface">Context Selection</h2>
        <p className="mt-1 text-body-sm text-on-surface-variant">{label}</p>
      </div>

      <div className="custom-scrollbar flex-1 space-y-2 overflow-y-auto p-stack-sm">
        {readyDocuments.length === 0 ? (
          <div className="flex flex-col items-center gap-2 px-3 py-10 text-center">
            <span className="material-symbols-outlined text-[48px] text-on-surface-variant">
              library_books
            </span>
            <p className="font-display text-label-md text-on-surface">No documents ready</p>
            <p className="text-body-sm text-on-surface-variant">
              Upload and index a PDF in the Documents space — only ready documents can be
              used as context.
            </p>
          </div>
        ) : (
          readyDocuments.map((document) => {
            const checked = selectedIds.includes(document.id);
            return (
              <label
                key={document.id}
                className="flex cursor-pointer items-start gap-3 rounded-lg border border-transparent p-3 transition-colors hover:border-surface-variant hover:bg-surface-container-low"
              >
                <div className="mt-0.5">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggle(document.id)}
                    aria-label={`Use ${document.filename}`}
                    className="h-4 w-4 rounded border-outline-variant text-secondary focus:ring-secondary/20"
                  />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="mb-1 flex items-center gap-2">
                    <span className="material-symbols-outlined text-[16px] text-secondary">
                      {fileIcon(document.filename)}
                    </span>
                    <span className="truncate font-display text-label-md text-on-surface">
                      {document.filename}
                    </span>
                  </div>
                  <p className="font-display text-label-sm text-on-surface-variant">
                    Uploaded · {formatBytes(document.file_size_bytes)}
                  </p>
                </div>
              </label>
            );
          })
        )}
      </div>
    </aside>
  );
}