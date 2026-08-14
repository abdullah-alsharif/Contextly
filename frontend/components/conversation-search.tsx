"use client";

// Search chats popup — compact ChatGPT-style overlay (docs/frontend-design.md
// "Search popup"): borderless 16px query header, ~70px rows, 5-at-a-time
// infinite scroll. Panel is a fixed 718×460 (clamped by the viewport).
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import {
  searchConversations,
  type Conversation,
  type ConversationSearchResult,
} from "@/lib/api-client";

const DEBOUNCE_MS = 200;
const PAGE_SIZE = 5;

type SearchStatus = "idle" | "searching" | "done" | "error";

interface ConversationSearchProps {
  initialQuery?: string;
  initialResults?: ConversationSearchResult[];
  recents: Conversation[];
  liveConversations: Conversation[];
  onClose: () => void;
  /** Keep query + results so Cmd+K can restore them when a row opens. */
  onOpenConversation: (
    query: string,
    results: ConversationSearchResult[],
  ) => void;
}

function highlightText(text: string, query: string): ReactNode {
  const needle = query.trim().toLowerCase();
  if (!needle) return text;
  const lower = text.toLowerCase();
  const parts: ReactNode[] = [];
  let cursor = 0;
  let index = lower.indexOf(needle);
  while (index !== -1) {
    if (index > cursor) parts.push(text.slice(cursor, index));
    const end = index + needle.length;
    parts.push(
      <span key={index} className="font-semibold">
        {text.slice(index, end)}
      </span>,
    );
    cursor = end;
    index = lower.indexOf(needle, cursor);
  }
  if (cursor < text.length) parts.push(text.slice(cursor));
  return parts;
}

/** Today / Yesterday / MMM D / MMM D, YYYY. */
function formatDate(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const dayMs = 86_400_000;
  const dayDiff = Math.floor(
    (Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()) -
      Date.UTC(date.getFullYear(), date.getMonth(), date.getDate())) /
      dayMs,
  );
  if (dayDiff <= 0) return "Today";
  if (dayDiff === 1) return "Yesterday";
  const sameYear = date.getFullYear() === now.getFullYear();
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
  });
}

function SearchResultRow({
  conversation,
  preview,
  query,
  onOpen,
}: {
  conversation: Conversation;
  preview: string | null;
  query: string;
  onOpen: () => void;
}) {
  return (
    <Link
      data-search-row
      href={`/chat/${conversation.id}`}
      onClick={onOpen}
      className="flex items-center gap-[17px] pl-[36px] pr-[24px] py-[15px] transition-colors duration-100 hover:bg-[#F5F5F5] focus-visible:bg-[#F5F5F5]"
    >
      <span
        className="material-symbols-outlined shrink-0 !text-[20px] text-[#171717]"
        aria-hidden="true"
      >
        {conversation.archived ? "archive" : "forum"}
      </span>
      <div className="min-w-0 flex-1">
        <span className="flex items-baseline gap-4">
          <span className="min-w-0 flex-1 truncate text-[14px] leading-[20px] text-[#202020]">
            {highlightText(conversation.title, query)}
          </span>
          <time className="shrink-0 text-[13px] leading-[20px] text-[#777777]">
            {formatDate(conversation.updated_at)}
          </time>
        </span>
        {preview && (
          <span className="mt-[1px] block truncate text-[13px] leading-[19px] text-[#777777]">
            {highlightText(preview, query)}
          </span>
        )}
      </div>
    </Link>
  );
}

function SkeletonRow({
  titleWidth,
  previewWidth,
}: {
  titleWidth: string;
  previewWidth: string;
}) {
  return (
    <div
      data-skeleton-row
      aria-hidden="true"
      className="flex items-center gap-[17px] px-[36px] py-[15px]"
    >
      <div className="sb-skeleton h-5 w-5 shrink-0 rounded-md" />
      <div className="flex min-w-0 flex-1 flex-col gap-[5px]">
        <div
          className="sb-skeleton h-3.5 rounded-sm"
          style={{ width: titleWidth }}
        />
        <div
          className="sb-skeleton h-3 rounded-sm"
          style={{ width: previewWidth }}
        />
      </div>
    </div>
  );
}

