// Slim h-16 title band for non-chat pages — mirrors the topbar's height and
// horizontal rhythm without the search/upload controls.
export default function PageTitleBar({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="sticky top-0 z-10 flex h-16 shrink-0 items-center gap-3 border-b border-outline-variant bg-surface px-margin-desktop py-stack-sm md:px-gutter">
      <h1 className="font-display text-title-lg text-on-surface">{title}</h1>
      {subtitle && (
        <p className="hidden text-body-sm text-on-surface-variant md:block">
          {subtitle}
        </p>
      )}
    </div>
  );
}
