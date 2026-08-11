// Status badge (docs/frontend-design.md §3): pill mapping state → tone.
// processing shows a `sync` spinner; failed shows an error dot + reason tooltip.
import type { DocumentStatus } from "@/lib/api-client";

const TONES: Record<DocumentStatus, string> = {
  ready: "bg-secondary-fixed text-on-secondary-fixed-variant",
  processing: "bg-surface-container-high text-on-surface",
  uploaded: "bg-surface-container-high text-on-surface-variant",
  failed: "bg-error-container text-error",
  deleted: "bg-surface-variant text-on-surface-variant",
};

const LABELS: Record<DocumentStatus, string> = {
  ready: "Ready",
  processing: "Processing",
  uploaded: "Queued",
  failed: "Failed",
  deleted: "Deleted",
};

export default function StatusBadge({
  status,
  error,
}: {
  status: DocumentStatus;
  error?: string | null;
}) {
  return (
    <span
      title={error ?? undefined}
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-display text-label-sm font-medium ${TONES[status]}`}
    >
      {status === "processing" && (
        <span className="material-symbols-outlined animate-spin text-sm" aria-hidden="true">
          sync
        </span>
      )}
      {status === "failed" && (
        <span className="material-symbols-outlined text-sm" aria-hidden="true">
          error
        </span>
      )}
      {LABELS[status]}
    </span>
  );
}