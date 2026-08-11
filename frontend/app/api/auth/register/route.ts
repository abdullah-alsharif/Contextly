// POST /api/auth/register — proxied Supabase signUp, or dev-token sign-in
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
    // Dev mode: "sign-up" is the same credential-free token mint (local-dev.md §3).
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
  const { error } = await supabase.auth.signUp({ email, password });
  if (error) {
    const message =
      error.status === 400
        ? "This email is already registered or invalid."
        : "Sign-up failed. Please try again.";
    return NextResponse.json({ error: message }, { status: error.status ?? 400 });
  }
  return NextResponse.json({ ok: true });
}