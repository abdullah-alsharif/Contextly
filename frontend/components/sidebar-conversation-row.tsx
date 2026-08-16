"use client";

// Sidebar conversation row: [title + hover-revealed pin/⋮ suffixes] with a
// context menu (rename/pin/archive/delete). Suffixes sit in flow at the end
// of the label: hidden they reserve no width, on hover they slide in and the
// title truncates earlier, so icons never cover text. The menu flips upward
// near the list bottom so it never clips.
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import type { Conversation } from "@/lib/api-client";

export interface RowActions {
  onRename: (id: string, title: string) => void;
  onTogglePin: (id: string, pinned: boolean) => void;
  onArchive: (id: string) => void;
  onDelete: (id: string) => void;
}

// 4 items × 36px + 8px vertical padding + 2px border + 4px gap.
const MENU_ESTIMATE = 160;

// Shared hover-reveal suffix: collapsed to zero width, expands on row hover
// (or keyboard focus / menu open) so the title truncates earlier instead of
// being covered by the icons.
const suffixBase =
  "flex shrink-0 items-center justify-center overflow-hidden whitespace-nowrap rounded-md text-sb-icon transition-[margin,width,opacity] duration-150 hover:bg-sb-hover hover:text-sb-text focus-visible:opacity-100";
const suffixPin =
  "ml-1 w-[18px] p-0.5 md:ml-0 md:w-0 md:opacity-0 md:group-hover:ml-1 md:group-hover:w-[18px] md:group-hover:opacity-100 md:group-focus-visible:ml-1 md:group-focus-visible:w-[18px] md:group-focus-visible:opacity-100";
const suffixMenu =
  "ml-1 w-7 p-1.5 md:ml-0 md:w-0 md:opacity-0 md:group-hover:ml-1 md:group-hover:w-7 md:group-hover:opacity-100 md:group-focus-visible:ml-1 md:group-focus-visible:w-7 md:group-focus-visible:opacity-100";

