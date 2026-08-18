// Documents table (docs/frontend-design.md §3): search + status filter
// toolbar, paginated rows, per-status actions. Mobile: stacked cards; md+.
"use client";

import { useMemo, useState, type ReactNode } from "react";
import StatusBadge, { STATUS_LABELS } from "@/components/status-badge";
import type { Document, DocumentStatus } from "@/lib/api-client";
import { formatBytes, formatDate } from "@/lib/format";

const PAGE_SIZE = 8;

const STATUS_FILTERS: { value: DocumentStatus | "all"; label: string }[] = [
  { value: "all", label: "All" },
  ...(Object.keys(STATUS_LABELS) as DocumentStatus[])
    .filter((status) => status !== "deleted")
    .map((status) => ({ value: status, label: STATUS_LABELS[status] })),
];

function RowActions({
  document,
  confirmId,
  onConfirm,
  onCancelConfirm,
  onDelete,
  onReprocess,
  onCancel,
  deletingId,
  reprocessingId,
  cancellingId,
  className,
}: {
  document: Document;
  confirmId: string | null;
  onConfirm: (id: string) => void;
  onCancelConfirm: () => void;
  onDelete: (id: string) => void;
  onReprocess: (id: string) => void;
  onCancel: (id: string) => void;
  deletingId: string | null;
  reprocessingId: string | null;
  cancellingId: string | null;
  className?: string;
}) {
  if (confirmId === document.id) {
    return (
      <span className={`inline-flex items-center gap-1.5 ${className ?? ""}`}>
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
          onClick={onCancelConfirm}
          className="rounded-lg px-2.5 py-1 font-display text-label-sm text-on-surface-variant hover:bg-surface-container-low"
        >
          Cancel
        </button>
      </span>
    );
  }

  return (
    <span className={`inline-flex items-center justify-end gap-1 ${className ?? ""}`}>
      {(document.status === "uploaded" || document.status === "processing") && (
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
          <span className="material-symbols-outlined text-[10px]" aria-hidden="true">
            {cancellingId === document.id ? "sync" : "cancel"}
          </span>
          {cancellingId === document.id ? "Stopping…" : "Cancel"}
        </button>
      )}
      {(document.status === "failed" || document.status === "cancelled") && (
        <button
          type="button"
          title="Re-process document"
          aria-label={`Re-process ${document.filename}`}
          disabled={reprocessingId !== null}
          onClick={() => onReprocess(document.id)}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 font-display text-label-sm font-medium text-secondary transition-colors hover:bg-secondary/10 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <span className="material-symbols-outlined text-sm" aria-hidden="true">
            {reprocessingId === document.id ? "sync" : "replay"}
          </span>
          {reprocessingId === document.id ? "Reprocessing…" : "Re-process"}
        </button>
      )}
      <button
        type="button"
        title="Delete document"
        aria-label={`Delete ${document.filename}`}
        disabled={reprocessingId === document.id || cancellingId === document.id}
        onClick={() => onConfirm(document.id)}
        className="rounded-md p-1.5 text-on-surface-variant transition-colors hover:bg-error-container/50 hover:text-error disabled:opacity-0"
      >
        <span className="material-symbols-outlined fill text-sm" aria-hidden="true">
          delete
        </span>
      </button>
    </span>
  );
}