const SKELETON_VARIANTS = [
  { titleWidth: "62%", previewWidth: "88%" },
  { titleWidth: "55%", previewWidth: "82%" },
  { titleWidth: "68%", previewWidth: "90%" },
  { titleWidth: "58%", previewWidth: "84%" },
];

export default function ConversationSearch({
  initialQuery = "",
  initialResults,
  recents,
  liveConversations,
  onClose,
  onOpenConversation,
}: ConversationSearchProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const requestIdRef = useRef(0);
  const [query, setQuery] = useState(initialQuery);
  const [results, setResults] = useState<ConversationSearchResult[]>(
    initialResults ?? [],
  );
  const [offset, setOffset] = useState(initialResults?.length ?? 0);
  const [hasMore, setHasMore] = useState(
    (initialResults?.length ?? 0) >= PAGE_SIZE,
  );
  const [status, setStatus] = useState<SearchStatus>(
    initialResults ? "done" : "idle",
  );
  const [fetchingMore, setFetchingMore] = useState(false);
  const [moreError, setMoreError] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const [announcement, setAnnouncement] = useState("");

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Debounced search; stale responses dropped by request id.
  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setResults([]);
      setOffset(0);
      setHasMore(false);
      setStatus("idle");
      setAnnouncement("");
      return;
    }
    setResults([]);
    setOffset(0);
    setHasMore(false);
    setFetchingMore(false);
    setMoreError(false);
    setStatus("searching");
    const id = ++requestIdRef.current;
    const timer = window.setTimeout(() => {
      searchConversations(trimmed, 0, PAGE_SIZE)
        .then((rows) => {
          if (requestIdRef.current !== id) return;
          setResults(rows);
          setOffset(rows.length);
          setHasMore(rows.length === PAGE_SIZE);
          setStatus("done");
          setAnnouncement(
            rows.length === 0
              ? "No conversations found"
              : `${rows.length} conversation${rows.length === 1 ? "" : "s"} found`,
          );
        })
        .catch(() => {
          if (requestIdRef.current !== id) return;
          setStatus("error");
        });
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [query, retryKey]);

  // Escape closes the popup.
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const liveById = useMemo(
    () => new Map(liveConversations.map((row) => [row.id, row])),
    [liveConversations],
  );

  // Bottom sentinel fetches the next page when visible — also backfills when
  // a page fits without overflowing (no scrollbar to reach).
  const loadMore = useCallback(() => {
    const trimmed = query.trim();
    if (!trimmed || status !== "done" || !hasMore || fetchingMore) return;
    setFetchingMore(true);
    setMoreError(false);
    const id = ++requestIdRef.current;
    searchConversations(trimmed, offset, PAGE_SIZE)
      .then((rows) => {
        if (requestIdRef.current !== id) return;
        setResults((current) => [...current, ...rows]);
        setOffset((current) => current + rows.length);
        setHasMore(rows.length === PAGE_SIZE);
        setFetchingMore(false);
      })
      .catch(() => {
        if (requestIdRef.current !== id) return;
        setFetchingMore(false);
        setMoreError(true);
      });
  }, [query, offset, status, hasMore, fetchingMore]);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    const root = listRef.current;
    if (!sentinel || !root) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) loadMore();
      },
      { root, rootMargin: "24px 0px" },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [loadMore]);

  // Arrow keys rove focus across result rows.
  const onPanelKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const rows = listRef.current?.querySelectorAll<HTMLAnchorElement>(
      "a[data-search-row]",
    );
    if (!rows || rows.length === 0) return;
    event.preventDefault();
    const currentIndex = Array.prototype.indexOf.call(rows, document.activeElement);
    const next =
      event.key === "ArrowDown"
        ? Math.min(currentIndex + 1, rows.length - 1)
        : Math.max(currentIndex - 1, 0);
    rows[next]?.focus();
  };

