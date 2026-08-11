// Session guard (research D1/D2). Runs before every request:
//  - supabase mode: refresh session via getUser() and write cookies back
//  - dev mode: treat the ctx_dev_token cookie as the session
// Redirects signed-out users from app routes to /login, and signed-in users
// from /login|/register to /documents.
import { NextResponse, type NextRequest } from "next/server";
import { createServerClient } from "@supabase/ssr";
import { DEV_TOKEN_COOKIE, isDevAuthMode } from "./lib/auth/session";

const APP_ROUTES = ["/documents", "/chat", "/settings"];
const AUTH_ROUTES = ["/login", "/register"];

function isAppRoute(pathname: string): boolean {
  return APP_ROUTES.some((route) => pathname === route || pathname.startsWith(`${route}/`));
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (isDevAuthMode()) {
    const hasSession = request.cookies.has(DEV_TOKEN_COOKIE);
    if (isAppRoute(pathname) && !hasSession) {
      return NextResponse.redirect(new URL("/login", request.url));
    }
    if (AUTH_ROUTES.includes(pathname) && hasSession) {
      return NextResponse.redirect(new URL("/documents", request.url));
    }
    return NextResponse.next();
  }

  let response = NextResponse.next({ request });
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  let user: { id: string } | null = null;

  if (url && anonKey) {
    const supabase = createServerClient(url, anonKey, {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) =>
            request.cookies.set(name, value),
          );
          response = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options),
          );
        },
      },
    });
    const { data } = await supabase.auth.getUser();
    user = data.user;
  }

  if (isAppRoute(pathname) && !user) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  if (AUTH_ROUTES.includes(pathname) && user) {
    return NextResponse.redirect(new URL("/documents", request.url));
  }
  return response;
}

export const config = {
  matcher: [
    "/documents/:path*",
    "/chat/:path*",
    "/settings/:path*",
    "/login",
    "/register",
  ],
};