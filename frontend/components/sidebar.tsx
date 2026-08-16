"use client";

// ChatGPT-style sidebar (docs/frontend-design.md §2): logo header with search
// + collapse, Documents, New Conversation, Pinned/Recents/Archived, account.
// Desktop collapses to a 64px icon rail; mobile gets an overlay drawer.
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import ConversationSearch from "@/components/conversation-search";
import SidebarConversationRow, {
  type RowActions,
} from "@/components/sidebar-conversation-row";
import Tooltip from "@/components/tooltip";
import {
  deleteConversation,
  getProfile,
  listConversations,
  signOutLocally,
  updateConversation,
  type Conversation,
  type ConversationSearchResult,
} from "@/lib/api-client";

const SEARCH_RECENTS = 7;
const SIDEBAR_COLLAPSED_KEY = "contextly:sidebar-collapsed";

// Kept while a result is open so returning to Search restores it.
interface PreservedSearch {
  query: string;
  results: ConversationSearchResult[];
}

function Brand() {
  return (
    <div className="flex h-9 items-center gap-2 pl-2.5">
      {/* eslint-disable-next-line @next/next/no-img-element -- small static brand mark */}
      <img src="/icon.svg" alt="" className="h-6 w-6 rounded" />
      <h1 className="font-display text-title-lg font-bold text-sb-text">Contextly</h1>
    </div>
  );
}

// Collapsed rail mark: hovering the rail swaps it for the expand toggle.
function RailLogo({ onExpand }: { onExpand: () => void }) {
  return (
    <div className="group relative flex h-10 w-10 items-center justify-center rounded-lg transition-colors duration-150 hover:bg-sb-hover">
      {/* eslint-disable-next-line @next/next/no-img-element -- small static brand mark */}
      <img
        src="/icon.svg"
        alt=""
        className="h-6 w-6 rounded transition-opacity duration-150 group-hover/sidebar:opacity-0"
      />
      <button
        type="button"
        onClick={onExpand}
        aria-label="Expand sidebar"
        className="absolute inset-0 flex items-center justify-center rounded-lg text-sb-icon opacity-0 transition-opacity duration-150 hover:text-sb-text focus-visible:opacity-100 group-hover/sidebar:opacity-100"
      >
        <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
          left_panel_open
        </span>
      </button>
      <Tooltip label="Expand sidebar" />
    </div>
  );
}

// Icon-only control with a tooltip; lg is the rail's 40px hit area, sm the
// header/drawer buttons.
function IconButton({
  label,
  tooltip,
  icon,
  onClick,
  href,
  className,
  size = "sm",
}: {
  label: string;
  tooltip?: string;
  icon: string;
  onClick?: () => void;
  href?: string;
  className?: string;
  size?: "sm" | "lg";
}) {
  const classes = `flex ${
    size === "lg" ? "h-10 w-10" : "h-8 w-8"
  } items-center justify-center rounded-lg text-sb-icon transition-colors duration-100 hover:bg-sb-hover hover:text-sb-text`;
  return (
    <div className={`group relative ${className ?? ""}`}>
      {href ? (
        <Link href={href} aria-label={label} className={classes}>
          <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
            {icon}
          </span>
        </Link>
      ) : (
        <button type="button" onClick={onClick} aria-label={label} className={classes}>
          <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
            {icon}
          </span>
        </button>
      )}
      <Tooltip label={tooltip ?? label} />
    </div>
  );
}

function DocumentsLink({ pathname }: { pathname: string }) {
  return (
    <div className="mt-2 flex flex-col gap-1 px-4 pb-2">
      <Link
        href="/documents"
        aria-current={pathname === "/documents" ? "page" : undefined}
        className={`flex h-10 items-center gap-3 rounded-lg px-2.5 text-sm transition-colors duration-100 md:h-9 ${
          pathname === "/documents"
            ? "bg-sb-selected font-medium text-sb-text"
            : "text-sb-text-secondary hover:bg-sb-hover hover:text-sb-text active:bg-sb-selected"
        }`}
      >
        <span className="material-symbols-outlined text-[20px] text-sb-icon" aria-hidden="true">
          description
        </span>
        <span className="font-display text-label-md">Documents</span>
      </Link>
    </div>
  );
}

