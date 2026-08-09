export default function Home() {
  return (
    <main className="flex min-h-screen items-center justify-center">
      <section className="max-w-2xl px-6 py-16 text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-standard bg-ink-900">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className="h-7 w-7 text-surface"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 3v18M3 12h18"
            />
          </svg>
        </div>
        <h1 className="mt-8 font-display text-4xl font-semibold tracking-tight text-ink-900">
          Contextly
        </h1>
        <p className="mt-4 text-lg text-ink-700">
          AI answers grounded in your documents — with sources you can verify.
        </p>
        <p className="mt-12 text-sm text-ink-700">
          Phase 0 shell. Uploads and chat arrive in later phases.
        </p>
      </section>
    </main>
  );
}