// Activity log hook: initial page load + "load more" append, refetching when
// the filters change. Follows use-documents.ts (deferred initial fetch, page
// of 50 per contracts/logs.md §2).
"use client";

import { useCallback, useEffect, useState } from "react";
import { listLogs, type ActionType, type LogEntry } from "@/lib/api-client";

const PAGE_SIZE = 50;

export interface LogFilters {
  action_type?: ActionType;
  from?: string;
  to?: string;
}

export function useLogs({
  actionType,
  from,
  to,
}: {
  actionType?: ActionType;
  from?: string;
  to?: string;
}) {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      // Deferred so the initial fetch's setState isn't synchronous with render
      // (react-hooks/set-state-in-effect; same pattern as use-documents.ts).
      setLoading(true);
      listLogs({ action_type: actionType, from, to, offset: 0, limit: PAGE_SIZE })
        .then((rows) => {
          if (cancelled) return;
          setEntries(rows);
          setHasMore(rows.length === PAGE_SIZE);
          setError(null);
        })
        .catch((err) => {
          if (cancelled) return;
          setError(
            err instanceof Error ? err.message : "Could not load your activity.",
          );
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [actionType, from, to]);

  const loadMore = useCallback(async () => {
    setLoadingMore(true);
    try {
      const rows = await listLogs({
        action_type: actionType,
        from,
        to,
        offset: entries.length,
        limit: PAGE_SIZE,
      });
      setEntries((prev) => [...prev, ...rows]);
      setHasMore(rows.length === PAGE_SIZE);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load more.");
    } finally {
      setLoadingMore(false);
    }
  }, [actionType, from, to, entries.length]);

  return { entries, loading, loadingMore, error, hasMore, loadMore };
}