function NewChatLink({ collapsed }: { collapsed: boolean }) {
  return (
    <div className={collapsed ? "px-2 pb-4" : "px-4 pb-4"}>
      <div className="group relative">
        <Link
          href="/chat"
          aria-label={collapsed ? "New Conversation" : undefined}
          className={`flex h-11 w-full items-center gap-3 rounded-lg bg-sb-hover px-2.5 font-display text-label-md text-sb-text transition-colors duration-100 hover:bg-sb-selected active:bg-sb-pressed ${
            collapsed ? "justify-center" : ""
          }`}
        >
          <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
            add
          </span>
          {!collapsed && <span>New Conversation</span>}
        </Link>
        {collapsed && <Tooltip label="New Conversation" />}
      </div>
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
      {count !== undefined && count > 0 && (
        <span className="ml-auto rounded-full bg-sb-hover px-1.5 text-[11px] font-medium leading-4 text-sb-text-muted">
          {count}
        </span>
      )}
      <span
        className={`material-symbols-outlined text-[14px] opacity-0 transition-opacity duration-100 group-hover:opacity-100 group-focus-visible:opacity-100 ${
          open ? "rotate-90" : ""
        } ${count === undefined || count === 0 ? "ml-auto" : ""}`}
        aria-hidden="true"
      >
        chevron_right
      </span>
    </button>
  );
}

// Account trigger + popover (Settings / Log out): anchors up when expanded,
// beside the rail when collapsed; Escape/outside/route changes close it.
function AccountMenu({
  collapsed,
  fullName,
  email,
  pathname,
  onSignOut,
}: {
  collapsed: boolean;
  fullName: string;
  email: string;
  pathname: string;
  onSignOut: () => void;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close the profile menu when navigating away (derived during render).
  const [prevPathname, setPrevPathname] = useState(pathname);
  if (pathname !== prevPathname) {
    setPrevPathname(pathname);
    setOpen(false);
    setConfirming(false);
  }

  useEffect(() => {
    if (open) menuRef.current?.focus({ preventScroll: true });
  }, [open]);

  const close = () => {
    setConfirming(false);
    setOpen(false);
  };

  const trigger = collapsed ? (
    <div className="group relative">
      <button
        type="button"
        onClick={() => setOpen((shown) => !shown)}
        aria-label="Open account menu"
        aria-expanded={open}
        className="flex h-10 w-10 items-center justify-center rounded-lg transition-colors duration-100 hover:bg-sb-hover"
      >
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-sb-selected">
          <span className="material-symbols-outlined fill text-sm text-sb-icon" aria-hidden="true">
            person
          </span>
        </span>
      </button>
      <Tooltip label={fullName || email || "Account"} />
    </div>
  ) : (
    <button
      type="button"
      onClick={() => setOpen((shown) => !shown)}
      aria-label="Open account menu"
      aria-expanded={open}
      className={`flex h-10 w-full items-center gap-2.5 rounded-lg px-2.5 transition-colors duration-100 hover:bg-sb-hover md:h-9 ${
        open ? "bg-sb-hover" : ""
      }`}
    >
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-sb-selected">
        <span className="material-symbols-outlined fill text-sm text-sb-icon" aria-hidden="true">
          person
        </span>
      </span>
      <p className="min-w-0 flex-1 truncate text-left text-label-sm text-sb-text">
        {fullName || email || "Account"}
      </p>
      <span
        className={`material-symbols-outlined text-[16px] text-sb-icon transition-transform duration-150 ${
          open ? "rotate-180" : ""
        }`}
        aria-hidden="true"
      >
        expand_more
      </span>
    </button>
  );

  const menu = open ? (
    <>
      <div
        className="fixed inset-0 z-20"
        data-rail-guard
        onClick={close}
        aria-hidden="true"
      />
      <div
        ref={menuRef}
        role="menu"
        data-rail-guard
        tabIndex={-1}
        aria-label="Account menu"
        className={`menu-in absolute z-30 rounded-lg border border-sb-border bg-sb-bg p-2 shadow-[0_10px_15px_-3px_rgba(0,0,0,0.1)] outline-none ${
          collapsed ? "bottom-0 left-full ml-2 w-56" : "bottom-full left-0 right-0 mb-2"
        }`}
        onKeyDown={(event) => {
          if (event.key === "Escape") close();
        }}
      >
        {confirming ? (
          <div>
            <p className="font-display text-label-sm font-medium text-sb-text">
              Sign out of Contextly?
            </p>
            <p className="mt-0.5 text-label-sm text-sb-text-secondary">
              You&apos;ll need to sign in again to access your documents.
            </p>
            <div className="mt-2 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirming(false)}
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
        ) : (
          <>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                close();
                router.push("/settings");
              }}
              className="flex h-9 w-full items-center gap-2.5 rounded-md px-2.5 text-left font-display text-[13px] font-medium text-sb-text transition-colors duration-100 hover:bg-sb-hover"
            >
              <span className="material-symbols-outlined text-[16px] text-sb-icon" aria-hidden="true">
                settings
              </span>
              Settings
            </button>
            <div className="mx-2 my-1 h-px bg-sb-border" />
            <button
              type="button"
              role="menuitem"
              onClick={() => setConfirming(true)}
              className="flex h-9 w-full items-center gap-2.5 rounded-md px-2.5 text-left font-display text-[13px] font-medium text-error transition-colors duration-100 hover:bg-error-container/50"
            >
              <span className="material-symbols-outlined text-[16px]" aria-hidden="true">
                logout
              </span>
              Log out
            </button>
          </>
        )}
      </div>
    </>
  ) : null;

  return (
    <div className={`relative ${collapsed ? "" : "w-full"}`}>
      {trigger}
      {menu}
    </div>
  );
}

