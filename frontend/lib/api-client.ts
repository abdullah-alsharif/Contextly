// Typed API client for the Contextly backend (docs/api.md). Consumption
// contracts: specs/009-frontend-buildout/contracts/frontend-consumption.md.
// Auth: Authorization: Bearer <JWT> on every request; 401 clears the session
// and redirects to /login.
import { getBrowserAccessToken } from "./auth/session";

export const BACKEND_URL: string =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

// ---- Types (data-model.md; docs/api.md §2–4) -----------------------------

export type DocumentStatus =
  | "uploaded"
  | "processing"
  | "ready"
  | "failed"
  | "deleted"
  | "superseded";

export interface Document {
  id: string;
  filename: string;
  status: DocumentStatus;
  file_size_bytes: number;
  total_chunks: number | null;
  status_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  pinned: boolean;
  archived: boolean;
  message_count: number;
  created_at: string;
  updated_at: string;
}

/** A search result: the conversation plus a preview snippet of the newest
 * matching message (null for title-only matches). */
export interface ConversationSearchResult extends Conversation {
  preview: string | null;
}

export interface ConversationDetail {
  conversation: Conversation;
  documents: Document[];
}

export interface Source {
  document_id: string;
  filename: string;
  page_number: number;
  chunk_index: number;
  similarity: number;
  /** Chunk text snapshot (≤600 chars) from the stored payload — FR-011. */
  excerpt?: string | null;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: Source[];
  input_tokens?: number | null;
  output_tokens?: number | null;
  retrieval_ms?: number | null;
  llm_ms?: number | null;
  created_at: string;
}

// ---- Errors ---------------------------------------------------------------

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** A 409 from the upload endpoint: an active file with the same name exists.
 * `existingId` lets the UI offer replace-vs-rename (docs/api.md §2). */
export class DuplicateDocumentError extends ApiError {
  readonly existingId: string | null;
  constructor(message: string, existingId: string | null) {
    super(409, message);
    this.name = "DuplicateDocumentError";
    this.existingId = existingId;
  }
}

function detailFrom(payload: unknown, fallback: string): string {
  if (
    payload &&
    typeof payload === "object" &&
    "detail" in payload &&
    typeof (payload as { detail: unknown }).detail === "string"
  ) {
    return (payload as { detail: string }).detail;
  }
  return fallback;
}

/** FastAPI-friendly human message per status (docs/api.md §6). */
export function friendlyError(status: number, message: string): string {
  switch (status) {
    case 400:
      return message || "The request was rejected.";
    case 413:
      return "This file is larger than the 10 MB limit. Choose a smaller PDF.";
    case 401:
      return "Your session expired. Please sign in again.";
    case 404:
      return "That item no longer exists.";
    case 422:
      return message || "Check the input and try again.";
    case 502:
    case 503:
      return "The answering service is temporarily unavailable. Try again shortly.";
    default:
      return message || "Something went wrong. Please try again.";
  }
}

// ---- Fetch wrapper ---------------------------------------------------------

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const token = await getBrowserAccessToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${BACKEND_URL}${path}`, { ...init, headers });

  if (res.status === 401) {
    await signOutLocally();
    throw new ApiError(401, "Your session expired. Please sign in again.");
  }
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      message = detailFrom(await res.json(), message);
    } catch {
      // non-JSON body — keep fallback message
    }
    throw new ApiError(res.status, friendlyError(res.status, message));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---- Documents (contracts C2) ----------------------------------------------

export function listDocuments(): Promise<Document[]> {
  return request<Document[]>("/api/v1/documents");
}

export async function uploadDocument(
  file: File,
  onProgress?: (fraction: number) => void,
  options?: { replace?: boolean },
): Promise<Document> {
  if (file.type !== "application/pdf" || !file.name.toLowerCase().endsWith(".pdf")) {
    throw new ApiError(400, "PDF files only. Choose a file ending in .pdf.");
  }
  if (file.size > 10 * 1024 * 1024) {
    throw new ApiError(413, "This file is larger than the 10 MB limit.");
  }

  const token = await getBrowserAccessToken();
  const form = new FormData();
  form.append("file", file, file.name);

  const result = await new Promise<Document>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(
      "POST",
      `${BACKEND_URL}/api/v1/documents${options?.replace ? "?replace=true" : ""}`,
    );
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(event.loaded / event.total);
      }
    };
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        body = null;
      }
      if (xhr.status === 401) {
        void signOutLocally();
        reject(new ApiError(401, "Your session expired. Please sign in again."));
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as Document);
        return;
      }
      const message = detailFrom(body, `Upload failed (${xhr.status}).`);
      if (xhr.status === 409) {
        const existingId = xhr.getResponseHeader("X-Existing-Document-Id");
        reject(
          new DuplicateDocumentError(message, existingId ? existingId : null),
        );
        return;
      }
      reject(new ApiError(xhr.status, friendlyError(xhr.status, message)));
    };
    xhr.onerror = () => reject(new ApiError(0, "Network error — check your connection."));
    xhr.onabort = () => reject(new ApiError(0, "Upload was cancelled."));
    xhr.send(form);
  });
  return result;
}

export function deleteDocument(id: string): Promise<void> {
  return request<void>(`/api/v1/documents/${id}`, { method: "DELETE" });
}

export function reprocessDocument(id: string): Promise<Document> {
  return request<Document>(`/api/v1/documents/${id}/reprocess`, { method: "PATCH" });
}

export async function downloadDocument(id: string): Promise<Blob> {
  const token = await getBrowserAccessToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${BACKEND_URL}/api/v1/documents/${id}/download`, { headers });
  if (res.status === 401) {
    await signOutLocally();
    throw new ApiError(401, "Your session expired. Please sign in again.");
  }
  if (!res.ok) throw new ApiError(res.status, "Could not download the document.");
  return res.blob();
}

