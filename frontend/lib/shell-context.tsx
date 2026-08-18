// App shell state (app/(app)/layout.tsx): desktop collapse rail + mobile
// drawer, with the preference persisted to localStorage (same key as before).
"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

const SIDEBAR_COLLAPSED_KEY = "contextly:sidebar-collapsed";

interface ShellApi {
  collapsed: boolean;
  drawerOpen: boolean;
  toggleSidebar: () => void;
  expandSidebar: () => void;
  closeDrawer: () => void;
}

const ShellContext = createContext<ShellApi | null>(null);

export function ShellProvider({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Deferred so first paint matches the server's expanded render.
  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      let stored: string | null = null;
      try {
        stored = window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
      } catch {}
      setCollapsed(stored !== null ? stored === "1" : window.innerWidth < 1024);
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? "1" : "0");
      } catch {}
      return next;
    });
  }, []);

  const expandSidebar = useCallback(() => {
    setCollapsed(false);
    try {
      window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, "0");
    } catch {}
  }, []);

  const toggleSidebar = useCallback(() => {
    if (window.matchMedia("(min-width: 768px)").matches) {
      toggleCollapsed();
    } else {
      setDrawerOpen((open) => !open);
    }
  }, [toggleCollapsed]);

  const closeDrawer = useCallback(() => setDrawerOpen(false), []);

  return (
    <ShellContext.Provider
      value={{ collapsed, drawerOpen, toggleSidebar, expandSidebar, closeDrawer }}
    >
      {children}
    </ShellContext.Provider>
  );
}

export function useShell(): ShellApi {
  const ctx = useContext(ShellContext);
  if (!ctx) throw new Error("useShell must be used within ShellProvider");
  return ctx;
}
