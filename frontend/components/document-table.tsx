// Documents table (docs/frontend-design.md §3): border-less rows, 1px
// dividers, hover #F8FAFC, body-sm density, pagination footer. Failed rows
// show an always-visible Re-process action (failure is a moment for
// direction); delete is a separate icon revealed on hover with an inline
// confirm step.
"use client";

import { useMemo, useState } from "react";
import StatusBadge from "@/components/status-badge";
import type { Document } from "@/lib/api-client";
import { formatBytes, formatDate } from "@/lib/format";

const PAGE_SIZE = 8;

export default function DocumentTable({
  documents,
  onDelete,
  onReprocess,
  deletingId,
  reprocessingId,
}: {
  documents: Document[];
  onDelete: (id: string) => void;
  onReprocess: (id: string) => void;
  deletingId: string | null;
  reprocessingId: string | null;
}) {
  const [page, setPage] = useState(0);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(documents.length / PAGE_SIZE)),
    [documents.length],
  );
  const pageRows = useMemo(
    () => documents.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE),
    [documents, page],
  );

  return (
    <div className="rounded-xl border border-outline-variant bg-surface">
      <div className="overflow-x-auto">
        <table className="w-full text-body-sm text-on-surface">
          <thead>
            <tr className="border-b border-surface-variant text-left font-display text-label-sm uppercase tracking-wide text-on-surface-variant">
              <th className="px-6 py-3 font-medium">Name</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Size</th>
              <th className="px-4 py-3 font-medium">Uploaded</th>
              <th className="px-4 py-3 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((document) => (
              <tr
                key={document.id}
                className="group border-b border-surface-variant last:border-0 hover:bg-surface-container-low"
              >
                <td className="max-w-64 px-6 py-3">
                  <div className="flex items-center gap-2.5">
                    <span className="material-symbols-outlined shrink-0 text-sm text-on-surface-variant">
                      picture_as_pdf
                    </span>
                    <span className="truncate font-medium text-on-surface">{document.filename}</span>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={document.status} error={document.status_error} />
                </td>
                <td className="px-4 py-3 text-on-surface-variant">
                  {formatBytes(document.file_size_bytes)}
                </td>
                <td className="px-4 py-3 text-on-surface-variant">
                  {formatDate(document.created_at)}
                </td>
                <td className="px-4 py-3 text-right">
                  {confirmId === document.id ? (
                    <span className="inline-flex items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => onDelete(document.id)}
                        disabled={deletingId === document.id}
                        className="rounded-lg bg-error-container px-2.5 py-1 font-display text-label-sm text-error transition-colors hover:bg-error-container/70"
                      >
                        {deletingId === document.id ? "Deleting…" : "Confirm"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmId(null)}
                        className="rounded-lg px-2.5 py-1 font-display text-label-sm text-on-surface-variant hover:bg-surface-container-low"
                      >
                        Cancel
                      </button>
                    </span>
                  ) : (
                    <span className="inline-flex items-center justify-end gap-1">
                      {document.status === "failed" && (
                        <button
                          type="button"
                          title="Re-process document"
                          aria-label={`Re-process ${document.filename}`}
                          disabled={reprocessingId !== null}
                          onClick={() => onReprocess(document.id)}
                          className="inline-flex items-center gap-1 rounded-md px-2 py-1 font-display text-label-sm font-medium text-secondary transition-colors hover:bg-secondary/10 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          <span
                            className="material-symbols-outlined text-sm"
                            aria-hidden="true"
                          >
                            {reprocessingId === document.id ? "sync" : "replay"}
                          </span>
                          {reprocessingId === document.id
                            ? "Reprocessing…"
                            : "Re-process"}
                        </button>
                      )}
                      <button
                        type="button"
                        title="Delete document"
                        aria-label={`Delete ${document.filename}`}
                        disabled={reprocessingId === document.id}
                        onClick={() => setConfirmId(document.id)}
                        className="rounded-md p-1.5 text-on-surface-variant opacity-0 transition-all hover:bg-error-container/50 hover:text-error focus:opacity-100 group-hover:opacity-100 disabled:opacity-0"
                      >
                        <span className="material-symbols-outlined text-sm">delete</span>
                      </button>
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {documents.length > 0 && (
        <div className="flex items-center justify-between border-t border-surface-variant px-6 py-3 font-display text-label-sm text-on-surface-variant">
          <span>
            {documents.length} file{documents.length === 1 ? "" : "s"}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              className="rounded-lg px-2 py-1 transition-colors hover:bg-surface-container-low disabled:opacity-40"
            >
              Previous
            </button>
            <span>
              Page {page + 1} of {totalPages}
            </span>
            <button
              type="button"
              disabled={page + 1 >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              className="rounded-lg px-2 py-1 transition-colors hover:bg-surface-container-low disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}