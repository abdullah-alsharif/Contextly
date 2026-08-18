// App shell: sidebar + scrollable content (frontend-design.md §5). No
// app-level header; h-dvh keeps the shell inside the mobile viewport.
import Sidebar from "@/components/sidebar";
import { ShellProvider } from "@/lib/shell-context";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <ShellProvider>
      <div className="flex h-screen flex-col overflow-hidden bg-surface supports-[height:100dvh]:h-dvh">
        <div className="flex min-h-0 flex-1">
          <Sidebar />
          <main className="flex min-w-0 flex-1 flex-col overflow-y-auto">
            {children}
          </main>
        </div>
      </div>
    </ShellProvider>
  );
}
