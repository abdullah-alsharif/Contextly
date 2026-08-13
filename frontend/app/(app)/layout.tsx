// App shell: fixed sidebar + scrollable content (frontend-design.md §5:
// h-screen overflow-hidden, content region scrolls). The topbar is chat-only
// and lives in the nested chat layout.
import Sidebar from "@/components/sidebar";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden bg-surface">
      <Sidebar />
      <main className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        {children}
      </main>
    </div>
  );
}
