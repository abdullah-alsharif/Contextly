# Frontend Design System

Source material: `designs/design-system.md` (token spec) and
`designs/prototypes/chat.html` + `designs/prototypes/dashboard.html` (interactive
reference UI). This doc is the implementable distillation for the Next.js/Tailwind
app — what the prototypes are on About, and how they map to real components.

## 1. Design position

The brand is **authoritative, precise, unobtrusive**: the user's documents and the
AI's answers are the focal point, not the chrome. Style is **Modern Corporate** —
functional density over decorative whitespace, tonal layering instead of heavy
shadows, clear interactive states. The UI should feel like a calibrated instrument.

## 2. Design tokens (adopt verbatim into `tailwind.config.ts`)

Comprehensive token tables (colors incl. surfaces, typography scale, 4px spacing,
radii, elevation) live in `designs/design-system.md`. The parts we adopt without
change:

- **Type:** headings/labels/data in **Geist** (medium/600+), body + document content
  in **Inter**. Body text is deep slate `#1E293B`, not pure black.
- **Grid:** 4px base; stack-sm 8, stack-md 16, stack-lg 24, stack-xl 48. Container max
  1440px; §32px desktop / 16px mobile.
- **Color roles:** surface = off-white `#F8FAFC`; primary (structure) `#0F172A`;
  secondary/accent `#3B82F6` (CTA, active, AI highlight — used sparingly); semantic
  status success `#10B981` / warning `#F59E0B` / error `#EF4444`.
- **Elevation:** cards are flat (1px border `#E2E8F0`, **no** shadow); only floating
  layers (popovers/dropdowns) get the medium shadow `0 10px 15px -3px rgba(0,0,0,0.1)`.
  Focus rings = 2px `#3B82F6` @ 20% opacity ("AI-readiness" glow).
- **Radius:** 0.5rem standard; 1rem for large containers; **xl (1.5rem) reserved for
  AI-generated elements** (chips, insight cards) to visually mark "machine" vs "user".
- **AI Context Bar:** persistent thin bar/row that glows subtly while the AI processes.

> The `design-system.md` file also contains a Material-3-style full palette
> (surface/highlights, fixed variants). The dark tokens are optional; MVP ships the
> light theme only.

## 3. Core components (from the prototypes → real React components)

Inventory in `frontend/components/`:

