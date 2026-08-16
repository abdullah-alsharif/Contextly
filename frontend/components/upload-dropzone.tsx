// Upload dropzone (docs/frontend-design.md §3, docs/api.md §2): drag-drop +
// picker, multi-file queue with aggregate progress, client-side validation,
// and duplicate handling — a 409 offers Update (reversible supersede) or
// upload under a suggested new name; the batch pauses per duplicate and
// resumes, nothing is dropped.
"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type FormEvent,
} from "react";
import { DuplicateDocumentError, type Document } from "@/lib/api-client";
import { formatBytes, formatDate } from "@/lib/format";
import type { UploadOutcome } from "@/lib/hooks/use-documents";

const MAX_BYTES = 10 * 1024 * 1024;

interface UploadDropzoneProps {
  upload: (
    file: File,
    onProgress?: (fraction: number) => void,
    options?: { replace?: boolean },
  ) => Promise<UploadOutcome>;
  documents?: Document[];
}

interface DuplicateState {
  file: File;
  existingId: string | null;
}

/** Suggest "name-2.pdf" (then -3, -4, …) skipping names already in the library. */
function suggestRename(name: string, existing: string[]): string {
  const dot = name.lastIndexOf(".");
  const stem = dot > 0 ? name.slice(0, dot) : name;
  const ext = dot > 0 ? name.slice(dot) : ".pdf";
  const used = new Set(existing);
  for (let n = 2; n < 100; n += 1) {
    const candidate = `${stem}-${n}${ext}`;
    if (!used.has(candidate)) return candidate;
  }
  return `${stem}-${Date.now()}${ext}`;
}