// Mobile: stacked cards with touch-sized actions (40px delete on the meta
// line; full-width Cancel/Re-process only when the row has something to do).
function DocumentCard({
  document,
  confirmId,
  onConfirm,
  onCancelConfirm,
  onDelete,
  onReprocess,
  onCancel,
  deletingId,
  reprocessingId,
  cancellingId,
}: {
  document: Document;
  confirmId: string | null;
  onConfirm: (id: string) => void;
  onCancelConfirm: () => void;
  onDelete: (id: string) => void;
  onReprocess: (id: string) => void;
  onCancel: (id: string) => void;
  deletingId: string | null;
  reprocessingId: string | null;
  cancellingId: string | null;
}) {
  const showCancel =
    document.status === "uploaded" || document.status === "processing";
  const showReprocess =
    document.status === "failed" || document.status === "cancelled";

  return (
    <div className="border-b border-surface-variant p-4 last:border-0">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="material-symbols-outlined shrink-0 text-base text-on-surface-variant">
            picture_as_pdf
          </span>
          <span className="truncate text-body-sm font-medium text-on-surface">
            {document.filename}
          </span>
        </div>
        <StatusBadge status={document.status} error={document.status_error} />
      </div>
      {confirmId === document.id ? (
        <div className="mt-3 flex items-center gap-2 border-t border-surface-variant/70 pt-3">
          <button
            type="button"
            onClick={() => onDelete(document.id)}
            disabled={deletingId === document.id}
            className="h-10 rounded-lg bg-error-container px-4 font-display text-label-sm text-error transition-colors hover:bg-error-container/70"
          >
            {deletingId === document.id ? "Deleting…" : "Confirm delete"}
          </button>
          <button
            type="button"
            onClick={onCancelConfirm}
            className="h-10 rounded-lg px-4 font-display text-label-sm text-on-surface-variant hover:bg-surface-container-low"
          >
            Cancel
          </button>
        </div>
      ) : (
        <>
          <div className="mt-2 flex items-center gap-2 pl-7 text-label-sm text-on-surface-variant">
            <span>{formatBytes(document.file_size_bytes)}</span>
            <span aria-hidden="true" className="text-on-surface-variant/60">·</span>
            <span>Uploaded {formatDate(document.created_at)}</span>
            <button
              type="button"
              onClick={() => onConfirm(document.id)}
              disabled={reprocessingId === document.id || cancellingId === document.id}
              aria-label={`Delete ${document.filename}`}
              className="ml-auto flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-outline-variant text-on-surface-variant transition-colors hover:bg-error-container/40 hover:text-error disabled:opacity-50"
            >
              <span className="material-symbols-outlined fill text-base" aria-hidden="true">
                delete
              </span>
            </button>
          </div>
          {(showCancel || showReprocess) && (
            <div className="mt-3 border-t border-surface-variant/70 pt-3">
              {showCancel && (
                <button
                  type="button"
                  onClick={() => onCancel(document.id)}
                  disabled={cancellingId !== null}
                  aria-label={`Cancel processing ${document.filename}`}
                  className="flex h-10 w-full items-center justify-center gap-1.5 rounded-lg border border-outline-variant font-display text-label-sm font-medium text-on-surface transition-colors hover:bg-surface-container-low disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-base" aria-hidden="true">
                    {cancellingId === document.id ? "sync" : "cancel"}
                  </span>
                  {cancellingId === document.id ? "Stopping…" : "Cancel"}
                </button>
              )}
              {showReprocess && (
                <button
                  type="button"
                  onClick={() => onReprocess(document.id)}
                  disabled={reprocessingId !== null}
                  aria-label={`Re-process ${document.filename}`}
                  className="flex h-10 w-full items-center justify-center gap-1.5 rounded-lg bg-secondary/10 font-display text-label-sm font-medium text-secondary transition-colors hover:bg-secondary/15 disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-base" aria-hidden="true">
                    {reprocessingId === document.id ? "sync" : "replay"}
                  </span>
                  {reprocessingId === document.id ? "Reprocessing…" : "Re-process"}
                </button>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

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

  const statusCounts = useMemo(() => {
    const counts = new Map<DocumentStatus | "all", number>();
    counts.set("all", documents.length);
    for (const d of documents) {
      counts.set(d.status, (counts.get(d.status) ?? 0) + 1);
    }
    return counts;
  }, [documents]);

  const actionsProps = {
    confirmId,
    onConfirm: (id: string) => setConfirmId(id),
    onCancelConfirm: () => setConfirmId(null),
    onDelete,
    onReprocess,
    onCancel,
    deletingId,
    reprocessingId,
    cancellingId,
  };

  const emptyRow: ReactNode =
    pageRows.length === 0 ? (
      <p className="px-6 py-8 text-center text-body-sm text-on-surface-variant">
        No files match your search or filters.
      </p>
    ) : null;

  return (
    <div className="rounded-xl border border-outline-variant bg-surface">
      <div className="flex flex-col gap-3 border-b border-surface-variant px-6 py-4">
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
        <div
          role="group"
          aria-label="Filter by status"
          className="-mx-6 flex items-center gap-2 overflow-x-auto px-6 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0"
        >
          {STATUS_FILTERS.map((filter) => {
            const count = statusCounts.get(filter.value) ?? 0;
            const active = statusFilter === filter.value;
            return (
              <button
                key={filter.value}
                type="button"
                aria-pressed={active}
                onClick={() => {
                  setStatusFilter(filter.value);
                  setPage(0);
                }}
                className={`inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3 font-display text-label-sm transition-colors ${
                  active
                    ? "bg-secondary text-on-secondary"
                    : "bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface"
                }`}
              >
                {filter.label}{" "}
                {count > 0 && (
                  <span
                    className={active ? "text-on-secondary/70" : "text-on-surface-variant/60"}
                  >
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Mobile: stacked cards */}
      <div className="md:hidden">
        {emptyRow}
        {pageRows.map((document) => (
          <DocumentCard key={document.id} document={document} {...actionsProps} />
        ))}
      </div>

      {/* md+: table */}
      <div className="hidden overflow-x-auto md:block">
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
                    <RowActions document={document} {...actionsProps} />
                  </td>
                </tr>
              ))
            )}
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
