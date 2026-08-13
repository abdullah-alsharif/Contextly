"use client";

// Sidebar — mirrors prototypes/chat.html SideNavBar: brand header, new-chat
// CTA, nav, Recent list, user chip with confirm-then-sign-out popover.
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { getProfile, listConversations, signOutLocally, type Conversation } from "@/lib/api-client";

const NAV_ITEMS = [
  { href: "/documents", label: "Documents", icon: "description" },
  { href: "/settings", label: "Settings", icon: "settings" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const [recent, setRecent] = useState<Conversation[]>([]);
  const [fullName, setFullName] = useState<string>("");
  const [email, setEmail] = useState<string>("");
  const [confirmSignOut, setConfirmSignOut] = useState(false);
  const confirmRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (confirmSignOut) confirmRef.current?.focus({ preventScroll: true });
  }, [confirmSignOut]);

  // Recents + user chip: mount fetch + 5s poll; "profile:updated" from
  // Settings refreshes the chip immediately on save.
  useEffect(() => {
    let cancelled = false;
    const refreshProfile = () => {
      void getProfile()
        .then((profile) => {
          if (cancelled) return;
          setFullName(profile.full_name ?? "");
          setEmail(profile.email);
        })
        .catch(() => {
          // chip keeps the last known identity
        });
    };
    const onProfileUpdated = () => refreshProfile();
    window.addEventListener("profile:updated", onProfileUpdated);
    const refresh = () => {
      void listConversations()
        .then((rows) => {
          if (!cancelled) setRecent(rows.slice(0, 5));
        })
        .catch(() => {
          // sidebar renders without recents
        });
      refreshProfile();
    };
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => {
      cancelled = true;
      window.removeEventListener("profile:updated", onProfileUpdated);
      window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
          const active = pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={`flex items-center gap-3 rounded-lg px-stack-sm py-2 transition-colors duration-200 ${
                active
                  ? "bg-surface-container-low font-bold text-secondary"
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
          recent.map((conversation) => {
            const active = pathname === `/chat/${conversation.id}`;
            return (
              <Link
                key={conversation.id}
                href={`/chat/${conversation.id}`}
                aria-current={active ? "page" : undefined}
                className={`flex items-center gap-3 rounded-lg px-stack-sm py-2 transition-colors duration-200 ${
                  active
                    ? "bg-surface-container-low font-bold text-secondary"
                    : "text-on-surface-variant hover:bg-surface-container"
                }`}
              >
                <span
                  className={`material-symbols-outlined text-[20px] ${
                    active ? "fill text-secondary" : ""
                  }`}
                >
                  history
                </span>
                <span className="font-display text-label-md truncate">{conversation.title}</span>
              </Link>
            );
          }))}

        <div className="mt-2 flex items-center gap-2.5 rounded-lg bg-surface-container-low px-stack-sm py-2">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-secondary">
            <span className="material-symbols-outlined fill text-sm text-on-secondary">person</span>
          </span>
          <p className="min-w-0 flex-1 truncate text-label-sm text-on-surface">
            {fullName || email || "Signed in"}
          </p>
          <div className="relative">
            <button
              type="button"
              onClick={() => setConfirmSignOut(true)}
              title="Sign out"
              aria-label="Sign out"
              aria-expanded={confirmSignOut}
              className="rounded p-1 text-on-surface-variant transition-colors hover:bg-surface-container hover:text-secondary"
            >
              <span className="material-symbols-outlined text-sm">logout</span>
            </button>
            {confirmSignOut && (
              <div
                ref={confirmRef}
                tabIndex={-1}
                role="alertdialog"
                aria-label="Confirm sign out"
                className="dialog-in absolute bottom-full right-0 z-10 mb-2 w-52 rounded-xl border border-outline-variant bg-surface p-3 shadow-[0_10px_15px_-3px_rgba(0,0,0,0.1)] outline-none"
                onKeyDown={(event) => {
                  if (event.key === "Escape") setConfirmSignOut(false);
                }}
              >
                <p className="font-display text-label-sm font-medium text-on-surface">
                  Sign out of Contextly?
                </p>
                <p className="mt-0.5 text-label-sm text-on-surface-variant">
                  You&apos;ll need to sign in again to access your documents.
                </p>
                <div className="mt-2.5 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setConfirmSignOut(false)}
                    className="rounded-lg px-3 py-1.5 font-display text-label-sm text-on-surface-variant transition-colors hover:bg-surface-container"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() => void signOutLocally()}
                    className="rounded-lg bg-secondary px-3 py-1.5 font-display text-label-sm text-on-secondary transition-colors hover:bg-secondary/90"
                  >
                    Sign out
                  </button>
                </div>
              </div>
            )}
            </div>
          </div>
      </div>
    </aside>
  );
}