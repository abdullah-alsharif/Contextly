// Session abstraction over both auth modes (research D1/D2, contracts C1):
//  - supabase mode: @supabase/ssr session cookies (deployment.md §5)
//  - dev mode:      dev JWT in a JS-readable cookie, minted by /api/auth/*
//                   (local-dev.md §3 — zero credentials, AUTH_MODE=dev)
import { createBrowserClient } from "@supabase/ssr";

export const DEV_TOKEN_COOKIE = "ctx_dev_token";
export const DEV_AUDIENCE = "contextly-dev";

export function isDevAuthMode(): boolean {
  return (process.env.NEXT_PUBLIC_AUTH_MODE ?? "dev") === "dev";
}

export function getDevJwtSecret(): string {
  return (
    process.env.NEXT_PUBLIC_DEV_JWT_SECRET ??
    "contextly-dev-secret-0123456789abcdef"
  );
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie
    .split("; ")
    .find((entry) => entry.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=").slice(1).join("=")) : null;
}

/** Browser-side access token for the Authorization header (docs/api.md). */
export async function getBrowserAccessToken(): Promise<string | null> {
  if (isDevAuthMode()) {
    return readCookie(DEV_TOKEN_COOKIE);
  }
  let client = null as ReturnType<typeof createBrowserClient> | null;
  try {
    const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
    const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    if (url && anonKey) client = createBrowserClient(url, anonKey);
  } catch {
    client = null;
  }
  if (!client) return null;
  const { data } = await client.auth.getSession();
  return data.session?.access_token ?? null;
}