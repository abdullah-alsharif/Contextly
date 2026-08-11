// POST /api/auth/login — proxied Supabase signIn, or dev-token login
// (docs/api.md §1 footnote; contracts C1).
import { NextResponse } from "next/server";
import {
  DEV_TOKEN_COOKIE,
  isDevAuthMode,
} from "@/lib/auth/session";
import { mintDevToken } from "@/lib/auth/dev-token";
import { createServerSupabaseClient } from "@/lib/supabase/server";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export async function POST(request: Request) {
  let email = "";
  let password = "";
  try {
    const body = (await request.json()) as { email?: unknown; password?: unknown };
    email = typeof body.email === "string" ? body.email.trim() : "";
    password = typeof body.password === "string" ? body.password : "";
  } catch {
    return NextResponse.json({ error: "Invalid request body." }, { status: 400 });
  }

  if (!EMAIL_RE.test(email)) {
    return NextResponse.json({ error: "Enter a valid email address." }, { status: 422 });
  }
  if (password.length < 6) {
    return NextResponse.json(
      { error: "Password must be at least 6 characters." },
      { status: 422 },
    );
  }

  if (isDevAuthMode()) {
    // Dev mode (docs/local-dev.md §3): mint a dev JWT — zero credentials.
    const token = await mintDevToken(email);
    const response = NextResponse.json({ ok: true });
    response.cookies.set(DEV_TOKEN_COOKIE, token, {
      path: "/",
      sameSite: "lax",
      maxAge: 60 * 60,
    });
    return response;
  }

  const supabase = createServerSupabaseClient();
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) {
    const message =
      error.status === 400
        ? "Invalid email or password."
        : "Sign-in failed. Please try again.";
    return NextResponse.json({ error: message }, { status: error.status ?? 400 });
  }
  return NextResponse.json({ ok: true });
}