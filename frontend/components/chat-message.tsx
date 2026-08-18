// Chat message — mirrors prototypes/chat.html: AI card (rounded-xl, no
// top-left radius), user solid secondary. Assistant content renders as
// markdown (react-markdown); `[n]` markers split into citation chips after
// parsing, so markdown constructs are never broken.
"use client";

import React, { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import CitationChip from "@/components/citation-chip";
import TypingIndicator from "@/components/typing-indicator";
import type { Source } from "@/lib/api-client";

const CITATION_PATTERN = /\[(\d{1,2})\]/g;

function splitText(
  text: string,
  sources: Source[],
  onCite: (source: Source) => void,
): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  const pattern = new RegExp(CITATION_PATTERN.source, "g");
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index));
    const n = Number(match[1]);
    const source = sources[n - 1] ?? sources[n];
    parts.push(
      source ? (
        <CitationChip
          key={key++}
          index={n}
          source={source}
          onClick={() => onCite(source)}
        />
      ) : (
        match[0]
      ),
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts;
}

function splitChildren(
  children: React.ReactNode,
  sources: Source[],
  onCite: (source: Source) => void,
): React.ReactNode {
  return React.Children.map(children, (child) => {
    if (typeof child === "string") return splitText(child, sources, onCite);
    if (React.isValidElement(child)) {
      return React.cloneElement(
        child as React.ReactElement<{ children?: React.ReactNode }>,
        {
          children: splitChildren(
            (child.props as { children?: React.ReactNode }).children,
            sources,
            onCite,
          ),
        },
      );
    }
    return child;
  });
}

const INLINE_CLASS = "text-body-md leading-relaxed";

// All markdown elements share `HTMLAttributes`; `node` is react-markdown's
// mdast reference (dropped before spreading onto DOM elements).
type MdProps = React.HTMLAttributes<HTMLElement> & { node?: unknown };

// Block components: style markdown typography and inject citation chips into
// text nodes.
function block(
  tag: string,
  className: string,
  sources: Source[],
  onCite: (source: Source) => void,
) {
  return function Block({ children, node: _node, ...rest }: MdProps) {
    return React.createElement(
      tag,
      { ...rest, className: `${INLINE_CLASS} ${className}` },
      splitChildren(children, sources, onCite),
    );
  };
}

function mdComponents(sources: Source[], onCite: (source: Source) => void) {
  return {
    p: block("p", "my-1.5", sources, onCite),
    li: block("li", "my-0.5", sources, onCite),
    td: block("td", "border border-outline-variant px-2 py-1", sources, onCite),
    th: block("th", "border border-outline-variant px-2 py-1 font-medium text-left", sources, onCite),
    h1: block("h1", "text-title-lg mt-4 mb-2", sources, onCite),
    h2: block("h2", "text-body-lg font-semibold mt-4 mb-2", sources, onCite),
    h3: block("h3", "text-body-md font-semibold mt-3 mb-1", sources, onCite),
    h4: block("h4", "text-body-md font-medium mt-3 mb-1", sources, onCite),
    h5: block("h5", "text-body-md font-medium mt-3 mb-1", sources, onCite),
    h6: block("h6", "text-body-md font-medium mt-3 mb-1", sources, onCite),
    blockquote: block(
      "blockquote",
      "border-l-2 border-outline-variant pl-3 my-1.5 text-on-surface-variant",
      sources,
      onCite,
    ),
    ul: ({ node: _node, ...rest }: MdProps) => (
      <ul {...rest} className="my-1.5 list-disc pl-6" />
    ),
    ol: ({ node: _node, ...rest }: MdProps) => (
      <ol {...rest} className="my-1.5 list-decimal pl-6" />
    ),
    pre: ({ node: _node, ...rest }: MdProps) => (
      <pre {...rest} className="my-2 overflow-x-auto rounded-lg bg-surface-variant p-3 text-body-sm" />
    ),
    code: ({ node: _node, ...rest }: MdProps) => (
      <code {...rest} className="rounded bg-surface-variant px-1 py-0.5 text-body-sm" />
    ),
    table: ({ node: _node, ...rest }: MdProps) => (
      <table {...rest} className="my-2 w-full border-collapse text-body-sm" />
    ),
    a: ({ node: _node, ...rest }: MdProps) => (
      <a {...rest} className="text-secondary underline" target="_blank" rel="noreferrer" />
    ),
  };
}

// Small ghost icon under the bubble, revealed on hover or keyboard focus,
// copies the raw message as text.
function CopyButton({ content, align }: { content: string; align: "left" | "right" }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  return (
    <div
      className={`mt-1 flex md:opacity-0 md:transition-opacity md:duration-150 md:group-hover:opacity-100 focus-within:opacity-100 ${
        align === "right" ? "justify-end" : ""
      }`}
    >
      <button
        type="button"
        title={copied ? "Copied" : "Copy as text"}
        aria-label={copied ? "Copied" : "Copy message as text"}
        onClick={() => {
          void navigator.clipboard.writeText(content).then(() => {
            setCopied(true);
            if (timer.current) clearTimeout(timer.current);
            timer.current = setTimeout(() => setCopied(false), 1500);
          });
        }}
        className="rounded-md p-1 text-on-surface-variant transition-colors hover:bg-surface-container-high hover:text-on-surface"
      >
        <span className="material-symbols-outlined text-xs" aria-hidden="true">
          {copied ? "check" : "content_copy"}
        </span>
      </button>
    </div>
  );
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
      <div className="group flex justify-end">
        <div className="flex max-w-[80%] flex-col items-end">
          <div className="rounded-xl rounded-tr-none bg-secondary p-4 text-body-md text-on-secondary shadow-sm">
            {content}
          </div>
          <CopyButton content={content} align="right" />
        </div>
      </div>
    );
  }

  return (
    <div className="group flex items-start gap-3">
      <span className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary">
        <span className="material-symbols-outlined fill text-sm text-on-primary">auto_awesome</span>
      </span>
      <div className="max-w-[80%] min-w-0">
        <div
          className={`rounded-xl rounded-tl-none border border-outline-variant bg-surface-container-low p-4 shadow-sm ${
            failed ? "border-error-container bg-error-container/40" : ""
          }`}
        >
          {pending && !content ? (
            <TypingIndicator />
          ) : (
            <div className="whitespace-pre-wrap">
              {sources && onCite ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents(sources, onCite)}>
                  {content}
                </ReactMarkdown>
              ) : (
                <p className="text-body-md whitespace-pre-wrap leading-relaxed">{content}</p>
              )}
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
        {!pending && <CopyButton content={content} align="left" />}
      </div>
    </div>
  );
}