export default function UploadDropzone({ upload, documents }: UploadDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [uploadingName, setUploadingName] = useState<string | null>(null);
  const [uploadCurrent, setUploadCurrent] = useState(0);
  const [uploadTotal, setUploadTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [uploadedName, setUploadedName] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState<DuplicateState | null>(null);
  const [renameValue, setRenameValue] = useState("");
  // Batch queue: files after the paused duplicate, resumed once it is
  // resolved — every file in a multi-file drop gets handled in turn.
  const resumeQueueRef = useRef<File[]>([]);
  const [pendingCount, setPendingCount] = useState(0);
  const dialogOpenRef = useRef(false);
  const documentNames = useMemo(
    () => (documents ?? []).map((doc) => doc.filename),
    [documents],
  );
  const existingVersion = useMemo(
    () =>
      duplicate
        ? documents?.find((doc) => doc.id === duplicate.existingId)
        : undefined,
    [duplicate, documents],
  );

  // Keyboard users should land inside the dialog, not behind it on the dropzone
  useEffect(() => {
    if (duplicate) dialogRef.current?.focus({ preventScroll: true });
  }, [duplicate]);

  const handleFiles = useCallback(
    async (files: File[], replace = false) => {
      if (uploading || files.length === 0) return;
      setError(null);
      setUploadedName(null);
      setDuplicate(null);

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
        for (let i = 0; i < valid.length; i += 1) {
          const file = valid[i];
          setUploadingName(file.name);
          setProgress(0.02);
          try {
            const outcome = await upload(file, setProgress, replace ? { replace: true } : undefined);
            if (outcome.ok) {
              succeeded += 1;
              if (outcome.document) lastUploaded = outcome.document;
            } else if (firstFailure === null) {
              firstFailure = outcome.error ?? "Upload failed. Please try again.";
            }
          } catch (err) {
            if (err instanceof DuplicateDocumentError) {
              // Pause the batch for the user's choice; the queue resumes after.
              dialogOpenRef.current = true;
              resumeQueueRef.current = valid.slice(i + 1);
              setPendingCount(valid.length - i - 1);
              setDuplicate({ file, existingId: err.existingId });
              setRenameValue(suggestRename(file.name, documentNames));
              return;
            }
            throw err;
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
    [upload, uploading, documentNames],
  );

  const resumeBatch = useCallback(
    async (uploads: Promise<unknown>[] = []) => {
      const rest = resumeQueueRef.current;
      resumeQueueRef.current = [];
      setPendingCount(0);
      dialogOpenRef.current = false;
      for (const pending of uploads) await pending;
      if (rest.length > 0) await handleFiles(rest);
    },
    [handleFiles],
  );

  const submitRename = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      if (!duplicate || !renameValue.trim()) return;
      const renamed = new File([duplicate.file], renameValue.trim(), {
        type: duplicate.file.type,
      });
      setDuplicate(null);
      await resumeBatch([handleFiles([renamed])]);
    },
    [duplicate, renameValue, handleFiles, resumeBatch],
  );

  const handleUpdate = useCallback(async () => {
    if (!duplicate) return;
    const file = duplicate.file;
    setDuplicate(null);
    await resumeBatch([handleFiles([file], true)]);
  }, [duplicate, handleFiles, resumeBatch]);

  const cancelDuplicate = useCallback(async () => {
    setDuplicate(null);
    await resumeBatch();
  }, [setDuplicate, resumeBatch]);

  const onDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setDragging(false);
      const files = Array.from(event.dataTransfer.files);
      if (files.length > 0) void handleFiles(files);
    },
    [handleFiles],
  );

  // Guard lives at the user entry points — resolution paths call handleFiles
  // while the dialog is open; refs are read at event time so values are fresh.
  return (
    <div
      role="button"
      tabIndex={0}
      aria-label="Upload PDF documents"
      onKeyDown={(event) => {
        if (
          (event.key === "Enter" || event.key === " ") &&
          !uploading &&
          !dialogOpenRef.current
        )
          inputRef.current?.click();
      }}
      onClick={() => {
        if (!uploading && !dialogOpenRef.current) inputRef.current?.click();
      }}
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
      {uploadedName && !error && !duplicate && (
        <p className="flex items-center gap-1.5 text-label-sm text-success">
          <span className="material-symbols-outlined text-sm">task_alt</span>
          {uploadedName} uploaded
        </p>
      )}
      {duplicate && !uploading && (
        <div
          ref={dialogRef}
          tabIndex={-1}
          role="alert"
          className="dialog-in w-full max-w-[36rem] rounded-xl border border-outline-variant bg-surface-container-low p-4 text-left outline-none"
          onClick={(event) => event.stopPropagation()}
        >
          <p className="flex items-center gap-1.5 font-display text-label-sm font-medium text-on-surface">
            <span className="material-symbols-outlined text-sm text-secondary">priority_high</span>
            “{duplicate.file.name}” is already in your library.
          </p>
          {existingVersion && (
            <p className="mt-1 flex items-center gap-1.5 text-label-sm text-on-surface-variant">
              <span className="material-symbols-outlined text-sm">description</span>
              Current version · {formatBytes(existingVersion.file_size_bytes)} ·{" "}
              {formatDate(existingVersion.created_at)}
            </p>
          )}
          {pendingCount > 0 && (
            <p className="mt-1 flex items-center gap-1.5 text-label-sm text-on-surface-variant">
              <span className="material-symbols-outlined text-sm">queue</span>
              {pendingCount} more file
              {pendingCount === 1 ? "" : "s"} in this batch will continue after your
              choice.
            </p>
          )}
          <div className="mt-3 flex flex-col gap-2 sm:flex-row">
            <button
              type="button"
              onClick={() => void handleUpdate()}
              className="flex-1 rounded-xl border border-outline-variant bg-surface p-3 text-left transition-colors hover:border-secondary hover:bg-surface-container-low focus-visible:border-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-secondary/20"
            >
              <span className="flex items-center gap-2 font-display text-label-sm font-medium text-on-surface">
                <span className="material-symbols-outlined text-base text-secondary">swap_horiz</span>
                Update existing
              </span>
              <span className="mt-1 block pl-6 text-label-sm leading-relaxed text-on-surface-variant">
                Replaces the current version — it comes back if the new one fails.
              </span>
            </button>
            <div
              className="flex-1 cursor-text rounded-xl border border-outline-variant bg-surface p-3"
              onClick={() => renameInputRef.current?.focus()}
            >
              <span className="flex items-center gap-2 font-display text-label-sm font-medium text-on-surface">
                <span className="material-symbols-outlined text-base text-secondary">drive_file_rename_outline</span>
                Upload under a new name
              </span>
              <form onSubmit={submitRename} className="mt-2 flex items-center gap-2">
                <input
                  ref={renameInputRef}
                  type="text"
                  value={renameValue}
                  onChange={(event) => setRenameValue(event.target.value)}
                  aria-label="New file name"
                  className="min-w-0 flex-1 rounded-lg border border-outline-variant bg-surface-container-low px-2.5 py-1.5 text-label-sm outline-none transition-colors focus:border-secondary focus:ring-2 focus:ring-secondary/20"
                />
                <button
                  type="submit"
                  disabled={!renameValue.trim().toLowerCase().endsWith(".pdf")}
                  className="rounded-lg bg-secondary px-3 py-1.5 font-display text-label-sm text-on-secondary transition-colors enabled:hover:bg-secondary/90 disabled:opacity-50"
                >
                  Upload
                </button>
              </form>
              <span className="mt-1.5 block text-label-sm leading-relaxed text-on-surface-variant">
                Keeps the current version.
              </span>
            </div>
          </div>
          <div className="mt-2 text-right">
            <button
              type="button"
              onClick={() => void cancelDuplicate()}
              className="rounded-lg px-3 py-1.5 font-display text-label-sm text-on-surface-variant transition-colors hover:bg-surface-container"
            >
              Cancel
            </button>
          </div>
        </div>
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
          if (files.length > 0 && !uploading && !dialogOpenRef.current)
            void handleFiles(files);
        }}
      />
    </div>
  );
}