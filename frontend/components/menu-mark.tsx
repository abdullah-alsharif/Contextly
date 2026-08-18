// Two-line menu mark (24×24): top stroke spans most of the box, bottom stroke
// is shorter — both left-aligned. Color follows currentColor.
export default function MenuMark() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <line x1="3.5" y1="8" x2="20.5" y2="8" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" />
      <line x1="3.5" y1="16" x2="14.5" y2="16" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" />
    </svg>
  );
}
