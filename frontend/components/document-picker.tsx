// Add-documents picker (docs/frontend-design.md §4): modal listing ready docs
// not yet in the conversation; "Add (n)" merges the checked rows in.
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Document } from "@/lib/api-client";
import { fileIcon, formatBytes } from "@/lib/format";

interface DocumentPickerProps {
  readyDocuments: Document[];
  selectedIds: string[];
  onAdd: (ids: string[]) => void;
  onClose: () => void;
}

export default function DocumentPicker({
  readyDocuments,
  selectedIds,
  onAdd,
  onClose,
}: DocumentPickerProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [pending, setPending] = useState<string[]>([]);

  const trimmed = query.trim().toLowerCase();

  const candidates = useMemo(
    () => readyDocuments.filter((doc) => !selectedIds.includes(doc.id)),
    [readyDocuments, selectedIds],
  );
  const matches = useMemo(
    () =>
      trimmed
        ? candidates.filter((doc) => doc.filename.toLowerCase().includes(trimmed))
        : candidates,
    [candidates, trimmed],
  );

  const toggle = (id: string) => {
    setPending((current) =>
      current.includes(id) ? current.filter((x) => x !== id) : [...current, id],
    );
  };
  const allVisibleChecked =
    matches.length > 0 && matches.every((doc) => pending.includes(doc.id));
  const toggleAll = () => {
    if (matches.length === 0) return;
    setPending((current) => {
      const ids = matches.map((doc) => doc.id);
      return allVisibleChecked
        ? current.filter((id) => !ids.includes(id))
        : Array.from(new Set([...current, ...ids]));
    });
  };

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const showNoMatch = candidates.length > 0 && matches.length === 0 && trimmed !== "";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Add documents"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
    >
      <div
        className="fade-in absolute inset-0 bg-black/40"
        onClick={onClose}
        aria-hidden="true"
      />
      <div className="dialog-in relative flex max-h-[min(560px,calc(100vh_-_32px))] w-[min(480px,calc(100vw_-_32px))] flex-col overflow-hidden rounded-2xl border border-surface-variant bg-surface-container-lowest shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
        <div className="flex items-start justify-between gap-2 px-5 pb-3 pt-4">
          <div className="min-w-0">
            <h2 className="font-display text-title-lg text-on-surface">Add documents</h2>
            <p className="mt-0.5 text-body-sm text-on-surface-variant">
              {candidates.length === 0
                ? "All ready documents are already in this conversation"
                : `${candidates.length} ready document${candidates.length === 1 ? "" : "s"} available`}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close add documents"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-on-surface-variant transition-colors hover:bg-surface-container hover:text-on-surface"
          >
            <span className="material-symbols-outlined text-[20px]" aria-hidden="true">
              close
            </span>
          </button>
        </div>

        <div className="flex flex-col gap-2 px-5 pb-3">
          <div className="relative">
            <span
              className="material-symbols-outlined pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[18px] text-on-surface-variant"
              aria-hidden="true"
            >
              search
            </span>
            <input
              ref={inputRef}
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
          <button
            type="button"
            onClick={toggleAll}
            disabled={matches.length === 0}
            className="self-start font-display text-label-sm font-medium text-secondary transition-colors enabled:hover:text-on-secondary-fixed-variant disabled:opacity-50"
          >
            {allVisibleChecked ? "Deselect all" : "Select all"}
          </button>
        </div>

        <div className="custom-scrollbar flex-1 space-y-2 overflow-y-auto border-t border-surface-variant p-3">
          {candidates.length === 0 ? (
            <div className="flex flex-col items-center gap-2 px-3 py-8 text-center">
              <span className="material-symbols-outlined text-[40px] text-on-surface-variant">
                task_alt
              </span>
              <p className="font-display text-label-md text-on-surface">
                Everything is already included
              </p>
              <p className="text-body-sm text-on-surface-variant">
                Use the context panel or the chips above the input to remove documents.
              </p>
            </div>
          ) : showNoMatch ? (
            <div className="flex flex-col items-center gap-2 px-3 py-8 text-center">
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
          ) : (
            matches.map((document) => {
              const checked = pending.includes(document.id);
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
                      aria-label={`Add ${document.filename}`}
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

        <div className="flex items-center justify-end gap-2 border-t border-surface-variant px-4 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-4 py-2 font-display text-label-md text-on-surface-variant transition-colors hover:bg-surface-container hover:text-on-surface"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={pending.length === 0}
            onClick={() => onAdd(pending)}
            className="flex items-center justify-center rounded-lg bg-secondary px-4 py-2 font-display text-label-md text-white shadow-sm transition-colors enabled:hover:bg-secondary/90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Add{pending.length > 0 ? ` (${pending.length})` : ""}
          </button>
        </div>
      </div>
    </div>
  );
}
