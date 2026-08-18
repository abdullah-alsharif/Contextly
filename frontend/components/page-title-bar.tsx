// Slim h-16 title band for non-chat pages. Mobile left padding clears the
// floating sidebar trigger (same safe-area offset + 52px button).
export default function PageTitleBar({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="sticky top-0 z-10 flex h-16 shrink-0 items-center gap-3 border-b border-outline-variant bg-surface py-stack-sm pl-[calc(max(0.75rem,env(safe-area-inset-left))+3.25rem)] pr-4 md:px-8">
      <h1 className="font-display text-title-lg text-on-surface">{title}</h1>
      {subtitle && (
        <p className="hidden text-body-sm text-on-surface-variant md:block">
          {subtitle}
        </p>
      )}
    </div>
  );
}
