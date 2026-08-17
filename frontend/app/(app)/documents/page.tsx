"use client";

// Documents dashboard (docs/frontend-design.md §4): "Documents Space" header,
// stats bento (3 stat-cards), upload dropzone, recent-files table, empty + error
// states.
import { useState } from "react";
import DocumentTable from "@/components/document-table";
import EmptyState from "@/components/empty-state";
import PageTitleBar from "@/components/page-title-bar";
import StatCard from "@/components/stat-card";
import UploadDropzone from "@/components/upload-dropzone";
import { formatBytes } from "@/lib/format";
import { useDocuments } from "@/lib/hooks/use-documents";

export default function DocumentsPage() {
  const { documents, stats, loading, error, upload, remove, reprocess, cancel, deletingId, reprocessingId, cancellingId } =
    useDocuments();

  return (
    <>
      <PageTitleBar
        title="Documents Space"
        subtitle="Upload PDFs and ask questions across your knowledge base."
      />
      <div className="mx-auto w-full max-w-container-max px-8 py-8">
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-3" aria-label="Library stats">
        <StatCard
          label="Documents"
          value={String(stats.total)}
          icon="folder_open"
          hint={`${stats.total} file${stats.total === 1 ? "" : "s"} in your library`}
        />
        <StatCard
          label="Ready to chat"
          value={String(stats.ready)}
          icon="check_circle"
          hint={`${stats.processing} processing`}
        />
        <StatCard
          label="Indexed"
          value={stats.totalChunks > 0 ? stats.totalChunks.toLocaleString() : "0"}
          icon="database"
          hint={
            stats.totalBytes > 0
              ? `${formatBytes(stats.totalBytes, 1)} stored`
              : "0 MB stored"
          }
        />
      </section>

      <section className="mt-6">
        <UploadDropzone upload={upload} documents={documents} />
      </section>

      <section className="mt-8">
        <h2 className="mb-3 font-display text-title-lg text-on-surface">Recent files</h2>
        {loading ? (
          <EmptyState icon="hourglass_empty" title="Loading documents…" />
        ) : error ? (
          <div className="rounded-xl border border-error-container/40 bg-error-container/60 px-4 py-3 text-body-sm text-error" role="alert">
            {error}
          </div>
        ) : documents.length === 0 ? (
          <EmptyState
            icon="description"
            title="No documents yet"
            hint="Upload a PDF above — it will be chunked and indexed automatically so you can chat with it."
          />
        ) : (
          <DocumentTable
            documents={documents}
            onDelete={(id) => void remove(id)}
            onReprocess={(id) => void reprocess(id)}
            onCancel={(id) => void cancel(id)}
            deletingId={deletingId}
            reprocessingId={reprocessingId}
            cancellingId={cancellingId}
          />
        )}
      </section>
    </div>
    </>
  );
}