// ---- Conversations (contracts C3) ------------------------------------------

export function listConversations(archived = false): Promise<Conversation[]> {
  return request<Conversation[]>(
    `/api/v1/conversations${archived ? "?archived=true" : ""}`,
  );
}

/** Ranked title/message search (docs/api.md §3), paged 5 at a time. */
export function searchConversations(
  q: string,
  offset = 0,
  limit = 5,
): Promise<ConversationSearchResult[]> {
  return request<ConversationSearchResult[]>(
    `/api/v1/conversations?q=${encodeURIComponent(q)}&offset=${offset}&limit=${limit}`,
  );
}

export function createConversation(init: {
  title?: string;
  document_ids?: string[];
}): Promise<Conversation> {
  return request<Conversation>("/api/v1/conversations", {
    method: "POST",
    body: JSON.stringify(init),
  });
}

export function getConversation(id: string): Promise<ConversationDetail> {
  return request<ConversationDetail>(`/api/v1/conversations/${id}`);
}

export function updateConversation(
  id: string,
  patch: {
    title?: string;
    document_ids?: string[];
    pinned?: boolean;
    archived?: boolean;
  },
): Promise<Conversation> {
  return request<Conversation>(`/api/v1/conversations/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteConversation(id: string): Promise<void> {
  return request<void>(`/api/v1/conversations/${id}`, { method: "DELETE" });
}

// ---- Messages (contracts C4) -----------------------------------------------

export function listMessages(conversationId: string): Promise<Message[]> {
  return request<Message[]>(`/api/v1/conversations/${conversationId}/messages`);
}

export interface StreamEvents {
  onDelta: (text: string) => void;
  onDone: (payload: { id: string; sources: Source[]; llm_ms?: number | null }) => void;
  onError: (message: string) => void;
}

/**
 * POST the question and parse the SSE stream (docs/api.md §4).
 * Buffered line parsing survives chunk boundaries; the same Idempotency-Key
 * must be reused on retry so no user message is duplicated (chat.md §6).
 */
export async function streamAnswer(
  conversationId: string,
  content: string,
  idempotencyKey: string,
  events: StreamEvents,
  signal?: AbortSignal,
): Promise<void> {
  const token = await getBrowserAccessToken();
  const res = await fetch(
    `${BACKEND_URL}/api/v1/conversations/${conversationId}/messages`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ content }),
      signal,
    },
  );

  if (res.status === 401) {
    await signOutLocally();
    events.onError("Your session expired. Please sign in again.");
    return;
  }
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      message = detailFrom(await res.json(), message);
    } catch {
      // keep fallback
    }
    events.onError(friendlyError(res.status, message));
    return;
  }
  if (!res.body) {
    events.onError("The stream ended unexpectedly.");
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let currentEvent = "message";

  const dispatch = (data: string) => {
    let payload: unknown;
    try {
      payload = JSON.parse(data);
    } catch {
      return;
    }
    if (!payload || typeof payload !== "object") return;
    const obj = payload as Record<string, unknown>;
    switch (currentEvent) {
      case "delta":
        if (typeof obj.text === "string") events.onDelta(obj.text);
        break;
      case "done":
        events.onDone({
          id: typeof obj.id === "string" ? obj.id : "",
          sources: Array.isArray(obj.sources) ? (obj.sources as Source[]) : [],
          llm_ms: typeof obj.llm_ms === "number" ? obj.llm_ms : null,
        });
        break;
      case "error":
        events.onError(
          typeof obj.message === "string" ? obj.message : "The answer failed.",
        );
        break;
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const trimmed = line.replace(/\r$/, "");
      if (trimmed.startsWith("event:")) {
        currentEvent = trimmed.slice(6).trim();
      } else if (trimmed.startsWith("data:")) {
        dispatch(trimmed.slice(5).trim());
      }
    }
  }
}

// ---- Profile + session (contracts C1) ----------------------------------------

export interface Profile {
  id: string;
  email: string;
  full_name: string | null;
  created_at: string;
  updated_at: string;
}

export function getProfile(): Promise<Profile> {
  return request<Profile>("/api/v1/auth/me");
}

export function updateProfile(fullName: string | null): Promise<Profile> {
  return request<Profile>("/api/v1/auth/me", {
    method: "PATCH",
    body: JSON.stringify({ full_name: fullName }),
  });
}

export async function signOutLocally(): Promise<void> {
  const token = await getBrowserAccessToken();
  try {
    await fetch("/api/auth/logout", { method: "POST", keepalive: true });
  } catch {
    // network dropped; cookies clear below regardless
  }
  if (typeof window !== "undefined" && token) {
    window.location.assign(new URL("/login", window.location.origin).href);
  }
}