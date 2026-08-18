// Stat card (docs/frontend-design.md §3): flat card, watermark icon @10%,
// uppercase label, display-lg number. Mobile: compact 2-up strip (no
// watermark/hint) so the dropzone and file list stay above the fold.
interface StatCardProps {
  label: string;
  value: string;
  icon: string;
  hint?: string;
}

export default function StatCard({ label, value, icon, hint }: StatCardProps) {
  return (
    <div className="relative overflow-hidden rounded-xl border border-outline-variant bg-surface p-3 sm:p-stack-lg">
      <span
        aria-hidden="true"
        className="pointer-events-none absolute -right-2 -top-2 hidden sm:block"
      >
        <span className="material-symbols-outlined text-6xl leading-none text-secondary opacity-10">
          {icon}
        </span>
      </span>
      <p className="truncate font-display text-label-sm uppercase tracking-wider text-on-surface-variant">
        {label}
      </p>
      <p className="mt-0.5 font-display text-lg font-bold leading-none tabular-nums text-primary sm:mt-1 sm:text-display-lg">
        {value}
      </p>
      {hint && (
        <p className="mt-stack-sm hidden font-display text-label-sm text-on-surface-variant sm:block">
          {hint}
        </p>
      )}
    </div>
  );
}