| Prototype | Component | Spec |
|---|---|---|
| Sidebar | `sidebar.tsx`, `sidebar-conversation-row.tsx` | ChatGPT-style neutral navigation: logo header (search + collapse toggle, tooltips), Documents nav row, filled "New Conversation" CTA, Pinned/Recents/Archived collapsible sections (rows: truncation, active state, hover-revealed ⋯ menu), account fixed at the bottom. **Collapsible on desktop**: a 64px icon rail (200ms width transition, choice persisted in `localStorage` `contextly:sidebar-collapsed`; medium screens start collapsed) — labels unmount, the rail keeps Logo → Documents → New Conversation → Search → Pinned/Recents/Archived section icons (expand + scroll to the section) → Avatar; hovering anywhere on the rail swaps the logo for the expand toggle; clicking rail whitespace also expands; icon-only controls show dark tooltips (`#212121` pill, hover + keyboard focus). Account trigger opens a popover (Settings / Log out with confirm) above the bottom area, Escape/outside/route-close. Mobile: off-canvas 272px drawer with backdrop. Search opens the compact popup (see row below) |
| Search popup | `conversation-search.tsx` | Compact ChatGPT-style overlay (the reference screenshot, not the workspace pattern): a **fixed** centered white panel, exactly `718px × 460px` (only clamped by the viewport — never by content), dark `black/40` overlay, click/Escape/X to close. No bordered input: the query is typed directly into the panel header — 16px `#171717` text at ~27px from the panel's left edge and ~20px from the top, 40px tall, transparent, no border/ring. Right side of the header: "Clear" (14px `#666666`, hover `#333333`, resets to the empty state, popup stays open), a 1px × 22px `#E5E5E5` divider, then an X (20px stroke-2 icon, ~40px hit area, ~24px from the right edge). No category tabs — the product has chats only. Result rows ~70px: 20px outline icon (chat-bubble `forum`; `archive` for archived conversations) at ~36px, then 14px `#202020` title + 13px `#777777` relative date (`Today` / `Yesterday` / `MMM D` / `MMM D, YYYY`) on the title line, date at the far right (~25px from the panel edge); 13px `#777777` single-line preview (ellipsis) below. Query matches get `font-weight: 600` only — no background/color. Rows are compact (`py-[15px]`, contiguous), hover `#F5F5F5`, no rounding. Empty query → "Recent" (7 suggested chats in the same rows). A search with no matches shows a row centered in the middle of the popup — a 24px search icon next to "No results" (14px `#666666`). The result area is a fixed-height region — a scrollbar appears only when content overflows. On mobile (`<768px`) the popup goes full screen: no outer padding, no border, no rounded corners (fills the whole viewport). Searching shows a 4-row shimmer skeleton (debounced 200ms, stale responses dropped); results fade in 140ms. Infinite scroll: 5 at a time, driven by a bottom sentinel (IntersectionObserver) that also backfills when a page fits without overflowing. Arrow keys rove the selection, Enter opens; clicking a row opens the conversation as-is (pinned/archived/title/messages preserved, archived rows stay archived) |
| Page title bar | `page-title-bar.tsx` | Non-chat pages get a slim `h-16` title band (border-b) with page title + subtitle — anchored to the top edge |
| Stat card | `stat-card.tsx` | Flat card, corner watermark icon @10% opacity, label-uppercase, display-lg number, trend line in accent |
| Upload zone | `upload-dropzone.tsx` | Dashed border card, hover→border-secondary, icon circle, multi-file drop with aggregate progress, duplicate 409 → equal-weight two-choice card fork: “Update existing” (reversible replace) vs “Upload under a new name” (pre-suggested `name-2.pdf`, editable). Dialog shows the current version's facts (size · date) so the choice is informed, enters with a motion-safe rise (`dialogIn`), and focus moves into it. Multi-file batches run as a queue — each duplicate gets its dialog in turn (with a "N more files waiting" note) and the remainder resumes; nothing is dropped |
| Docs table | `document-table.tsx` | Border-less rows, horizontal `1px` dividers, hover `#F8FAFC`, always-visible row actions (delete icon, inline confirm), failed rows show an always-visible Re-process action, `body-sm` density, pagination footer |
| Status badge | `status-badge.tsx` | Pill: Ready (`secondary-fixed`), Processing (spinner `sync`), Queued (`surface-container-high`), Failed (`error-container`), Outdated (`tertiary-fixed`, `history_toggle_off` — replaced by a newer upload), Deleted (`surface-container-high`) |
| Context panel | `context-panel.tsx` | Chat left panel `w-72` (desktop only, `hidden lg:flex`): "Context Selection" header with live `X of Y selected` count, document search (icon, Clear button, Escape clears), All/Selected segmented filter, contextual Select all / Deselect all (applies to the visible/filtered set, `aria-pressed` segments, `aria-live` count); lists **every ready document account-wide**, so checking adds to the conversation and unchecking removes; the conversation workspace starts on the **Selected** filter (see what's in context first, switch to All to add more), the entry page starts on All; doc rows with `picture_as_pdf` / `description` / `text_snippet` icons + filename + meta (`Uploaded · size`) + checkbox, selected rows tinted `secondary-fixed`; empty states: no ready docs / no search matches / nothing selected |
| Chat bubble | `chat-message.tsx` | AI: `surface-container-low` card, `rounded-xl rounded-tl-none`, 1px border; user: solid `secondary` bg white text; typing indicator = 3 bouncing dots + "Analyzing documents…" |
| Source quote | `source-excerpt.tsx` | In-answer quoted block: left accent bar `w-1 bg-secondary`, "Excerpt from Source" label, italic quote |
| Citation chip | `citation-chip.tsx` | `[1]` + filename, p.N — pill with `tertiary-fixed` bg + border, hover→`tertiary-fixed-dim` |
| Source viewer | `source-viewer.tsx` | Right panel `w-80`: card w/ primary-accented header `[1] filename · Page N`, excerpt with `<mark>` highlighted span, "Open Document" button (streams the PDF via a blob URL) |
| Composer | `chat-composer.tsx` | Rounded input box with "Using: …" chips (removable, `surface-container-high` pills), textarea, ghost add-documents action (opens the picker, `lg:hidden` — desktop uses the context panel), accent send button, disclaimer line "AI can make mistakes. Consider verifying important information." |
| Document picker | `document-picker.tsx` | Add-documents modal (mobile add path): ready docs NOT yet in the conversation, search + Select/Deselect all, checked rows merge into the selection on "Add (n)" (removal stays with panel/chips), Escape/backdrop/X/Cancel close, empty states (all already included / no matches) |
| Typing indicator | `typing-indicator.tsx` | three `w-2 h-2` `bg-secondary` dots, `animate-bounce` staggered 0/150/300ms |

Icon language: **Material Symbols Outlined** (FILL for active states) — already used
consistently (pdf/description/snippet per file type, `smart_toy` for AI, `person` for
user, `forum_toy` active state).

## 4. Page layouts (Next.js App Router)

### `/chat` and `/chat/:conversation_id` — three-pane workspace

```text
┌ 64 (sidebar) ───────────────────────────────────────────────────┐
│              ├ 72 context panel │ chat column (max-w-4xl) │Source viewer 80px│
│ Recent list  │ checkboxes       │ message list          │[1] excerpt + mark │
│              │                  │ composer (sticky)      │                  │
│ user chip    │                  │ disclaimer             │                  │
└──────────────┴──────────────────┴────────────────────────┴──────────────────┘
```

- Left context panel `hidden lg:flex`; Source viewer `hidden xl:flex`.
- Composer shows live "Using: [doc…]" chips mirroring the checked context panel.
- Per docs/chat.md, answers stream via SSE into `chat-message`; sources render from
  `messages.sources` (filename, page, similarity) → `citation-chip` + `source-excerpt`,
  with `source-viewer` populating on `[n]` click.

### `/documents` — dashboard

```
Header
  └ "Documents Space" (headline-lg/display-lg) + subtitle
  └ Stats bento grid (3 cards: Total Documents / Processed Chunks / Storage Used w/ bar)
  └ Upload dropzone
  └ Recent Files table (responsive, filter dropdown + view toggle, pagination)
```

Status filter maps to `GET /documents?status=…`. Upload dropzone → toast on result;
polling for `uploaded→ready` shows `status-badge` transitions and per-row progress.

### `/documents/:id` — file detail
Not in prototype; reuse `source-viewer` card + stats for chunk/page/status summary.
Skip in MVP (see mvp-scope.md) — detail view renders from `GET /documents/{id}`.

### `/login` `/register` `/settings` — not in prototypes
Use the same tokens: centered card on `background`, primary button, `rounded-lg`,
focus ring; settings reuses `sidebar` list rows + form inputs. Register captures
the display name (full name); the sidebar user chip shows the name when set
(falling back to email); `/settings` edits the name via
`PATCH /auth/me` (email is read-only).

## 5. Margins/borders conventions

- `h-screen overflow-hidden`, content region scrolls; sidebar fixed.
- The chat shell has no top bar — search lives in the sidebar (Cmd/Ctrl+K
  popup) and uploads happen on `/documents`.
- Borders `border-outline-variant` define structure; dividers in rows `#F1F5F9`.
- Row hover `#F8FAFC`, card hover `#F1F5F9` (interactive cards only).
- Icons: `text-on-surface-variant`, active→`text-secondary`.

## 6. Accessibility & density constraints
- Contrast enforced: slate body, Geist labels medium-weight.
- Interactive focus ring always visible (secondary 20% ring).
- Labels `label-sm`/`label-md` uppercase only where meaningful (section headers).
- Functional density: no decorative space; collapse panels (`lg`/`xl`) to keep
  workspace on mobile; disabled states explicit.

## 7. Notes mapping to spec database
- `source-viewer` `<mark>` highlights a sliding snippet served from
  `document_chunks.content` for the clicked `chunk_index`; sources carry
  `chunk_index` (see database.md) so this needs no extra query — payload already
  returned by `/conversations/{id}/messages`.