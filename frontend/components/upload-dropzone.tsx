// Upload dropzone (docs/frontend-design.md §3): dashed border card, drag-drop
// + picker, client-side validation (contract C2), progress bar, friendly
// inline errors for 400/413.
"use client";

import { useCallback, useRef, useState, type DragEvent } from "react";
import type { Document } from "@/lib/api-client";
import type { UploadOutcome } from "@/lib/hooks/use-documents";

interface UploadDropzoneProps {
  upload: (file: File, onProgress?: (fraction: number) => void) => Promise<UploadOutcome>;
}

export default function UploadDropzone({ upload }: UploadDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [uploadedName, setUploadedName] = useState<string | null>(null);

  const handleFile = useCallback(
    async (file: File) => {
      if (uploading) return;
      setError(null);
      setUploadedName(null);
      if (!file.name.toLowerCase().endsWith(".pdf") || file.type !== "application/pdf") {
        setError("PDF files only — choose a file ending in .pdf.");
        return;
      }
      if (file.size > 10 * 1024 * 1024) {
        setError("This file is larger than the 10 MB limit. Choose a smaller PDF.");
        return;
      }
      setUploading(true);
      setProgress(0.02);
      try {
        const outcome = await upload(file, setProgress);
        if (!outcome.ok) {
          setError(outcome.error ?? "Upload failed. Please try again.");
        } else if (outcome.document) {
          setUploadedName(outcome.document.filename);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Upload failed. Please try again.");
      } finally {
        setUploading(false);
        if (inputRef.current) inputRef.current.value = "";
      }
    },
    [upload, uploading],
  );

  const onDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setDragging(false);
      const file = event.dataTransfer.files?.[0];
      if (file) void handleFile(file);
    },
    [handleFile],
  );

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label="Upload a PDF document"
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") inputRef.current?.click();
      }}
      onClick={() => !uploading && inputRef.current?.click()}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
className={`flex cursor-pointer flex-col items-center gap-3 rounded-xl border-2 border-dashed border-outline-variant bg-surface px-6 py-10 transition-all ${
        dragging ? "border-secondary bg-surface-container-low" : "hover:border-secondary hover:bg-surface-container-low"
      }`}
    >
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-secondary-fixed">
        <span className="material-symbols-outlined text-xl text-secondary">cloud_upload</span>
      </span>
      <div className="text-center">
        {uploading ? (
          <>
            <p className="font-display text-title-lg text-ink-900">
              Uploading… {Math.round(progress * 100)}%
            </p>
            <div className="mx-auto mt-2 h-1.5 w-56 overflow-hidden rounded-full bg-surface-container-high">
              <div
                className="h-full rounded-full bg-secondary transition-[width] duration-200"
                style={{ width: `${Math.max(progress * 100, 4)}%` }}
              />
            </div>
          </>
        ) : (
          <>
            <p className="font-display text-title-lg text-ink-900">
              Drop your PDF here, or <span className="text-secondary underline">browse</span>
            </p>
            <p className="mt-1 text-body-sm text-on-surface-variant">
              PDF only · up to 10 MB · text will be extracted and chunked automatically
            </p>
          </>
        )}
      </div>
      {uploadedName && !error && (
        <p className="flex items-center gap-1.5 text-label-sm text-success">
          <span className="material-symbols-outlined text-sm">task_alt</span>
          {uploadedName} uploaded
        </p>
      )}
      {error && (
        <p className="flex max-w-[26rem] items-center gap-1.5 rounded-lg border border-error-container/40 bg-error-container/60 px-3 py-1.5 text-label-sm text-error" role="alert">
          <span className="material-symbols-outlined text-sm">error</span>
          {error}
        </p>
      )}
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void handleFile(file);
        }}
      />
    </div>
  );
}