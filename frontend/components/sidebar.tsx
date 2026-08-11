"use client";

// Sidebar — mirrors prototypes/chat.html SideNavBar: bg-surface shell,
// avatar brand header, primary CTA with shadow, active nav item with fill
// icon + left accent, Recent list, user chip with sign-out.
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { listConversations, signOutLocally, type Conversation } from "@/lib/api-client";

const NAV_ITEMS = [
  { href: "/documents", label: "Documents", icon: "description" },
  { href: "/chat", label: "Chat", icon: "forum" },
  { href: "/settings", label: "Settings", icon: "settings" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const [recent, setRecent] = useState<Conversation[]>([]);
  const [email, setEmail] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    listConversations()
      .then((rows) => {
        if (!cancelled) setRecent(rows.slice(0, 5));
      })
      .catch(() => {
        // sidebar renders without recents
      });
    fetch("/api/v1/auth/me")
      .then((res) => (res.ok ? res.json() : null))
      .then((profile) => {
        if (profile && !cancelled) setEmail(profile.email ?? "");
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const chatActive = pathname.startsWith("/chat");

  return (
    <aside className="hidden w-64 shrink-0 flex-col border-r border-outline-variant bg-surface py-stack-md px-stack-sm md:flex">
      <div className="mb-stack-lg flex items-center gap-3 px-stack-sm">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-secondary-fixed">
          <span className="material-symbols-outlined fill text-secondary">account_circle</span>
        </div>
        <div>
          <h1 className="font-display text-headline-md font-bold text-tertiary">Contextly</h1>
          <p className="font-display text-label-sm text-on-surface-variant">
            AI Document Platform
          </p>
        </div>
      </div>

      <Link
        href="/chat"
        className="mb-stack-lg flex w-full items-center justify-center gap-2 rounded-lg bg-secondary py-2 font-display text-label-md text-on-secondary shadow-sm transition-transform duration-200 hover:bg-secondary/90 active:scale-95"
      >
        <span className="material-symbols-outlined text-[18px]">add</span>
        New Conversation
      </Link>

      <nav className="flex flex-1 flex-col gap-1" aria-label="Main">
        {NAV_ITEMS.map((item) => {
          const active = item.href === "/chat" ? chatActive : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={`flex items-center gap-3 rounded-lg px-stack-sm py-2 transition-colors duration-200 ${
                active
                  ? "border-r-2 border-secondary bg-surface-container-low font-bold text-secondary"
                  : "text-on-surface-variant hover:bg-surface-container"
              }`}
            >
              <span
                className={`material-symbols-outlined text-[20px] ${
                  active ? "fill text-secondary" : "group-hover:text-secondary"
                }`}
              >
                {item.icon}
              </span>
              <span className="font-display text-label-md">{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto flex flex-col gap-1 border-t border-surface-variant pt-stack-md">
        <p className="mb-2 px-stack-sm font-display text-label-sm uppercase tracking-wider text-on-surface-variant">
          Recent
        </p>
        {recent.length === 0 ? (
          <p className="px-stack-sm py-2 text-label-sm text-on-surface-variant">
            No conversations yet
          </p>
        ) : (
          recent.map((conversation) => (
            <Link
              key={conversation.id}
              href={`/chat/${conversation.id}`}
              className="flex items-center gap-3 rounded-lg px-stack-sm py-2 text-on-surface-variant transition-colors duration-200 hover:bg-surface-container"
            >
              <span className="material-symbols-outlined text-[20px]">history</span>
              <span className="font-display text-label-md truncate">{conversation.title}</span>
            </Link>
          ))
        )}

        <div className="mt-2 flex items-center gap-2.5 rounded-lg bg-surface-container-low px-stack-sm py-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-secondary">
            <span className="material-symbols-outlined fill text-sm text-on-secondary">person</span>
          </span>
          <p className="min-w-0 flex-1 truncate text-label-sm text-on-surface">{email || "Signed in"}</p>
          <button
            type="button"
            onClick={() => void signOutLocally()}
            title="Sign out"
            className="rounded p-1 text-on-surface-variant transition-colors hover:bg-surface-container hover:text-secondary"
          >
            <span className="material-symbols-outlined text-sm">logout</span>
          </button>
        </div>
      </div>
    </aside>
  );
}