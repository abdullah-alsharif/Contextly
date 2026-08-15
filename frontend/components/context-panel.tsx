// Context panel — chat left rail (docs/frontend-design.md §4): search,
// All/Selected filter, Select/Deselect all, checkbox rows over every ready
// document account-wide.
"use client";

import { useMemo, useState } from "react";
import type { Document } from "@/lib/api-client";
import { fileIcon, formatBytes } from "@/lib/format";

export default function ContextPanel({
  readyDocuments,
  selectedIds,
  setSelectedIds,
  defaultSelectedOnly = false,
}: {
  readyDocuments: Document[];
  selectedIds: string[];
  setSelectedIds: (ids: string[]) => void;
  defaultSelectedOnly?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [selectedOnly, setSelectedOnly] = useState(defaultSelectedOnly);

  const trimmed = query.trim().toLowerCase();

  const matches = useMemo(
    () =>
      trimmed
        ? readyDocuments.filter((doc) => doc.filename.toLowerCase().includes(trimmed))
        : readyDocuments,
    [readyDocuments, trimmed],
  );
  const visible = useMemo(
    () => (selectedOnly ? matches.filter((doc) => selectedIds.includes(doc.id)) : matches),
    [matches, selectedOnly, selectedIds],
  );

  const visibleIds = useMemo(() => visible.map((doc) => doc.id), [visible]);
  const allVisibleSelected =
    visibleIds.length > 0 && visibleIds.every((id) => selectedIds.includes(id));

  const toggle = (id: string) => {
    setSelectedIds(
      selectedIds.includes(id)
        ? selectedIds.filter((selected) => selected !== id)
        : [...selectedIds, id],
    );
  };

  const toggleAll = () => {
    if (visibleIds.length === 0) return;
    setSelectedIds(
      allVisibleSelected
        ? selectedIds.filter((id) => !visibleIds.includes(id))
        : Array.from(new Set([...selectedIds, ...visibleIds])),
    );
  };

  const countLabel =
    readyDocuments.length === 0
      ? "No ready documents"
      : `${selectedIds.length} of ${readyDocuments.length} selected`;
  const showNoMatch = readyDocuments.length > 0 && visible.length === 0 && trimmed !== "";
  const showNothingSelected =
    readyDocuments.length > 0 && visible.length === 0 && !trimmed && selectedOnly;

  return (
    <aside className="hidden w-72 shrink-0 flex-col border-r border-surface-variant bg-surface lg:flex">
      <div className="sticky top-0 z-10 flex flex-col gap-2 border-b border-surface-variant bg-surface-container-lowest p-stack-md">
        <h2 className="font-display text-title-lg text-on-surface">Context Selection</h2>
        <p aria-live="polite" className="text-body-sm text-on-surface-variant">
          {countLabel}
        </p>

        <div className="relative">
          <span
            className="material-symbols-outlined pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[18px] text-on-surface-variant"
            aria-hidden="true"
          >
            search
          </span>
          <input
            type="text"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") setQuery("");
            }}
            placeholder="Search documents"
            aria-label="Search documents"
            className="h-9 w-full rounded-lg border border-outline-variant bg-surface-container-low pl-8 pr-8 text-body-sm text-on-surface outline-none transition-colors placeholder:text-on-surface-variant/70 focus:border-secondary focus:ring-2 focus:ring-secondary/20"
          />
          {query !== "" && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="Clear search"
              className="absolute right-1 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-on-surface-variant transition-colors hover:bg-surface-container-high hover:text-on-surface"
            >
              <span className="material-symbols-outlined text-[16px]" aria-hidden="true">
                close
              </span>
            </button>
          )}
        </div>

        <div className="flex items-center justify-between gap-2">
          <div
            role="group"
            aria-label="Filter context documents"
            className="flex rounded-lg bg-surface-container-low p-0.5"
          >
            <button
              type="button"
              aria-pressed={!selectedOnly}
              onClick={() => setSelectedOnly(false)}
              className={`rounded-md px-2.5 py-1 font-display text-label-sm transition-colors ${
                !selectedOnly
                  ? "bg-white text-on-surface shadow-sm"
                  : "text-on-surface-variant hover:text-on-surface"
              }`}
            >
              All
            </button>
            <button
              type="button"
              aria-pressed={selectedOnly}
              onClick={() => setSelectedOnly(true)}
              className={`rounded-md px-2.5 py-1 font-display text-label-sm transition-colors ${
                selectedOnly
                  ? "bg-white text-on-surface shadow-sm"
                  : "text-on-surface-variant hover:text-on-surface"
              }`}
            >
              Selected
            </button>
          </div>
          <button
            type="button"
            onClick={toggleAll}
            disabled={visibleIds.length === 0}
            className="font-display text-label-sm font-medium text-secondary transition-colors enabled:hover:text-on-secondary-fixed-variant disabled:opacity-50"
          >
            {allVisibleSelected ? "Deselect all" : "Select all"}
          </button>
        </div>
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
        ) : showNoMatch ? (
          <div className="flex flex-col items-center gap-2 px-3 py-10 text-center">
            <span className="material-symbols-outlined text-[40px] text-on-surface-variant">
              search_off
            </span>
            <p className="font-display text-label-md text-on-surface">No matches</p>
            <p className="text-body-sm text-on-surface-variant">
              No documents match &quot;{query}&quot;.
            </p>
            <button
              type="button"
              onClick={() => setQuery("")}
              className="font-display text-label-sm font-medium text-secondary transition-colors hover:text-on-secondary-fixed-variant"
            >
              Clear search
            </button>
          </div>
        ) : showNothingSelected ? (
          <div className="flex flex-col items-center gap-2 px-3 py-10 text-center">
            <span className="material-symbols-outlined text-[40px] text-on-surface-variant">
              check_box_outline_blank
            </span>
            <p className="font-display text-label-md text-on-surface">Nothing selected</p>
            <p className="text-body-sm text-on-surface-variant">
              Pick documents to use as context, or select them all.
            </p>
            <button
              type="button"
              onClick={() => setSelectedIds(readyDocuments.map((doc) => doc.id))}
              className="font-display text-label-sm font-medium text-secondary transition-colors hover:text-on-secondary-fixed-variant"
            >
              Select all documents
            </button>
          </div>
        ) : (
          visible.map((document) => {
            const checked = selectedIds.includes(document.id);
            return (
              <label
                key={document.id}
                className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
                  checked
                    ? "border-secondary-fixed-dim bg-secondary-fixed/50 hover:bg-secondary-fixed/70"
                    : "border-transparent hover:border-surface-variant hover:bg-surface-container-low"
                }`}
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
