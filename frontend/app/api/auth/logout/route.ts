// POST /api/auth/logout — remove the session (contracts C1).
import { NextResponse } from "next/server";
import { DEV_TOKEN_COOKIE, isDevAuthMode } from "@/lib/auth/session";
import { createServerSupabaseClient } from "@/lib/supabase/server";

export async function POST() {
  const response = NextResponse.json({ ok: true });

  if (isDevAuthMode()) {
    response.cookies.set(DEV_TOKEN_COOKIE, "", { path: "/", maxAge: 0 });
    return response;
  }

  const supabase = await createServerSupabaseClient();
  await supabase.auth.signOut();
  return response;
}