// App shell: fixed sidebar + topbar, scrollable content (frontend-design.md §5:
// h-screen overflow-hidden, content region scrolls, sidebar+topbar fixed).
import Sidebar from "@/components/sidebar";
import Topbar from "@/components/topbar";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden bg-surface">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <div id="ai-context-bar" className="ai-context-bar" aria-hidden="true" />
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}