"use client";

// Filters live here so they can drive the hook's refetch; the no-matches state
// keeps the filter toolbar visible so it can be cleared.
import { useState } from "react";
import EmptyState from "@/components/empty-state";
import LogTable from "@/components/log-table";
import PageTitleBar from "@/components/page-title-bar";
import { useLogs, type LogFilters } from "@/lib/hooks/use-logs";

export default function LogsPage() {
  const [filters, setFilters] = useState<LogFilters>({});
  const { entries, loading, loadingMore, error, hasMore, loadMore } = useLogs({
    actionType: filters.action_type,
    from: filters.from,
    to: filters.to,
  });

  const filtersActive = Boolean(filters.action_type || filters.from || filters.to);

  return (
    <>
      <PageTitleBar
        title="Activity Log"
        subtitle="Your document actions and processing outcomes, newest first."
      />
      <div className="mx-auto w-full max-w-container-max px-4 py-6 md:px-8 md:py-8">
        {loading ? (
          <EmptyState icon="hourglass_empty" title="Loading activity…" />
        ) : error ? (
          <div
            className="rounded-xl border border-error-container/40 bg-error-container/60 px-4 py-3 text-body-sm text-error"
            role="alert"
          >
            {error}
          </div>
        ) : entries.length === 0 && !filtersActive ? (
          <EmptyState
            icon="list_alt"
            title="No activity yet"
            hint="Upload, delete, or process a PDF and it will show up here."
          />
        ) : (
          <LogTable
            entries={entries}
            loadingMore={loadingMore}
            hasMore={hasMore}
            onLoadMore={() => void loadMore()}
            filters={filters}
            onFiltersChange={setFilters}
            emptyContent={
              filtersActive ? (
                <EmptyState
                  icon="search_off"
                  title="No matches"
                  hint="Nothing matches these filters."
                />
              ) : undefined
            }
          />
        )}
      </div>
    </>
  );
}
