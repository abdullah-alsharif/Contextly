"use client";

// Sidebar — ChatGPT-style neutral navigation: brand + search, nav, New
// Conversation, Pinned/Recents, Archive view, account chip. Desktop column;
// mobile drawer. Search opens as a centered dialog. Palette from .sb-root
// tokens (globals.css), light/dark follow the OS.
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import ConversationSearch from "@/components/conversation-search";
import SidebarConversationRow, {
  type RowActions,
} from "@/components/sidebar-conversation-row";
import {
  deleteConversation,
  getProfile,
  listConversations,
  signOutLocally,
  updateConversation,
  type Conversation,
  type ConversationSearchResult,
} from "@/lib/api-client";

const NAV_ITEMS = [
  { href: "/documents", label: "Documents", icon: "description" },
  { href: "/settings", label: "Settings", icon: "settings" },
];

type View = "list" | "archived";

const SEARCH_RECENTS = 7;

/** Query + results preserved while a result is opened, so returning to
 * Search restores the previous experience. */
interface PreservedSearch {
  query: string;
  results: ConversationSearchResult[];
}

function Brand() {
  return (
    <div className="flex h-9 items-center gap-2">
      {/* eslint-disable-next-line @next/next/no-img-element -- small static brand mark */}
      <img src="/icon.svg" alt="" className="h-5 w-5 rounded" />
      <h1 className="font-display text-title-lg font-bold text-sb-text">Contextly</h1>
    </div>
  );
}