export default function SidebarConversationRow({
  conversation,
  active,
  archived,
  actions,
}: {
  conversation: Conversation;
  active: boolean;
  archived?: boolean;
  actions: RowActions;
}) {
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [openUp, setOpenUp] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const rowRef = useRef<HTMLDivElement>(null);
  const deleteRef = useRef<HTMLButtonElement>(null);
  const cancelledRef = useRef(false);

  useEffect(() => {
    if (renaming) {
      // A fresh rename session clears any pending cancel (ref guard below).
      cancelledRef.current = false;
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [renaming]);

  useEffect(() => {
    if (confirmingDelete) deleteRef.current?.focus();
  }, [confirmingDelete]);

  const commitRename = () => {
    if (cancelledRef.current) {
      cancelledRef.current = false;
      return;
    }
    const title = draft.trim();
    if (title && title !== conversation.title) {
      actions.onRename(conversation.id, title);
    }
    setRenaming(false);
  };

  const cancelRename = () => {
    cancelledRef.current = true;
    setRenaming(false);
  };

  const toggleMenu = () => {
    if (menuOpen) {
      setMenuOpen(false);
      return;
    }
    const row = rowRef.current;
    const container = row?.closest<HTMLElement>("[data-conv-scroll]");
    if (row && container) {
      const rowRect = row.getBoundingClientRect();
      const containerRect = container.getBoundingClientRect();
      setOpenUp(rowRect.bottom + MENU_ESTIMATE > containerRect.bottom);
    }
    setMenuOpen(true);
  };

  const rowClass = `group flex h-10 items-center rounded-lg px-2.5 text-sm transition-colors duration-100 md:h-9 ${
    active
      ? "bg-sb-selected font-medium text-sb-text"
      : "text-sb-text hover:bg-sb-hover active:bg-sb-selected"
  }`;

  const body = renaming ? (
    <input
      ref={inputRef}
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onKeyDown={(event) => {
        if (event.key === "Enter") commitRename();
        if (event.key === "Escape") cancelRename();
      }}
      onBlur={commitRename}
      aria-label="Rename conversation"
      className="min-w-0 flex-1 rounded-md border border-sb-input-border bg-sb-input-bg px-2 py-1 text-sm text-sb-text outline-none focus:ring-1 focus:ring-secondary"
    />
  ) : (
    <span className="min-w-0 flex-1 truncate">{conversation.title}</span>
  );

  return (
    <div ref={rowRef} className="relative">
      {renaming ? (
        <div className={rowClass}>{body}</div>
      ) : (
        <Link
          href={`/chat/${conversation.id}`}
          aria-current={active ? "page" : undefined}
          className={rowClass}
        >
          {body}
          {!archived && (
            <button
              type="button"
              title={conversation.pinned ? "Unpin" : "Pin"}
              aria-label={`${conversation.pinned ? "Unpin" : "Pin"} ${conversation.title}`}
              onClick={(event) => {
                event.preventDefault();
                actions.onTogglePin(conversation.id, !conversation.pinned);
              }}
              className={`${suffixBase} ${suffixPin}`}
            >
              <span
                className="material-symbols-outlined text-[12px]"
                aria-hidden="true"
              >
                {conversation.pinned ? "keep_off" : "push_pin"}
              </span>
            </button>
          )}
          <button
            type="button"
            title="Conversation options"
            aria-label={`Options for ${conversation.title}`}
            aria-expanded={menuOpen}
            onClick={(event) => {
              event.preventDefault();
              toggleMenu();
            }}
            className={`${suffixBase} ${suffixMenu} ${
              menuOpen ? "bg-sb-hover text-sb-text md:ml-1 md:w-7 md:opacity-100" : ""
            }`}
          >
            <span
              className="material-symbols-outlined text-[16px]"
              aria-hidden="true"
            >
              more_vert
            </span>
          </button>
        </Link>
      )}

      {menuOpen && (
        <>
          <div
            className="fixed inset-0 z-20"
            onClick={() => setMenuOpen(false)}
            aria-hidden="true"
          />
          <div
            role="menu"
            className={`menu-in absolute right-0 z-30 w-40 rounded-lg border border-sb-border bg-sb-bg p-2 shadow-[0_10px_15px_-3px_rgba(0,0,0,0.1)] ${
              openUp ? "bottom-full mb-1" : "top-full mt-1"
            }`}
            onKeyDown={(event) => {
              if (event.key === "Escape") setMenuOpen(false);
            }}
          >
            {[
              ...(archived
                ? []
                : [
                    {
                      label: "Rename",
                      icon: "edit",
                      run: () => {
                        setDraft(conversation.title);
                        setMenuOpen(false);
                        setRenaming(true);
                      },
                    },
                    {
                      label: conversation.pinned ? "Unpin" : "Pin",
                      icon: conversation.pinned ? "keep_off" : "push_pin",
                      run: () => {
                        actions.onTogglePin(conversation.id, !conversation.pinned);
                        setMenuOpen(false);
                      },
                    },
                  ]),
              {
                label: archived ? "Unarchive" : "Archive",
                icon: archived ? "unarchive" : "archive",
                run: () => {
                  actions.onArchive(conversation.id);
                  setMenuOpen(false);
                },
              },
              {
                label: "Delete",
                icon: "delete",
                danger: true,
                run: () => {
                  setConfirmingDelete(true);
                  setMenuOpen(false);
                },
              },
            ].map((item) => (
              <button
                key={item.label}
                type="button"
                role="menuitem"
                onClick={item.run}
                className={`flex h-9 w-full items-center gap-2.5 rounded-md px-2.5 text-left font-display text-[13px] font-medium transition-colors duration-100 ${
                  item.danger
                    ? "text-error hover:bg-error-container/50"
                    : "text-sb-text hover:bg-sb-hover"
                }`}
              >
                <span
                  className="material-symbols-outlined text-[16px]"
                  aria-hidden="true"
                >
                  {item.icon}
                </span>
                {item.label}
              </button>
            ))}
          </div>
        </>
      )}

      {confirmingDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div
            className="absolute inset-0 bg-black/25"
            onClick={() => setConfirmingDelete(false)}
            aria-hidden="true"
          />
          <div
            role="alertdialog"
            aria-label="Delete conversation"
            className="dialog-in relative w-72 rounded-lg border border-sb-border bg-sb-bg p-3 shadow-[0_10px_15px_-3px_rgba(0,0,0,0.1)] outline-none"
            onKeyDown={(event) => {
              if (event.key === "Escape") setConfirmingDelete(false);
            }}
          >
            <p className="font-display text-sm font-medium text-sb-text">
              Delete chat?
            </p>
            <p className="mt-0.5 text-[13px] text-sb-text-secondary">
              This conversation will be permanently removed.
            </p>
            <div className="mt-2.5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmingDelete(false)}
                className="h-8 rounded-md px-3 font-display text-label-sm text-sb-text-secondary transition-colors hover:bg-sb-hover"
              >
                Cancel
              </button>
              <button
                ref={deleteRef}
                type="button"
                onClick={() => actions.onDelete(conversation.id)}
                className="h-8 rounded-md bg-error px-3 font-display text-label-sm text-white transition-colors hover:bg-error/80"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}