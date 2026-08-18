// Shared empty/loading state (frontend-design.md §4): icon, headline, hint.
interface EmptyStateProps {
  icon: string;
  title: string;
  hint?: React.ReactNode;
}

export default function EmptyState({ icon, title, hint }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-3 py-10 text-center sm:py-16">
      <span className="material-symbols-outlined text-5xl text-on-surface-variant" aria-hidden="true">
        {icon}
      </span>
      <div>
        <p className="font-display text-headline-md text-on-surface">{title}</p>
        {hint && <p className="mt-1 max-w-sm text-body-sm text-on-surface-variant">{hint}</p>}
      </div>
    </div>
  );
}