// Documents table (docs/frontend-design.md §3): search + status filter
// toolbar, paginated rows. Queued/processing rows show Cancel (worker aborts
// in-flight); failed/cancelled rows show Re-process; delete is hover-revealed
// with an inline confirm.
"use client";

import { useMemo, useState } from "react";
import StatusBadge, { STATUS_LABELS } from "@/components/status-badge";
import type { Document, DocumentStatus } from "@/lib/api-client";
import { formatBytes, formatDate } from "@/lib/format";

const PAGE_SIZE = 8;

const STATUS_FILTERS: { value: DocumentStatus | "all"; label: string }[] = [
  { value: "all", label: "All Statuses" },
  ...(Object.keys(STATUS_LABELS) as DocumentStatus[])
    .filter((status) => status !== "deleted")
    .map((status) => ({ value: status, label: STATUS_LABELS[status] })),
];

export default function DocumentTable({
  documents,
  onDelete,
  onReprocess,
  onCancel,
  deletingId,
  reprocessingId,
  cancellingId,
}: {
  documents: Document[];
  onDelete: (id: string) => void;
  onReprocess: (id: string) => void;
  onCancel: (id: string) => void;
  deletingId: string | null;
  reprocessingId: string | null;
  cancellingId: string | null;
}) {
  const [page, setPage] = useState(0);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<DocumentStatus | "all">("all");

  const filteredRows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return documents.filter(
      (d) =>
        (statusFilter === "all" || d.status === statusFilter) &&
        (q === "" || d.filename.toLowerCase().includes(q)),
    );
  }, [documents, query, statusFilter]);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE)),
    [filteredRows.length],
  );
  const pageRows = useMemo(
    () => filteredRows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE),
    [filteredRows, page],
  );

  return (
    <div className="rounded-xl border border-outline-variant bg-surface">
      <div className="flex flex-col gap-3 border-b border-surface-variant px-6 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full sm:max-w-sm">
          <span
            className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-sm text-on-surface-variant"
            aria-hidden="true"
          >
            search
          </span>
          <input
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(0);
            }}
            placeholder="Search files by name…"
            aria-label="Search files by name"
            className="w-full rounded-lg border border-outline-variant bg-surface-container-low py-2 pl-10 pr-4 text-body-sm text-on-surface transition-all placeholder:text-on-surface-variant focus:border-secondary focus:outline-none focus:ring-2 focus:ring-secondary/20"
          />
        </div>
        <div className="relative">
          <span
            className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-sm text-on-surface-variant"
            aria-hidden="true"
          >
            filter_list
          </span>
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value as DocumentStatus | "all");
              setPage(0);
            }}
            aria-label="Filter by status"
            className="appearance-none rounded-lg border border-outline-variant bg-surface py-1.5 pl-9 pr-8 font-display text-label-sm text-on-surface focus:border-secondary focus:outline-none focus:ring-1 focus:ring-secondary"
          >
            {STATUS_FILTERS.map((filter) => (
              <option key={filter.value} value={filter.value}>
                {filter.label}
              </option>
            ))}
          </select>
        </div>
      </div>
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
            {pageRows.length === 0 ? (
              <tr>
                <td
                  colSpan={5}
                  className="px-6 py-8 text-center text-body-sm text-on-surface-variant"
                >
                  No files match your search or filters.
                </td>
              </tr>
            ) : (
              pageRows.map((document) => (
                <tr
                  key={document.id}
                  className="border-b border-surface-variant last:border-0 hover:bg-surface-container-low"
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
                        {(document.status === "uploaded" ||
                          document.status === "processing") && (
                          <button
                            type="button"
                            title="Cancel processing"
                            aria-label={`Cancel processing ${document.filename}`}
                            disabled={
                              cancellingId !== null ||
                              reprocessingId === document.id ||
                              deletingId === document.id
                            }
                            onClick={() => onCancel(document.id)}
                            className="inline-flex items-center gap-1 rounded-md px-2 py-1 font-display text-label-sm font-medium text-on-surface-variant transition-colors hover:bg-surface-container-high disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            <span
                              className="material-symbols-outlined text-[10px]"
                              aria-hidden="true"
                            >
                              {cancellingId === document.id ? "sync" : "cancel"}
                            </span>
                            {cancellingId === document.id ? "Stopping…" : "Cancel"}
                          </button>
                        )}
                        {(document.status === "failed" ||
                          document.status === "cancelled") && (
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
                          disabled={
                            reprocessingId === document.id ||
                            cancellingId === document.id
                          }
                          onClick={() => setConfirmId(document.id)}
                          className="rounded-md p-1.5 text-on-surface-variant transition-colors hover:bg-error-container/50 hover:text-error disabled:opacity-0"
                        >
                          <span
                            className="material-symbols-outlined fill text-sm"
                            aria-hidden="true"
                          >
                            delete
                          </span>
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              )))}
          </tbody>
        </table>
      </div>
      {documents.length > 0 && (
        <div className="flex items-center justify-between border-t border-surface-variant px-6 py-3 font-display text-label-sm text-on-surface-variant">
          <span>
            {filteredRows.length}
            {filteredRows.length !== documents.length &&
              ` of ${documents.length}`}{" "}
            file{filteredRows.length === 1 ? "" : "s"}
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
