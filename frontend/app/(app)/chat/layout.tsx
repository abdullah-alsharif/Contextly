// Chat-only shell: the AI-context bar renders only on chat routes.
export default function ChatLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <div id="ai-context-bar" className="ai-context-bar" aria-hidden="true" />
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">{children}</div>
    </>
  );
}
