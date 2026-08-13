// Chat-only shell: topbar + AI-context bar render only on chat routes.
import Topbar from "@/components/topbar";

export default function ChatLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Topbar />
      <div id="ai-context-bar" className="ai-context-bar" aria-hidden="true" />
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">{children}</div>
    </>
  );
}
