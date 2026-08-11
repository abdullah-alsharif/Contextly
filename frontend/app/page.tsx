import { redirect } from "next/navigation";
import { isDevAuthMode, DEV_TOKEN_COOKIE } from "@/lib/auth/session";
import { cookies } from "next/headers";

// Session check both modes: dev cookie (middleware keeps it fresh) or Supabase
// session cookie via the SSR client (deployment.md §5).
async function hasSession(): Promise<boolean> {
  if (isDevAuthMode()) {
    return cookies().has(DEV_TOKEN_COOKIE);
  }
  try {
    const { createServerSupabaseClient } = await import("@/lib/supabase/server");
    const { data } = await createServerSupabaseClient().auth.getUser();
    return Boolean(data.user);
  } catch {
    return false;
  }
}

export default async function HomePage() {
  if (await hasSession()) {
    redirect("/documents");
  }
  redirect("/login");
}