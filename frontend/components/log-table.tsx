// Activity log table (specs/016 US2/US3): action-type chips + date-range
// inputs, newest-first rows with outcome pill and inline failure reason,
// one-at-a-time Details expansion, "Load more" footer. Container mirrors
// `document-table` (rounded-xl border, hover rows).
"use client";

import { useState, type ReactNode } from "react";
import type { ActionType, LogEntry } from "@/lib/api-client";
import { formatDateTime } from "@/lib/format";
import type { LogFilters } from "@/lib/hooks/use-logs";

export const ACTION_LABELS: Record<ActionType, string> = {
  upload: "Uploaded",
  replace: "Replaced",
  delete: "Deleted",
  cancel: "Cancelled",
  reprocess: "Re-processed",
  superseded: "Superseded",
  restored: "Restored",
  processing_started: "Processing started",
  processing_succeeded: "Processing complete",
  processing_failed: "Processing failed",
};

const ACTION_CHIPS: { value: ActionType; label: string }[] = [
  { value: "upload", label: "Upload" },
  { value: "replace", label: "Replace" },
  { value: "delete", label: "Delete" },
  { value: "cancel", label: "Cancel" },
  { value: "reprocess", label: "Re-process" },
  { value: "superseded", label: "Superseded" },
  { value: "restored", label: "Restored" },
  { value: "processing_started", label: "Started" },
  { value: "processing_succeeded", label: "Succeeded" },
  { value: "processing_failed", label: "Failed" },
];

/** Local YYYY-MM-DD → UTC start/end instant for the API (FR-013). */
function toFromIso(date: string): string {
  return new Date(`${date}T00:00:00`).toISOString();
}
function toToIso(date: string): string {
  return new Date(`${date}T23:59:59.999`).toISOString();
}

