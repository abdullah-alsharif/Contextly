"use client";

// Top bar — mirrors prototypes/chat.html header: search pill on
// surface-container-low with AI focus ring and Upload CTA with shadow.
import Link from "next/link";

export default function Topbar() {
  return (
    <header className="sticky top-0 z-10 flex h-16 w-full items-center justify-between border-b border-outline-variant bg-surface px-margin-desktop py-stack-sm md:px-gutter">
      <div className="flex items-center gap-4">
        <div className="hidden w-64 items-center rounded-lg border border-outline-variant bg-surface-container-low px-3 py-1.5 transition-all focus-within:border-secondary focus-within:ring-2 focus-within:ring-secondary/20 md:flex">
          <span className="material-symbols-outlined mr-2 text-[18px] text-on-surface-variant">
            search
          </span>
          <input
            type="search"
            aria-label="Search"
            placeholder="Search conversations..."
            className="w-full bg-transparent p-0 text-body-sm outline-none placeholder:text-on-surface-variant/70"
          />
        </div>
      </div>

      <div className="flex items-center gap-4">
        <Link
          href="/documents"
          className="flex items-center justify-center gap-2 rounded-lg bg-secondary py-1.5 px-4 font-display text-label-md text-on-secondary shadow-sm transition-transform duration-200 hover:bg-secondary/90 active:scale-95"
        >
          Upload
        </Link>
      </div>
    </header>
  );
}