interface SidebarBodyProps {
  pinned: Conversation[];
  recent: Conversation[];
  archived: Conversation[];
  showPinned: boolean;
  showRecent: boolean;
  showArchived: boolean;
  onTogglePinned: () => void;
  onToggleRecent: () => void;
  onToggleArchived: () => void;
  pathname: string;
  rowActions: RowActions;
  fullName: string;
  email: string;
  onSignOut: () => void;
  collapsed: boolean;
}

function SidebarBody({
  pinned,
  recent,
  archived,
  showPinned,
  showRecent,
  showArchived,
  onTogglePinned,
  onToggleRecent,
  onToggleArchived,
  pathname,
  rowActions,
  fullName,
  email,
  onSignOut,
  collapsed,
}: SidebarBodyProps) {
  return (
    <div
      className={`flex min-h-0 flex-1 flex-col ${
        collapsed ? "justify-end gap-1" : ""
      }`}
    >
      {!collapsed && (
        <div
          data-conv-scroll
          className="custom-scrollbar min-h-0 flex-1 overflow-y-auto px-4 pb-4"
        >
          {pinned.length > 0 && (
            <div data-section="pinned" className="flex flex-col gap-1">
              <SectionHeader label="Pinned" open={showPinned} onToggle={onTogglePinned} />
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

          <div data-section="recent" className="mt-4 flex flex-col gap-1">
            <SectionHeader label="Recents" open={showRecent} onToggle={onToggleRecent} />
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

          <div data-section="archived" className="mt-4 flex flex-col gap-1">
            <SectionHeader
              label="Archived"
              icon="archive"
              open={showArchived}
              count={archived.length}
              onToggle={onToggleArchived}
            />
            {showArchived &&
              (archived.length === 0 ? (
                <p className="px-2.5 py-2 text-label-sm text-sb-text-muted">Nothing archived</p>
              ) : (
                archived.map((conversation) => (
                  <SidebarConversationRow
                    key={conversation.id}
                    conversation={conversation}
                    active={pathname === `/chat/${conversation.id}`}
                    archived
                    actions={rowActions}
                  />
                ))
              ))}
          </div>
        </div>
      )}

      {/* Bottom cluster — account, fixed */}
      <div
        className={
          collapsed
            ? "flex flex-col items-center px-2 pb-3"
            : "flex flex-col px-4 pb-4 pt-2"
        }
      >
        <AccountMenu
          collapsed={collapsed}
          fullName={fullName}
          email={email}
          pathname={pathname}
          onSignOut={onSignOut}
        />
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
  const [showArchived, setShowArchived] = useState(false);
  const [fullName, setFullName] = useState<string>("");
  const [email, setEmail] = useState<string>("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  // Client-only (localStorage, innerWidth): applied on mount to avoid a
  // hydration mismatch with the server's expanded render.
  const [collapsed, setCollapsed] = useState(false);
  const [searchPreserved, setSearchPreserved] = useState<PreservedSearch | null>(
    null,
  );
  const drawerCloseRef = useRef<HTMLButtonElement>(null);
  const searchOpenRef = useRef(false);
  useEffect(() => {
    searchOpenRef.current = searchOpen;
  }, [searchOpen]);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? "1" : "0");
      } catch {
        // storage unavailable — the toggle still works for the session
      }
      return next;
    });
  }, []);

  // Apply the persisted preference (or medium-screen rule) after hydration.
  useEffect(() => {
    // Deferred out of the synchronous effect path; runs right after paint.
    const frame = window.requestAnimationFrame(() => {
      let stored: string | null = null;
      try {
        stored = window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
      } catch {
        // fall back to the viewport rule
      }
      setCollapsed(stored !== null ? stored === "1" : window.innerWidth < 1024);
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

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
  const recent = conversations.filter((row) => !row.pinned && row.message_count > 0);

  const rowActions: RowActions = {
    onRename: rename,
    onTogglePin: togglePin,
    onArchive: (id: string) => void (archived.some((row) => row.id === id)
      ? unarchive(id)
      : archive(id)),
    onDelete: remove,
  };

  // Search: opening a result preserves query + results; dismissing resets.
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

  // Drawer closes on navigation (derived during render), Escape, or overlay
  // click; Escape inside the search popup stays with it.
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);
  const [prevNavPathname, setPrevNavPathname] = useState(pathname);
  if (pathname !== prevNavPathname) {
    setPrevNavPathname(pathname);
    setDrawerOpen(false);
  }
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

  // Rail icons: expand and open the target section, then scroll to it.
  const focusSection = useCallback((name: "pinned" | "recent" | "archived") => {
    setCollapsed(false);
    setShowPinned(true);
    setShowRecent(true);
    setShowArchived(true);
    window.setTimeout(() => {
      document
        .querySelector<HTMLElement>(`[data-section="${name}"]`)
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 220);
  }, []);

  const bodyProps: SidebarBodyProps = {
    pinned,
    recent,
    archived,
    showPinned,
    showRecent,
    showArchived,
    onTogglePinned: () => setShowPinned((shown) => !shown),
    onToggleRecent: () => setShowRecent((shown) => !shown),
    onToggleArchived: () => setShowArchived((shown) => !shown),
    pathname,
    rowActions,
    fullName,
    email,
    onSignOut: () => void signOutLocally(),
    collapsed,
  };

  return (
    <>
      {/* Desktop: collapsible column */}
      <aside
        className={`sb-root group/sidebar hidden shrink-0 flex-col border-r border-sb-border bg-sb-bg transition-[width] duration-200 md:flex ${
          collapsed ? "w-16" : "w-[272px]"
        }`}
        onClick={(event) => {
          // Rail whitespace (not a control or popover) expands the sidebar.
          if (!collapsed) return;
          const target = event.target as HTMLElement;
          if (target.closest("a, button, [data-rail-guard]")) return;
          toggleCollapsed();
        }}
      >
        {collapsed ? (
          <div className="flex flex-col items-center gap-2 px-2 pb-2 pt-3">
            <RailLogo onExpand={toggleCollapsed} />
            <IconButton size="lg" href="/documents" label="Documents" icon="description" />
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2 px-4 pb-2 pt-4">
            <Brand />
            <div className="flex items-center gap-2">
              <IconButton
                label="Search conversations"
                tooltip="Search chats"
                icon="search"
                onClick={openSearch}
              />
              <IconButton
                label="Collapse sidebar"
                icon="left_panel_close"
                onClick={toggleCollapsed}
              />
            </div>
          </div>
        )}
        {!collapsed && <DocumentsLink pathname={pathname} />}
        <NewChatLink collapsed={collapsed} />
        {collapsed && (
          <div className="flex flex-col items-center gap-2 px-2">
            <IconButton
              size="lg"
              label="Search conversations"
              tooltip="Search chats"
              icon="search"
              onClick={openSearch}
            />
            <IconButton
              size="lg"
              label="Pinned"
              icon="push_pin"
              onClick={() => focusSection("pinned")}
            />
            <IconButton
              size="lg"
              label="Recents"
              icon="history"
              onClick={() => focusSection("recent")}
            />
            <IconButton
              size="lg"
              label="Archived"
              icon="archive"
              onClick={() => focusSection("archived")}
            />
          </div>
        )}
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
                <IconButton
                  label="Search conversations"
                  tooltip="Search chats"
                  icon="search"
                  onClick={openSearch}
                />
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
            <DocumentsLink pathname={pathname} />
            <NewChatLink collapsed={false} />
            <SidebarBody {...bodyProps} collapsed={false} />
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
