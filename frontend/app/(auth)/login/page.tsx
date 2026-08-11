import type { Metadata } from "next";
import Link from "next/link";
import AuthForm from "@/components/auth-form";

export const metadata: Metadata = { title: "Sign in — Contextly" };

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-surface px-4">
      <section className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <Link
            href="/login"
            className="inline-flex h-11 w-11 items-center justify-center rounded-lg bg-ink-900"
            aria-label="Contextly home"
          >
            <span className="material-symbols-outlined text-surface">menu_book</span>
          </Link>
          <h1 className="mt-4 font-display text-headline-md text-ink-900">Contextly</h1>
          <p className="mt-1 text-body-sm text-ink-700">
            AI answers grounded in your documents — with sources you can verify.
          </p>
        </div>
        <div className="rounded-xl border border-outline-variant bg-white p-6 shadow-none">
          <AuthForm mode="login" />
        </div>
      </section>
    </main>
  );
}