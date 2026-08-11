import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { cookies } from "next/headers";

// @supabase/ssr server client for route handlers (docs/deployment.md §5:
// session lives in httpOnly cookies in production). Cookie writes inside
// Server Components are refused by Next.js — the middleware refreshes instead.
export function createServerSupabaseClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) {
    throw new Error(
      "NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY must be set in supabase auth mode",
    );
  }
  return createServerClient(url, anonKey, {
    cookies: {
      getAll() {
        return cookies().getAll();
      },
      setAll(cookiesToSet: { name: string; value: string; options: CookieOptions }[]) {
        try {
          cookiesToSet.forEach(({ name, value, options }) =>
            cookies().set(name, value, options),
          );
        } catch {
          // Server Component context — middleware handles the refresh.
        }
      },
    },
  });
}