function NavLinks({ pathname }: { pathname: string }) {
  return (
    <nav className="flex flex-col gap-1 px-4 pb-4" aria-label="Main">
      {NAV_ITEMS.map((item) => {
        const active = pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={`flex h-10 items-center gap-3 rounded-lg px-2.5 text-sm transition-colors duration-100 md:h-9 ${
              active
                ? "bg-sb-selected font-medium text-sb-text"
                : "text-sb-text-secondary hover:bg-sb-hover hover:text-sb-text active:bg-sb-selected"
            }`}
          >
            <span className="material-symbols-outlined text-[20px] text-sb-icon" aria-hidden="true">
              {item.icon}
            </span>
            <span className="font-display text-label-md">{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

function NewChatLink() {
  return (
    <div className="px-4 pb-4">
      <Link
        href="/chat"
        className="flex h-11 w-full items-center justify-center gap-3 rounded-lg bg-sb-hover px-2.5 font-display text-label-md text-sb-text transition-colors duration-100 hover:bg-sb-selected active:bg-sb-pressed"
      >
        <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
          add
        </span>
        New Conversation
      </Link>
    </div>
  );
}

function SectionHeader({
  label,
  icon,
  open,
  count,
  onToggle,
}: {
  label: string;
  icon?: string;
  open: boolean;
  count?: number;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      className="group flex h-8 w-full items-center gap-1.5 rounded-lg px-2.5 font-display text-label-sm text-sb-text-secondary transition-colors duration-100 hover:bg-sb-hover"
    >
      {icon && (
        <span className="material-symbols-outlined text-[14px]" aria-hidden="true">
          {icon}
        </span>
      )}
      <span>{label}</span>
      <span
        className={`material-symbols-outlined text-[14px] opacity-0 transition-opacity duration-100 group-hover:opacity-100 group-focus-visible:opacity-100 ${
          open ? "rotate-90" : ""
        }`}
        aria-hidden="true"
      >
        chevron_right
      </span>
      {count !== undefined && count > 0 && (
        <span className="ml-auto rounded-full bg-sb-hover px-1.5 text-[11px] font-medium leading-4 text-sb-text-muted">
          {count}
        </span>
      )}
    </button>
  );
}

interface SidebarBodyProps {
  view: View;
  onToggleArchiveView: () => void;
  pinned: Conversation[];
  recent: Conversation[];
  archived: Conversation[];
  showPinned: boolean;
  showRecent: boolean;
  onTogglePinned: () => void;
  onToggleRecent: () => void;
  pathname: string;
  rowActions: RowActions;
  fullName: string;
  email: string;
  confirmSignOut: boolean;
  onRequestSignOut: () => void;
  onCancelSignOut: () => void;
  onSignOut: () => void;
}

function SidebarBody({
  view,
  onToggleArchiveView,
  pinned,
  recent,
  archived,
  showPinned,
  showRecent,
  onTogglePinned,
  onToggleRecent,
  pathname,
  rowActions,
  fullName,
  email,
  confirmSignOut,
  onRequestSignOut,
  onCancelSignOut,
  onSignOut,
}: SidebarBodyProps) {
  const confirmRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (confirmSignOut) confirmRef.current?.focus({ preventScroll: true });
  }, [confirmSignOut]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* §14 conversation list — the only scrollable region */}
      <div
        data-conv-scroll
        className="custom-scrollbar min-h-0 flex-1 overflow-y-auto px-4 pb-4"
      >
        {view === "archived" ? (
          <>
            <button
              type="button"
              onClick={onToggleArchiveView}
              className="flex h-10 w-full items-center gap-3 rounded-lg px-2.5 text-sm text-sb-text-secondary transition-colors duration-100 hover:bg-sb-hover hover:text-sb-text md:h-9"
            >
              <span
                className="material-symbols-outlined text-[18px] text-sb-icon"
                aria-hidden="true"
              >
                arrow_back
              </span>
              <span className="font-display text-label-md">Conversations</span>
            </button>
            <p className="px-2.5 pb-1 pt-4 font-display text-label-sm text-sb-text-muted">
              Archived{archived.length > 0 ? ` · ${archived.length}` : ""}
            </p>
            {archived.length === 0 ? (
              <p className="px-2.5 py-2 text-label-sm text-sb-text-muted">Nothing archived</p>
            ) : (
              <div className="flex flex-col gap-1">
                {archived.map((conversation) => (
                  <SidebarConversationRow
                    key={conversation.id}
                    conversation={conversation}
                    active={pathname === `/chat/${conversation.id}`}
                    archived
                    actions={rowActions}
                  />
                ))}
              </div>
            )}
          </>
        ) : (
          <>
            {pinned.length > 0 && (
              <div className="flex flex-col gap-1">
                <SectionHeader
                  label="Pinned"
                  open={showPinned}
                  onToggle={onTogglePinned}
                />
                {showPinned &&
                  pinned.map((conversation) => (
                    <SidebarConversationRow
                      key={conversation.id}
                      conversation={conversation}
                      active={pathname === `/chat/${conversation.id}`}
                      actions={rowActions}
                    />
                  ))}
              </div>
            )}

            <div className="mt-3 flex flex-col gap-1">
              <SectionHeader
                label="Recents"
                open={showRecent}
                onToggle={onToggleRecent}
              />
              {showRecent &&
                (recent.length === 0 && pinned.length === 0 ? (
                  <p className="px-2.5 py-2 text-label-sm text-sb-text-muted">
                    No conversations yet
                  </p>
                ) : (
                  recent.map((conversation) => (
                    <SidebarConversationRow
                      key={conversation.id}
                      conversation={conversation}
                      active={pathname === `/chat/${conversation.id}`}
                      actions={rowActions}
                    />
                  ))
                ))}
            </div>
          </>
        )}
      </div>

      {/* Archive — secondary navigation, fixed above the account */}
      <div className="px-4 pt-4">
        <button
          type="button"
          onClick={onToggleArchiveView}
          className={`flex h-10 w-full items-center gap-3 rounded-lg px-2.5 text-sm transition-colors duration-100 md:h-9 ${
            view === "archived"
              ? "bg-sb-selected font-medium text-sb-text"
              : "text-sb-text-secondary hover:bg-sb-hover hover:text-sb-text"
          }`}
        >
          <span className="material-symbols-outlined text-[20px] text-sb-icon" aria-hidden="true">
            archive
          </span>
          <span className="flex-1 text-left font-display text-label-md">Archived</span>
          {archived.length > 0 && (
            <span className="rounded-full bg-sb-hover px-1.5 text-[11px] font-medium leading-4 text-sb-text-muted">
              {archived.length}
            </span>
          )}
        </button>
      </div>

      {/* Account area — visually separated from the conversation list */}
      <div className="px-4 pb-4 pt-2">
        <div className="flex h-10 items-center gap-2.5 rounded-lg px-2.5 transition-colors duration-100 hover:bg-sb-hover md:h-9">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-sb-selected">
            <span className="material-symbols-outlined fill text-sm text-sb-icon" aria-hidden="true">
              person
            </span>
          </span>
          <p className="min-w-0 flex-1 truncate text-label-sm text-sb-text">
            {fullName || email || "Signed in"}
          </p>
          <div className="relative">
            <button
              type="button"
              onClick={onRequestSignOut}
              title="Sign out"
              aria-label="Sign out"
              aria-expanded={confirmSignOut}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-sb-icon transition-colors duration-100 hover:bg-sb-hover hover:text-sb-text"
            >
              <span className="material-symbols-outlined text-sm" aria-hidden="true">
                logout
              </span>
            </button>
            {confirmSignOut && (
              <div
                ref={confirmRef}
                tabIndex={-1}
                role="alertdialog"
                aria-label="Confirm sign out"
                className="dialog-in absolute bottom-full right-0 z-10 mb-2 w-52 rounded-lg border border-sb-border bg-sb-bg p-2 shadow-[0_10px_15px_-3px_rgba(0,0,0,0.1)] outline-none"
                onKeyDown={(event) => {
                  if (event.key === "Escape") onCancelSignOut();
                }}
              >
                <p className="font-display text-label-sm font-medium text-sb-text">
                  Sign out of Contextly?
                </p>
                <p className="mt-0.5 text-label-sm text-sb-text-secondary">
                  You&apos;ll need to sign in again to access your documents.
                </p>
                <div className="mt-2 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={onCancelSignOut}
                    className="h-8 rounded-md px-3 font-display text-label-sm text-sb-text-secondary transition-colors hover:bg-sb-hover"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={onSignOut}
                    className="h-8 rounded-md bg-secondary px-3 font-display text-label-sm text-on-secondary transition-colors hover:bg-secondary/90"
                  >
                    Sign out
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [archived, setArchived] = useState<Conversation[]>([]);
  const [showPinned, setShowPinned] = useState(true);
  const [showRecent, setShowRecent] = useState(true);
  const [view, setView] = useState<View>("list");
  const [fullName, setFullName] = useState<string>("");
  const [email, setEmail] = useState<string>("");
  const [confirmSignOut, setConfirmSignOut] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchPreserved, setSearchPreserved] = useState<PreservedSearch | null>(
    null,
  );
  const drawerCloseRef = useRef<HTMLButtonElement>(null);
  const searchOpenRef = useRef(false);
  searchOpenRef.current = searchOpen;

  const refresh = useCallback(async () => {
    try {
      setConversations(await listConversations());
    } catch {
      // sidebar renders without recents
    }
    try {
      setArchived(await listConversations(true));
    } catch {
      // archived section stays empty
    }
  }, []);

  // Mount fetch + 5s poll; events refresh on demand: "profile:updated"
  // (Settings save) updates the chip, "conversations:updated" the lists.
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
    const onConversationsUpdated = () => {
      if (!cancelled) void refresh();
    };
    window.addEventListener("conversations:updated", onConversationsUpdated);
    const refreshAll = () => {
      void refresh().then(() => {
        if (!cancelled) refreshProfile();
      });
    };
    refreshAll();
    const timer = window.setInterval(refreshAll, 5000);
    return () => {
      cancelled = true;
      window.removeEventListener("profile:updated", onProfileUpdated);
      window.removeEventListener("conversations:updated", onConversationsUpdated);
      window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh]);

  const patch = useCallback(
    async (id: string, body: { title?: string; pinned?: boolean; archived?: boolean }) => {
      const updated = await updateConversation(id, body);
      // Keep the open conversation page in sync without waiting for its fetch.
      window.dispatchEvent(new CustomEvent("conversations:updated"));
      setConversations((rows) =>
        rows
          .map((row) => (row.id === id ? updated : row))
          .sort((a, b) =>
            a.pinned === b.pinned ? 0 : a.pinned ? -1 : 1,
          ),
      );
      setArchived((rows) =>
        body.archived === true
          ? [updated, ...rows.filter((row) => row.id !== id)]
          : body.archived === false
            ? rows.filter((row) => row.id !== id)
            : rows.map((row) => (row.id === id ? updated : row)),
      );
      return updated;
    },
    [],
  );

  const rename = useCallback(
    (id: string, title: string) => void patch(id, { title }).catch(() => undefined),
    [patch],
  );
  const togglePin = useCallback(
    (id: string, pinned: boolean) => void patch(id, { pinned }).catch(() => undefined),
    [patch],
  );
  const archive = useCallback(
    (id: string) => void patch(id, { archived: true }).catch(() => undefined),
    [patch],
  );
  const unarchive = useCallback(
    (id: string) => void patch(id, { archived: false }).catch(() => undefined),
    [patch],
  );

  const remove = useCallback(
    (id: string) => {
      void deleteConversation(id).catch(() => undefined);
      setConversations((rows) => rows.filter((row) => row.id !== id));
      setArchived((rows) => rows.filter((row) => row.id !== id));
      if (pathname === `/chat/${id}`) router.push("/chat");
    },
    [pathname, router],
  );

  const pinned = conversations.filter((row) => row.pinned);
  const recent = conversations.filter((row) => !row.pinned);

  const rowActions: RowActions = {
    onRename: rename,
    onTogglePin: togglePin,
    onArchive: (id: string) => void (archived.some((row) => row.id === id)
      ? unarchive(id)
      : archive(id)),
    onDelete: remove,
  };

  // Search popup: opening a result preserves query + results; dismissing resets.
  const openSearch = useCallback(() => setSearchOpen(true), []);
  const closeSearch = useCallback(() => {
    setSearchPreserved(null);
    setSearchOpen(false);
  }, []);
  const openSearchResult = useCallback(
    (query: string, results: ConversationSearchResult[]) => {
      // Recents clicks carry an empty query — nothing worth preserving.
      if (query.trim()) setSearchPreserved({ query, results });
      setSearchOpen(false);
    },
    [],
  );

  // Cmd/Ctrl+K toggles search on desktop.
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "k") {
        return;
      }
      if (!window.matchMedia("(min-width: 768px)").matches) return;
      event.preventDefault();
      if (searchOpenRef.current) {
        setSearchPreserved(null);
        setSearchOpen(false);
      } else {
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Drawer closes on navigation, Escape, or overlay click. Escape inside the
  // search popup belongs to the search.
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);
  useEffect(() => {
    if (drawerOpen) closeDrawer();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);
  useEffect(() => {
    if (drawerOpen) drawerCloseRef.current?.focus({ preventScroll: true });
  }, [drawerOpen]);
  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !searchOpenRef.current) closeDrawer();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen, closeDrawer]);

  const bodyProps: SidebarBodyProps = {
    view,
    onToggleArchiveView: () => setView((current) => (current === "archived" ? "list" : "archived")),
    pinned,
    recent,
    archived,
    showPinned,
    showRecent,
    onTogglePinned: () => setShowPinned((shown) => !shown),
    onToggleRecent: () => setShowRecent((shown) => !shown),
    pathname,
    rowActions,
    fullName,
    email,
    confirmSignOut,
    onRequestSignOut: () => setConfirmSignOut(true),
    onCancelSignOut: () => setConfirmSignOut(false),
    onSignOut: () => void signOutLocally(),
  };

  return (
    <>
      {/* Desktop: persistent column */}
      <aside className="sb-root hidden w-[272px] shrink-0 flex-col border-r border-sb-border bg-sb-bg md:flex">
        <div className="flex items-center justify-between gap-2 px-4 pb-2 pt-4">
          <Brand />
          <button
            type="button"
            onClick={openSearch}
            aria-label="Search conversations"
            title="Search conversations"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-sb-icon transition-colors duration-100 hover:bg-sb-hover hover:text-sb-text"
          >
            <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
              search
            </span>
          </button>
        </div>
        <NavLinks pathname={pathname} />
        <NewChatLink />
        <SidebarBody {...bodyProps} />
      </aside>

      {/* Mobile: floating trigger + overlay drawer */}
      <button
        type="button"
        onClick={() => setDrawerOpen(true)}
        aria-label="Open navigation"
        aria-expanded={drawerOpen}
        className={`sb-root fixed left-2 top-2 z-40 flex h-8 w-8 items-center justify-center rounded-lg border border-sb-border bg-sb-bg text-sb-icon shadow-sm transition-colors duration-100 hover:bg-sb-hover hover:text-sb-text md:hidden ${
          drawerOpen ? "invisible" : ""
        }`}
      >
        <span className="material-symbols-outlined text-[20px]" aria-hidden="true">
          menu
        </span>
      </button>
      {drawerOpen && (
        <div
          className="fixed inset-0 z-50 md:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="Navigation"
        >
          <div
            className="fade-in absolute inset-0 bg-black/40"
            onClick={closeDrawer}
            aria-hidden="true"
          />
          <aside className="sb-root drawer-in absolute inset-y-0 left-0 flex w-[272px] flex-col bg-sb-bg shadow-lg">
            <div className="flex h-16 shrink-0 items-center justify-between px-4">
              <Brand />
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={openSearch}
                  aria-label="Search conversations"
                  title="Search conversations"
                  className="flex h-9 w-9 items-center justify-center rounded-lg text-sb-icon transition-colors duration-100 hover:bg-sb-hover hover:text-sb-text"
                >
                  <span className="material-symbols-outlined text-[20px]" aria-hidden="true">
                    search
                  </span>
                </button>
                <button
                  ref={drawerCloseRef}
                  type="button"
                  onClick={closeDrawer}
                  aria-label="Close navigation"
                  className="flex h-9 w-9 items-center justify-center rounded-lg text-sb-icon transition-colors duration-100 hover:bg-sb-hover hover:text-sb-text"
                >
                  <span className="material-symbols-outlined text-[20px]" aria-hidden="true">
                    close
                  </span>
                </button>
              </div>
            </div>
            <NavLinks pathname={pathname} />
            <NewChatLink />
            <SidebarBody {...bodyProps} />
          </aside>
        </div>
      )}

      {searchOpen && (
        <ConversationSearch
          initialQuery={searchPreserved?.query}
          initialResults={searchPreserved?.results}
          recents={recent.slice(0, SEARCH_RECENTS)}
          liveConversations={[...conversations, ...archived]}
          onClose={closeSearch}
          onOpenConversation={openSearchResult}
        />
      )}
    </>
  );
}
