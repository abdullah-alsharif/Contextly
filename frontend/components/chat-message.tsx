// Chat message — mirrors prototypes/chat.html: AI card (rounded-xl, no
// top-left radius), user solid secondary; renders `[n]` markers as chips.
"use client";

import CitationChip from "@/components/citation-chip";
import TypingIndicator from "@/components/typing-indicator";
import type { Source } from "@/lib/api-client";

const CITATION_PATTERN = /\[(\d{1,2})\]/g;

function renderWithCitations(text: string, sources: Source[], onCite: (source: Source) => void) {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  const pattern = new RegExp(CITATION_PATTERN.source, "g");
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    const n = Number(match[1]);
    const source = sources[n - 1] ?? sources[n];
    if (source) {
      parts.push(
        <CitationChip
          key={key++}
          index={n}
          source={source}
          onClick={() => onCite(source)}
        />,
      );
    } else {
      parts.push(match[0]);
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts;
}

export default function ChatMessage({
  role,
  content,
  sources,
  pending,
  failed,
  onCite,
}: {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  pending?: boolean;
  failed?: boolean;
  onCite?: (source: Source) => void;
}) {
  const isUser = role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-xl rounded-tr-none bg-secondary p-4 text-body-md text-on-secondary shadow-sm">
          {content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-3">
      <span className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary">
        <span className="material-symbols-outlined fill text-sm text-on-primary">auto_awesome</span>
      </span>
      <div
        className={`max-w-[80%] rounded-xl rounded-tl-none border border-outline-variant bg-surface-container-low p-4 text-body-md leading-relaxed text-on-surface shadow-sm ${
          failed ? "border-error-container bg-error-container/40" : ""
        }`}
      >
        {pending && !content ? (
          <TypingIndicator />
        ) : (
          <div className="whitespace-pre-wrap">
            {onCite && sources ? renderWithCitations(content, sources, onCite) : content}
            {pending && (
              <span className="ml-1">
                <TypingIndicator />
              </span>
            )}
          </div>
        )}
        {failed && !content && (
          <p className="mt-1 text-label-sm text-error">The answer failed. Try again.</p>
        )}
      </div>
    </div>
  );
}