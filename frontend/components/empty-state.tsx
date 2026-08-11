// Shared empty/loading state (frontend-design.md §4): icon, headline,
// hint text, optional CTA.
import Link from "next/link";

interface EmptyStateProps {
  icon: string;
  title: string;
  hint?: string;
  cta?: { label: string; href: string; icon?: string };
}

export default function EmptyState({ icon, title, hint, cta }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-3 py-16 text-center">
      <span className="material-symbols-outlined text-5xl text-on-surface-variant" aria-hidden="true">
        {icon}
      </span>
      <div>
        <p className="font-display text-headline-md text-on-surface">{title}</p>
        {hint && <p className="mt-1 max-w-sm text-body-sm text-on-surface-variant">{hint}</p>}
      </div>
      {cta && (
        <Link
          href={cta.href}
          className="mt-2 flex items-center gap-2 rounded-lg bg-secondary px-4 py-2 font-display text-label-md text-white transition-colors hover:bg-secondary-fixed-dim"
        >
          <span className="material-symbols-outlined text-label-md">{cta.icon}</span>
          {cta.label}
        </Link>
      )}
    </div>
  );
}