// Source excerpt (docs/frontend-design.md §3): left accent bar w-1 bg-primary,
// "Excerpt from Source" label, italic quote.
export default function SourceExcerpt({
  text,
  pageNumber,
}: {
  text: string;
  pageNumber?: number;
}) {
  return (
    <figure className="flex gap-3 rounded-lg bg-surface-container-low p-3">
      <span aria-hidden="true" className="w-1 shrink-0 rounded-full bg-primary" />
      <figcaption className="min-w-0">
        <p className="font-display text-label-sm text-primary">
          Excerpt from Source{pageNumber ? ` · Page ${pageNumber}` : ""}
        </p>
        <blockquote className="mt-1 text-body-sm italic text-ink-700">“{text}”</blockquote>
      </figcaption>
    </figure>
  );
}