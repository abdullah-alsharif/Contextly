// Dark pill for icon-only controls. Lives inside a `group` (revealed on
// hover/focus) and anchors left of it — never blocks clicks.
export default function Tooltip({ label }: { label: string }) {
  return (
    <span
      aria-hidden="true"
      className="pointer-events-none absolute left-full top-1/2 z-50 ml-2 -translate-y-1/2 whitespace-nowrap rounded-md bg-[#212121] px-2 py-1 text-xs font-medium text-[#EDEDED] opacity-0 shadow-lg transition-opacity duration-100 group-hover:opacity-100 group-focus-within:opacity-100"
    >
      {label}
    </span>
  );
}
