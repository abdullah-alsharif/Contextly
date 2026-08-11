"use client";

// Shared login/register card (docs/frontend-design.md §4: centered card on
// background, primary button, rounded-lg, focus ring).
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

export default function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const isLogin = mode === "login";

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await fetch(`/api/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const body = (await res.json().catch(() => ({}))) as {
        ok?: boolean;
        error?: string;
      };
      if (!res.ok || !body.ok) {
        setError(body.error ?? "Something went wrong. Please try again.");
        return;
      }
      router.push("/documents");
      router.refresh();
    } catch {
      setError("Network error — check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="w-full" noValidate>
      <div className="space-y-4">
        <div className="space-y-1.5">
          <label htmlFor="email" className="block font-display text-label-sm text-ink-900">
            Email address
          </label>
          <input
            id="email"
            type="email"
            name="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="w-full rounded-lg border border-outline-variant bg-white px-3 py-2 text-body-sm text-ink-700 transition-colors placeholder:text-on-surface-variant/70/70 focus:border-secondary focus-ring"
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="password" className="block font-display text-label-sm text-ink-900">
            Password
          </label>
          <input
            id="password"
            type="password"
            name="password"
            autoComplete={isLogin ? "current-password" : "new-password"}
            required
            minLength={6}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="At least 6 characters"
            className="w-full rounded-lg border border-outline-variant bg-white px-3 py-2 text-body-sm text-ink-700 transition-colors placeholder:text-on-surface-variant/70/70 focus:border-secondary focus-ring"
          />
        </div>
      </div>

      {error && (
        <p
          role="alert"
          className="mt-4 rounded-lg border border-error/30 bg-error-container px-3 py-2 text-label-sm text-ink-700"
        >
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={busy}
        className="mt-6 w-full rounded-lg bg-secondary py-2.5 font-display text-label-md text-white transition-transform active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
      >
        {busy ? "Please wait…" : isLogin ? "Sign in" : "Create account"}
      </button>

      <p className="mt-5 text-center text-body-sm text-ink-700">
        {isLogin ? (
          <>
            New to Contextly?{" "}
            <Link href="/register" className="font-medium text-secondary hover:underline">
              Create an account
            </Link>
          </>
        ) : (
          <>
            Already have an account?{" "}
            <Link href="/login" className="font-medium text-secondary hover:underline">
              Sign in
            </Link>
          </>
        )}
      </p>
    </form>
  );
}