// Upload dropzone (docs/frontend-design.md §3): dashed border card, drag-drop
// + picker, multi-file (sequential uploads, aggregate progress), client-side
// validation (contract C2), progress bar, friendly inline errors for 400/413.
"use client";

import { useCallback, useRef, useState, type DragEvent } from "react";
import type { Document } from "@/lib/api-client";
import type { UploadOutcome } from "@/lib/hooks/use-documents";

const MAX_BYTES = 10 * 1024 * 1024;

interface UploadDropzoneProps {
  upload: (file: File, onProgress?: (fraction: number) => void) => Promise<UploadOutcome>;
}

export default function UploadDropzone({ upload }: UploadDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [uploadingName, setUploadingName] = useState<string | null>(null);
  const [uploadCurrent, setUploadCurrent] = useState(0);
  const [uploadTotal, setUploadTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [uploadedName, setUploadedName] = useState<string | null>(null);

  const handleFiles = useCallback(
    async (files: File[]) => {
      if (uploading || files.length === 0) return;
      setError(null);
      setUploadedName(null);

      const nonPdf: string[] = [];
      const oversized: string[] = [];
      const valid: File[] = [];
      for (const file of files) {
        if (!file.name.toLowerCase().endsWith(".pdf") || file.type !== "application/pdf") {
          nonPdf.push(file.name);
        } else if (file.size > MAX_BYTES) {
          oversized.push(file.name);
        } else {
          valid.push(file);
        }
      }
      if (valid.length === 0) {
        setError(
          oversized.length > 0 && nonPdf.length === 0
            ? "These files are larger than the 10 MB limit. Choose smaller PDFs."
            : "PDF files only — drop files ending in .pdf.",
        );
        return;
      }

      setUploading(true);
      setUploadTotal(valid.length);
      setUploadCurrent(0);
      let succeeded = 0;
      let lastUploaded: Document | null = null;
      let firstFailure: string | null = null;
      try {
        for (const file of valid) {
          setUploadingName(file.name);
          setProgress(0.02);
          const outcome = await upload(file, setProgress);
          if (outcome.ok) {
            succeeded += 1;
            if (outcome.document) lastUploaded = outcome.document;
          } else if (firstFailure === null) {
            firstFailure = outcome.error ?? "Upload failed. Please try again.";
          }
          setUploadCurrent((current) => current + 1);
        }
        if (succeeded === 1 && lastUploaded) {
          setUploadedName(lastUploaded.filename);
        } else if (succeeded > 1) {
          setUploadedName(`${succeeded} files`);
        }
        if (firstFailure) {
          setError(firstFailure);
        } else if (nonPdf.length + oversized.length > 0) {
          setError(
            `Skipped ${nonPdf.length + oversized.length} file${nonPdf.length + oversized.length === 1 ? "" : "s"} — not a PDF or over the 10 MB limit.`,
          );
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Upload failed. Please try again.");
      } finally {
        setUploading(false);
        setUploadingName(null);
        setUploadCurrent(0);
        setUploadTotal(0);
        if (inputRef.current) inputRef.current.value = "";
      }
    },
    [upload, uploading],
  );

  const onDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setDragging(false);
      const files = Array.from(event.dataTransfer.files);
      if (files.length > 0) void handleFiles(files);
    },
    [handleFiles],
  );

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label="Upload PDF documents"
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
              Uploading {uploadingName}… {Math.round(progress * 100)}%
            </p>
            {uploadTotal > 1 && (
              <p className="mt-1 text-label-sm text-on-surface-variant">
                File {Math.min(uploadCurrent + 1, uploadTotal)} of {uploadTotal}
              </p>
            )}
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
              Drop your PDFs here, or <span className="text-secondary underline">browse</span>
            </p>
            <p className="mt-1 text-body-sm text-on-surface-variant">
              PDF only · up to 10 MB each · text will be extracted and chunked automatically
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
        multiple
        className="hidden"
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          if (files.length > 0) void handleFiles(files);
        }}
      />
    </div>
  );
}