const trimmed = query.trim();
  const showRecents = status === "idle";
  const showSkeleton = status === "searching" && trimmed !== "";
  const showNoResults = status === "done" && results.length === 0 && trimmed !== "";
  const showError = status === "error";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Search conversations"
      onKeyDown={onPanelKeyDown}
      className="fixed inset-0 z-50 flex items-center justify-center p-4 max-md:p-0"
    >
      <div
        className="fade-in absolute inset-0 bg-black/40"
        onClick={onClose}
        aria-hidden="true"
      />
      <div className="dialog-in relative flex h-[min(460px,calc(100vh_-_32px))] w-[min(718px,calc(100vw_-_32px))] max-md:h-dvh max-md:w-full max-md:rounded-none max-md:border-0 flex-col overflow-hidden rounded-2xl border border-[#E0E0E0] bg-white shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
        {/* Header sits above the no-results overlay so Clear/X stay clickable. */}
        <div className="relative z-10 flex items-center gap-[18px] px-[27px] pt-[20px]">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Search conversations"
            placeholder="Search conversations"
            className="h-10 min-w-0 flex-1 bg-transparent text-[16px] leading-[24px] text-[#171717] outline-none placeholder:text-[#A8A8A8]"
          />
          {trimmed !== "" && (
            <>
              <button
                type="button"
                onClick={() => setQuery("")}
                aria-label="Clear search"
                className="shrink-0 text-[14px] leading-[20px] text-[#666666] transition-colors duration-100 hover:text-[#333333]"
              >
                Clear
              </button>
              <span
                aria-hidden="true"
                className="h-[22px] w-px shrink-0 bg-[#E5E5E5]"
              />
            </>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="Close search"
            title="Close search (Esc)"
            className="flex h-10 w-10 shrink-0 items-center justify-center text-[#202020]"
          >
            <span
              className="material-symbols-outlined !text-[20px]"
              aria-hidden="true"
            >
              close
            </span>
          </button>
        </div>

        <div
          ref={listRef}
          data-conv-scroll
          className="custom-scrollbar min-w-0 flex-1 overflow-y-auto pb-[10px]"
          aria-busy={status === "searching" || fetchingMore}
        >
          {showRecents && (
            <>
              <p className="px-[36px] pb-[4px] pt-[10px] text-[13px] leading-[20px] text-[#777777]">
                Recent
              </p>
              {recents.length === 0 ? (
                <p className="px-[36px] py-2 text-[13px] text-[#777777]">
                  No conversations yet
                </p>
              ) : (
                <div className="flex flex-col">
                  {recents.map((conversation) => (
                    <SearchResultRow
                      key={conversation.id}
                      conversation={conversation}
                      preview={null}
                      query=""
                      onOpen={() => onOpenConversation(trimmed, results)}
                    />
                  ))}
                </div>
              )}
            </>
          )}
          {showSkeleton && (
            <div className="flex flex-col" aria-hidden="true">
              {SKELETON_VARIANTS.map((variant, index) => (
                <SkeletonRow key={index} {...variant} />
              ))}
            </div>
          )}
          {showNoResults && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="flex items-center gap-2">
                <span
                  className="material-symbols-outlined !text-[24px] text-[#C9C9C9]"
                  aria-hidden="true"
                >
                  search
                </span>
                <p className="text-[14px] leading-[20px] text-[#666666]">
                  No results
                </p>
              </div>
            </div>
          )}
          {showError && (
            <div className="flex flex-col items-center justify-center gap-2 px-4 py-6 text-center">
              <p className="text-[14px] text-[#666666]">
                Couldn&apos;t search right now.
              </p>
              <button
                type="button"
                onClick={() => setRetryKey((key) => key + 1)}
                className="text-[13px] text-[#666666] transition-colors hover:text-[#333333]"
              >
                Try again
              </button>
            </div>
          )}
          {results.length > 0 && (
            <div className="results-in flex flex-col">
              {results.map((result) => {
                const live = liveById.get(result.id);
                const row = live ?? result;
                return (
                  <SearchResultRow
                    key={result.id}
                    conversation={row}
                    preview={result.preview}
                    query={trimmed}
                    onOpen={() => onOpenConversation(trimmed, results)}
                  />
                );
              })}
            </div>
          )}
          {fetchingMore && (
            <SkeletonRow titleWidth="50%" previewWidth="70%" />
          )}
          {moreError && (
            <div className="flex items-center justify-center gap-2 px-4 py-3">
              <p className="text-[13px] text-[#666666]">
                Couldn&apos;t load more.
              </p>
              <button
                type="button"
                onClick={loadMore}
                className="text-[13px] text-[#666666] transition-colors hover:text-[#333333]"
              >
                Retry
              </button>
            </div>
          )}
          <div ref={sentinelRef} aria-hidden="true" className="h-px" />
          <span aria-live="polite" className="sr-only">
            {announcement}
          </span>
        </div>
      </div>
    </div>
  );
}
