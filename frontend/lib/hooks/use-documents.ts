// Documents workspace hook: list + 3 s polling while any row is
// uploaded/processing (research D4), upload with progress, delete (404
// tolerant), stats derivation (counts, size sum).
"use client";

import { useCallback, useEffect, useState } from "react";
import {
  deleteDocument,
  listDocuments,
  reprocessDocument,
  uploadDocument,
  type Document,
} from "@/lib/api-client";

export interface DocumentStats {
  total: number;
  ready: number;
  processing: number;
  totalBytes: number;
  totalChunks: number;
}

export interface UploadOutcome {
  ok: boolean;
  document?: Document;
  error?: string;
}

function deriveStats(documents: Document[]): DocumentStats {
  return documents.reduce<DocumentStats>(
    (stats, doc) => {
      stats.total += 1;
      stats.totalBytes += doc.file_size_bytes;
      stats.totalChunks += doc.total_chunks ?? 0;
      if (doc.status === "ready") stats.ready += 1;
      if (doc.status === "processing" || doc.status === "uploaded") stats.processing += 1;
      return stats;
    },
    { total: 0, ready: 0, processing: 0, totalBytes: 0, totalChunks: 0 },
  );
}

export function useDocuments() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [reprocessingId, setReprocessingId] = useState<string | null>(null);

  const refresh = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const rows = await listDocuments();
      setDocuments(rows);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load documents.");
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Poll while anything is still uploading/processing.
  useEffect(() => {
    const pending = documents.some(
      (doc) => doc.status === "uploaded" || doc.status === "processing",
    );
    if (!pending) return;
    const timer = window.setInterval(() => void refresh(true), 3000);
    return () => window.clearInterval(timer);
  }, [documents, refresh]);

  const upload = useCallback(
    async (file: File, onProgress?: (fraction: number) => void): Promise<UploadOutcome> => {
      setError(null);
      try {
        const document = await uploadDocument(file, onProgress);
        setDocuments((rows) => [document, ...rows.filter((row) => row.id !== document.id)]);
        return { ok: true, document };
      } catch (err) {
        const message = err instanceof Error ? err.message : "Upload failed. Please try again.";
        setError(message);
        return { ok: false, error: message };
      }
    },
    [],
  );

  const remove = useCallback(
    async (id: string) => {
      setDeletingId(id);
      try {
        await deleteDocument(id);
      } catch (err) {
        // 404-tolerant: row disappears either way (task T020)
        if (!(err instanceof Error) || !/404|no longer exists/.test(err.message)) {
          setError(err instanceof Error ? err.message : "Delete failed.");
        }
      } finally {
        setDocuments((rows) => rows.filter((row) => row.id !== id));
        setDeletingId(null);
      }
    },
    [],
  );

  const reprocess = useCallback(
    async (id: string) => {
      setReprocessingId(id);
      try {
        const document = await reprocessDocument(id);
        setDocuments((rows) =>
          rows.map((row) => (row.id === id ? document : row)),
        );
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Reprocessing failed.");
      } finally {
        setReprocessingId(null);
      }
    },
    [],
  );

  const stats = deriveStats(documents);

  return {
    documents,
    stats,
    loading,
    error,
    upload,
    remove,
    reprocess,
    deletingId,
    reprocessingId,
  };
}