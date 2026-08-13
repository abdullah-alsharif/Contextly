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
| Sidebar | `sidebar.tsx` | `w-64`, brand header, "New Conversation" primary CTA (chat is entered through it — no separate Chat nav item), nav (Documents / Settings), footer "Recent" list + user chip |
| Top bar | `topbar.tsx` | Chat-only (rendered by the nested `chat/layout.tsx`): search field (rounded, focus ring) + Upload button; absent on Documents and Settings pages |
| Page title bar | `page-title-bar.tsx` | Non-chat pages get a slim `h-16` title band (border-b, same horizontal rhythm as the topbar) with page title + subtitle — anchored top edge without the chat controls |
| Stat card | `stat-card.tsx` | Flat card, corner watermark icon @10% opacity, label-uppercase, display-lg number, trend line in accent |
| Upload zone | `upload-dropzone.tsx` | Dashed border card, hover→border-secondary, icon circle, multi-file drop with aggregate progress, duplicate 409 → equal-weight two-choice card fork: “Update existing” (reversible replace) vs “Upload under a new name” (pre-suggested `name-2.pdf`, editable). Dialog shows the current version's facts (size · date) so the choice is informed, enters with a motion-safe rise (`dialogIn`), and focus moves into it. Multi-file batches run as a queue — each duplicate gets its dialog in turn (with a "N more files waiting" note) and the remainder resumes; nothing is dropped |
| Docs table | `document-table.tsx` | Border-less rows, horizontal `1px` dividers, hover `#F8FAFC`, always-visible row actions (delete icon, inline confirm), failed rows show an always-visible Re-process action, `body-sm` density, pagination footer |
| Status badge | `status-badge.tsx` | Pill: Ready (`secondary-fixed`), Processing (spinner `sync`), Queued (`surface-container-high`), Failed (`error-container`), Outdated (`tertiary-fixed`, `history_toggle_off` — replaced by a newer upload), Deleted (`surface-container-high`) |
| Context panel | `context-panel.tsx` | Chat left panel `w-72`: "Context Selection", doc rows with `picture_as_pdf` / `description` / `text_snippet` icons + filename + meta (`Uploaded · size`) + checkbox |
| Chat bubble | `chat-message.tsx` | AI: `surface-container-low` card, `rounded-xl rounded-tl-none`, 1px border; user: solid `secondary` bg white text; typing indicator = 3 bouncing dots + "Analyzing documents…" |
| Source quote | `source-excerpt.tsx` | In-answer quoted block: left accent bar `w-1 bg-secondary`, "Excerpt from Source" label, italic quote |
| Citation chip | `citation-chip.tsx` | `[1]` + filename, p.N — pill with `tertiary-fixed` bg + border, hover→`tertiary-fixed-dim` |
| Source viewer | `source-viewer.tsx` | Right panel `w-80`: card w/ primary-accented header `[1] filename · Page N`, excerpt with `<mark>` highlighted span, "Open Document" button (streams the PDF via a blob URL) |
| Composer | `chat-composer.tsx` | Rounded input box with "Using: …" chips (removable, `surface-container-high` pills), textarea, attach/voice ghost actions, accent send button, disclaimer line "AI can make mistakes. Consider verifying important information." |
| Typing indicator | `typing-indicator.tsx` | three `w-2 h-2` `bg-secondary` dots, `animate-bounce` staggered 0/150/300ms |

Icon language: **Material Symbols Outlined** (FILL for active states) — already used
consistently (pdf/description/snippet per file type, `smart_toy` for AI, `person` for
user, `forum_toy` active state).

## 4. Page layouts (Next.js App Router)

### `/chat` and `/chat/:conversation_id` — three-pane workspace

```text
┌ 64 (sidebar) ┬ topbar ─────────────────────────────────────────────┐
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
focus ring; settings reuses `sidebar` list rows + form inputs.

## 5. Margins/borders conventions

- `h-screen overflow-hidden`, content region scrolls; sidebar+topbar fixed.
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