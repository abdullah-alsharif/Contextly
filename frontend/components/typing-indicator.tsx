// Typing indicator (docs/frontend-design.md §3): three w-2 h-2 bg-secondary
// dots, animate-bounce staggered 0/150/300ms.
export default function TypingIndicator() {
  return (
    <span className="inline-flex items-center gap-1" aria-label="Thinking" role="status">
      {[0, 150, 300].map((delay) => (
        <span
          key={delay}
          className="h-2 w-2 animate-bounce rounded-full bg-secondary"
          style={{ animationDelay: `${delay}ms` }}
        />
      ))}
    </span>
  );
}