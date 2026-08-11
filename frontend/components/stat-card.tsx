// Stat card (docs/frontend-design.md §3): flat card, watermark icon @10%,
// uppercase label, display-lg number, accent trend line.
interface StatCardProps {
  label: string;
  value: string;
  icon: string;
  hint?: string;
  trend?: string;
  trendPositive?: boolean;
}

export default function StatCard({ label, value, icon, hint, trend, trendPositive }: StatCardProps) {
  return (
    <div className="relative overflow-hidden rounded-xl border border-outline-variant bg-surface p-stack-lg">
      <span
        aria-hidden="true"
        className="material-symbols-outlined pointer-events-none absolute -right-2 -top-2 text-6xl leading-none text-secondary opacity-10"
      >
        {icon}
      </span>
      <p className="font-display text-label-sm uppercase tracking-wider text-on-surface-variant">
        {label}
      </p>
      <p className="mt-1 font-display text-display-lg font-bold text-primary">
        {value}
      </p>
      {(trend || hint) && (
        <div className="mt-stack-sm flex items-center gap-1">
          {trend && (
            <span
              className={`font-display text-label-sm ${
                trendPositive ? "text-secondary-container" : "text-error"
              }`}
            >
              {trend}
            </span>
          )}
          {hint && (
            <span className="font-display text-label-sm text-on-surface-variant">{hint}</span>
          )}
        </div>
      )}
    </div>
  );
}