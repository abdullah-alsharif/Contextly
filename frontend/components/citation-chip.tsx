// Citation chip (docs/frontend-design.md §3): `[n]` + filename p.N pill,
// tertiary-fixed bg, hover dim.
"use client";

import type { Source } from "@/lib/api-client";

export default function CitationChip({
  index,
  source,
  onClick,
}: {
  index: number;
  source: Source;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={`${source.filename} · page ${source.page_number}`}
      className="mx-0.5 inline-flex translate-y-[-0.5px] items-center gap-1 rounded-full bg-tertiary-fixed px-2 py-0.5 align-middle font-display text-label-sm text-secondary transition-colors hover:bg-tertiary-fixed-dim"
    >
      [{index}] {source.filename} p.{source.page_number}
    </button>
  );
}