/** UTC ISO instant → local YYYY-MM-DD for a date input value. */
function toDateInput(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

function OutcomePill({ outcome }: { outcome: "succeeded" | "failed" }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 font-display text-label-sm font-medium ${
        outcome === "failed"
          ? "bg-error-container text-error"
          : "bg-secondary-fixed text-on-secondary-fixed-variant"
      }`}
    >
      {outcome === "failed" && (
        <span className="material-symbols-outlined text-sm" aria-hidden="true">
          error
        </span>
      )}
      {outcome === "failed" ? "Failed" : "Succeeded"}
    </span>
  );
}

function EntryRow({
  entry,
  expanded,
  onToggle,
}: {
  entry: LogEntry;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr className="border-b border-surface-variant last:border-0 hover:bg-surface-container-low">
        <td className="max-w-56 px-6 py-3">
          <div className="flex items-center gap-2.5">
            <span className="material-symbols-outlined shrink-0 text-sm text-on-surface-variant" aria-hidden="true">
              {entry.action_type === "delete" || entry.action_type === "processing_failed"
                ? "report"
                : "history"}
            </span>
            <span className="truncate font-medium text-on-surface">
              {ACTION_LABELS[entry.action_type]}
            </span>
          </div>
          {entry.error_message && (
            <p className="mt-0.5 truncate pl-7 text-label-sm text-error">
              {entry.error_message}
            </p>
          )}
        </td>
        <td className="max-w-48 px-4 py-3">
          <span className="truncate text-on-surface-variant">{entry.filename}</span>
        </td>
        <td className="px-4 py-3">
          <OutcomePill outcome={entry.outcome} />
        </td>
        <td className="px-4 py-3 text-on-surface-variant">
          {formatDateTime(entry.created_at)}
        </td>
        <td className="px-4 py-3 text-right">
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={expanded}
            aria-controls={`log-entry-details-${entry.id}`}
            aria-label={`${expanded ? "Hide" : "Show"} details for ${entry.filename}`}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-on-surface-variant transition-colors hover:bg-surface-container-high hover:text-on-surface"
          >
            <span className="material-symbols-outlined text-base" aria-hidden="true">
              {expanded ? "expand_less" : "expand_more"}
            </span>
          </button>
        </td>
      </tr>
      {expanded && (
        <tr
          id={`log-entry-details-${entry.id}`}
          className="border-b border-surface-variant bg-surface-container-low last:border-0"
        >
          <td colSpan={5} className="px-6 py-4">
            <DetailsPane entry={entry} />
          </td>
        </tr>
      )}
    </>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function DetailsPane({ entry }: { entry: LogEntry }) {
  const metaLines: { label: string; value: string }[] = [];
  const { retry_count, total_chunks, file_size } = entry.metadata;
  if (typeof retry_count === "number")
    metaLines.push({ label: "Retries", value: String(retry_count) });
  if (typeof total_chunks === "number")
    metaLines.push({ label: "Chunks", value: String(total_chunks) });
  if (typeof file_size === "number")
    metaLines.push({ label: "Size", value: formatBytes(file_size) });
  if (entry.document_id)
    metaLines.push({ label: "Document", value: entry.document_id.slice(0, 8) });

  return (
    <div className="grid max-w-3xl gap-3">
      {entry.error_message && (
        <div>
          <p className="font-display text-label-sm text-on-surface-variant">Error</p>
          <p className="mt-1 text-body-sm text-error">{entry.error_message}</p>
        </div>
      )}
      {entry.error_trace && (
        <div>
          <p className="font-display text-label-sm text-on-surface-variant">
            Stack trace
          </p>
          <pre className="mt-1 max-h-48 overflow-y-auto rounded-lg border border-outline-variant bg-surface px-3 py-2 font-mono text-xs leading-relaxed text-on-surface">
            {entry.error_trace}
          </pre>
        </div>
      )}
      {metaLines.length > 0 && (
        <dl className="flex flex-wrap gap-x-6 gap-y-1">
          {metaLines.map((line) => (
            <div key={line.label} className="flex items-baseline gap-2">
              <dt className="font-display text-label-sm text-on-surface-variant">
                {line.label}
              </dt>
              <dd className="text-label-sm text-on-surface">{line.value}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

export default function LogTable({
  entries,
  loadingMore,
  hasMore,
  onLoadMore,
  filters,
  onFiltersChange,
  emptyContent,
}: {
  entries: LogEntry[];
  loadingMore: boolean;
  hasMore: boolean;
  onLoadMore: () => void;
  filters: LogFilters;
  onFiltersChange: (filters: LogFilters) => void;
  /** Rendered in the list area when there are no rows (toolbar stays). */
  emptyContent?: ReactNode;
}) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const toggle = (id: string) =>
    setExpandedId((current) => (current === id ? null : id));

  const emptyRow: ReactNode =
    entries.length === 0 ? (
      <p className="px-6 py-8 text-center text-body-sm text-on-surface-variant">
        Nothing here yet.
      </p>
    ) : null;

  return (
    <div className="rounded-xl border border-outline-variant bg-surface">
      <div className="flex flex-col gap-3 border-b border-surface-variant px-6 py-4">
        <div
          role="group"
          aria-label="Filter by action"
          className="-mx-6 flex items-center gap-2 overflow-x-auto px-6 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0"
        >
          <button
            type="button"
            aria-pressed={!filters.action_type}
            onClick={() => onFiltersChange({ ...filters, action_type: undefined })}
            className={`inline-flex h-8 shrink-0 items-center rounded-full px-3 font-display text-label-sm transition-colors ${
              !filters.action_type
                ? "bg-secondary text-on-secondary"
                : "bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface"
            }`}
          >
            All
          </button>
          {ACTION_CHIPS.map((chip) => {
            const active = filters.action_type === chip.value;
            return (
              <button
                key={chip.value}
                type="button"
                aria-pressed={active}
                onClick={() =>
                  onFiltersChange({
                    ...filters,
                    action_type: active ? undefined : chip.value,
                  })
                }
                className={`inline-flex h-8 shrink-0 items-center rounded-full px-3 font-display text-label-sm transition-colors ${
                  active
                    ? "bg-secondary text-on-secondary"
                    : "bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface"
                }`}
              >
                {chip.label}
              </button>
            );
          })}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 font-display text-label-sm text-on-surface-variant">
            From
            <input
              type="date"
              value={toDateInput(filters.from)}
              max={toDateInput(filters.to) || undefined}
              onChange={(e) =>
                onFiltersChange({
                  ...filters,
                  from: e.target.value ? toFromIso(e.target.value) : undefined,
                })
              }
              className="rounded-lg border border-outline-variant bg-surface-container-low px-2.5 py-1.5 font-display text-label-sm text-on-surface transition-all focus:border-secondary focus:outline-none focus:ring-2 focus:ring-secondary/20"
            />
          </label>
          <label className="flex items-center gap-2 font-display text-label-sm text-on-surface-variant">
            To
            <input
              type="date"
              value={toDateInput(filters.to)}
              min={toDateInput(filters.from) || undefined}
              onChange={(e) =>
                onFiltersChange({
                  ...filters,
                  to: e.target.value ? toToIso(e.target.value) : undefined,
                })
              }
              className="rounded-lg border border-outline-variant bg-surface-container-low px-2.5 py-1.5 font-display text-label-sm text-on-surface transition-all focus:border-secondary focus:outline-none focus:ring-2 focus:ring-secondary/20"
            />
          </label>
          {(filters.action_type || filters.from || filters.to) && (
            <button
              type="button"
              onClick={() => onFiltersChange({})}
              className="ml-auto rounded-lg px-2.5 py-1.5 font-display text-label-sm text-secondary transition-colors hover:bg-secondary/10"
            >
              Clear filters
            </button>
          )}
        </div>
      </div>

      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-body-sm text-on-surface">
          <thead>
            <tr className="border-b border-surface-variant text-left font-display text-label-sm uppercase tracking-wide text-on-surface-variant">
              <th className="px-6 py-3 font-medium">Action</th>
              <th className="px-4 py-3 font-medium">File</th>
              <th className="px-4 py-3 font-medium">Outcome</th>
              <th className="px-4 py-3 font-medium">When</th>
              <th className="px-4 py-3 text-right font-medium">Details</th>
            </tr>
          </thead>
          <tbody>
            {entries.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-6 py-8 text-center text-body-sm text-on-surface-variant">
                  {emptyContent ?? "Nothing here yet."}
                </td>
              </tr>
            ) : (
              entries.map((entry) => (
                <EntryRow
                  key={entry.id}
                  entry={entry}
                  expanded={expandedId === entry.id}
                  onToggle={() => toggle(entry.id)}
                />
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="md:hidden">
        {entries.length === 0 ? (emptyContent ?? emptyRow) : null}
        {entries.map((entry) => (
          <div key={entry.id} className="border-b border-surface-variant p-4 last:border-0">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-body-sm font-medium text-on-surface">
                  {ACTION_LABELS[entry.action_type]}
                </p>
                <p className="mt-0.5 truncate text-label-sm text-on-surface-variant">
                  {entry.filename}
                </p>
                {entry.error_message && (
                  <p className="mt-1 text-label-sm text-error">{entry.error_message}</p>
                )}
              </div>
              <OutcomePill outcome={entry.outcome} />
            </div>
            <div className="mt-2 flex items-center justify-between gap-2">
              <p className="text-label-sm text-on-surface-variant">
                {formatDateTime(entry.created_at)}
              </p>
              <button
                type="button"
                onClick={() => toggle(entry.id)}
                aria-expanded={expandedId === entry.id}
                aria-controls={`log-entry-details-${entry.id}`}
                aria-label={`${expandedId === entry.id ? "Hide" : "Show"} details for ${entry.filename}`}
                className="inline-flex h-8 items-center gap-1 rounded-lg px-2 font-display text-label-sm text-secondary transition-colors hover:bg-secondary/10"
              >
                <span className="material-symbols-outlined text-base" aria-hidden="true">
                  {expandedId === entry.id ? "expand_less" : "expand_more"}
                </span>
                {expandedId === entry.id ? "Hide details" : "Details"}
              </button>
            </div>
            {expandedId === entry.id && (
              <div id={`log-entry-details-${entry.id}`} className="mt-3 rounded-lg bg-surface-container-low p-3">
                <DetailsPane entry={entry} />
              </div>
            )}
          </div>
        ))}
      </div>

      {hasMore && (
        <div className="flex justify-center border-t border-surface-variant px-6 py-3">
          <button
            type="button"
            onClick={onLoadMore}
            disabled={loadingMore}
            className="inline-flex h-9 items-center gap-2 rounded-lg px-4 font-display text-label-sm text-secondary transition-colors hover:bg-secondary/10 disabled:opacity-50"
          >
            <span
              className={`material-symbols-outlined text-base ${loadingMore ? "animate-spin" : ""}`}
              aria-hidden="true"
            >
              {loadingMore ? "sync" : "expand_more"}
            </span>
            {loadingMore ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
    </div>
  );
}
