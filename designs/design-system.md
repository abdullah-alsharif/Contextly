---
name: Modern Enterprise AI
colors:
  surface: '#f7f9fb'
  surface-dim: '#d8dadc'
  surface-bright: '#f7f9fb'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f4f6'
  surface-container: '#eceef0'
  surface-container-high: '#e6e8ea'
  surface-container-highest: '#e0e3e5'
  on-surface: '#191c1e'
  on-surface-variant: '#45464d'
  inverse-surface: '#2d3133'
  inverse-on-surface: '#eff1f3'
  outline: '#76777d'
  outline-variant: '#c6c6cd'
  surface-tint: '#565e74'
  primary: '#000000'
  on-primary: '#ffffff'
  primary-container: '#131b2e'
  on-primary-container: '#7c839b'
  inverse-primary: '#bec6e0'
  secondary: '#0058be'
  on-secondary: '#ffffff'
  secondary-container: '#2170e4'
  on-secondary-container: '#fefcff'
  tertiary: '#000000'
  on-tertiary: '#ffffff'
  tertiary-container: '#0b1c30'
  on-tertiary-container: '#75859d'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dae2fd'
  primary-fixed-dim: '#bec6e0'
  on-primary-fixed: '#131b2e'
  on-primary-fixed-variant: '#3f465c'
  secondary-fixed: '#d8e2ff'
  secondary-fixed-dim: '#adc6ff'
  on-secondary-fixed: '#001a42'
  on-secondary-fixed-variant: '#004395'
  tertiary-fixed: '#d3e4fe'
  tertiary-fixed-dim: '#b7c8e1'
  on-tertiary-fixed: '#0b1c30'
  on-tertiary-fixed-variant: '#38485d'
  background: '#f7f9fb'
  on-background: '#191c1e'
  surface-variant: '#e0e3e5'
typography:
  display-lg:
    fontFamily: Geist
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Geist
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Geist
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  title-lg:
    fontFamily: Geist
    fontSize: 20px
    fontWeight: '500'
    lineHeight: 28px
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-sm:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-md:
    fontFamily: Geist
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
    letterSpacing: 0.01em
  label-sm:
    fontFamily: Geist
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.02em
  headline-lg-mobile:
    fontFamily: Geist
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 4px
  container-max: 1440px
  gutter: 24px
  margin-mobile: 16px
  margin-desktop: 32px
  stack-xs: 4px
  stack-sm: 8px
  stack-md: 16px
  stack-lg: 24px
  stack-xl: 48px
---

## Brand & Style

The design system is engineered for a high-performance AI document SaaS environment. The brand personality is **authoritative, precise, and unobtrusive**, ensuring that the user’s content and the AI’s insights remain the focal point.

The style is **Modern Corporate**, blending the structural reliability of enterprise software with the fluid efficiency of modern developer tools. It prioritizes functional density over decorative whitespace, using a systematic approach to layering and clear visual signifiers for interactive states. The interface should feel like a high-end instrument: calibrated, responsive, and trustworthy.

## Colors

The palette is designed for deep focus and document legibility. 

- **Primary (#0F172A):** Used for structural navigation elements like sidebars and headers. It provides a grounded "frame" for the application.
- **Secondary/Accent (#3B82F6):** Reserved for primary calls to action, active selection states, and AI-driven highlights. It must be used sparingly to maintain its "active" meaning.
- **Background (#F8FAFC):** An off-white "Paper" tint used for the main workspace to reduce the harsh glare of pure white while maintaining high contrast for text.
- **Status Colors:** Use standard semantic tokens: Success (#10B981), Warning (#F59E0B), and Error (#EF4444) for system feedback.

## Typography

This design system utilizes a dual-font strategy. **Geist** is used for headings, labels, and technical data to provide a sharp, modern, and slightly "monospaced" feel that suggests AI precision. **Inter** is used for all body copy and document content to ensure maximum readability during long-form consumption.

Text contrast is strictly enforced. Body text should utilize a deep slate (#1E293B) rather than pure black to prevent eye fatigue while maintaining high accessibility scores. All labels should be set in medium weight to distinguish them from standard body text.

## Layout & Spacing

The layout utilizes a **Fixed-Fluid Hybrid** model. The main application shell (navigation and sidebars) is fixed, while the primary document workspace is fluid with a maximum readable width of 1440px.

A strict 4px base grid governs all spatial relationships. 
- **Desktop:** 12-column grid with 24px gutters. Use 32px outer margins for a spacious, professional feel.
- **Tablet:** 8-column grid with 16px gutters.
- **Mobile:** 4-column grid with 16px margins.

Vertical rhythm should follow the "stack" variables. Elements within a component use `stack-sm` (8px), while distinct sections on a page use `stack-xl` (48px) to create clear visual separation without the need for excessive borders.

## Elevation & Depth

Hierarchy is established through **Tonal Layering** and **Subtle Elevation**. 

1.  **Level 0 (Floor):** The off-white workspace background (#F8FAFC).
2.  **Level 1 (Card/Surface):** White (#FFFFFF) surfaces used for the primary document or content containers, featuring a 1px border (#E2E8F0) and no shadow.
3.  **Level 2 (Floating/Overlay):** Popovers, dropdowns, and context menus. These use a medium-diffusion shadow: `0 10px 15px -3px rgba(0, 0, 0, 0.1)`.
4.  **Interactive Focus:** Active inputs or focused elements use a 2px "ring" glow in the secondary color (#3B82F6) with 20% opacity to signal AI-readiness.

Avoid heavy drop shadows; use borders to define structure and shadows only to indicate temporary or floating state.

## Shapes

The shape language is **Professional-Soft**. 

- **Standard Elements:** Buttons, inputs, and small cards use a 0.5rem (8px) radius. This provides a modern, approachable feel while remaining structured.
- **Large Containers:** Main content areas or large modals use 1rem (16px) to soften the overall interface.
- **AI Components:** Elements specifically generated or controlled by AI (like suggested text or insight chips) can use the `rounded-xl` (1.5rem) setting to visually distinguish "machine" suggestions from "user" content.

## Components

### Buttons
- **Primary:** Solid #3B82F6 with white text. 8px radius. Subtle scale-down effect (0.98) on click.
- **Secondary:** Transparent with #0F172A border and text. Use for secondary actions like "Export" or "Settings".
- **Ghost:** No background or border. Used for toolbar actions to minimize visual noise.

### Inputs & Text Areas
- Use white backgrounds with #E2E8F0 borders. 
- On focus, the border transitions to #3B82F6 with a subtle 3px outer ring. 
- Labels always sit above the input in `label-sm` Geist.

### Cards
- Standard cards use a 1px solid #E2E8F0 border. 
- Avoid shadows on static cards to keep the UI "flat" and tool-like. 
- Use a slight background shift (#F1F5F9) on hover for interactive cards.

### Chips & Badges
- Used for metadata and AI tags. 
- Height: 24px. Font: `label-sm`. 
- AI-generated tags should use a subtle gradient or a light indigo background (#EFF6FF) to denote their origin.

### Lists & Data Tables
- Clean, border-less rows separated by 1px horizontal dividers (#F1F5F9). 
- Hover states should use #F8FAFC to highlight the active row. 
- Text in tables should utilize `body-sm` for high information density.

### AI Context Bar
- A specific component for this design system: a persistent, thin vertical or horizontal bar that glows slightly when the AI is "thinking" or processing document context.