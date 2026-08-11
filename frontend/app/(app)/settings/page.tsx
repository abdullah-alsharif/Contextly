// Minimal settings page (docs/frontend-design.md §4: reuses sidebar list rows
// + form inputs).
export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-2xl px-8 py-8">
      <h1 className="font-display text-headline-lg text-ink-900">Settings</h1>
      <p className="mt-1 text-body-sm text-on-surface-variant">
        Account preferences for your workspace.
      </p>

      <section className="mt-8 rounded-xl border border-outline-variant bg-white">
        <div className="border-b border-surface-variant px-6 py-4">
          <h2 className="font-display text-title-lg text-ink-900">Profile</h2>
        </div>
        <div className="space-y-4 px-6 py-5">
          <div className="space-y-1.5">
            <label htmlFor="full-name" className="block font-display text-label-sm text-ink-900">
              Full name
            </label>
            <input
              id="full-name"
              type="text"
              placeholder="Your name"
              className="w-full rounded-lg border border-outline-variant bg-white px-3 py-2 text-body-sm text-ink-700 focus:border-secondary focus-ring"
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="email" className="block font-display text-label-sm text-ink-900">
              Email
            </label>
            <input
              id="email"
              type="email"
              disabled
              placeholder="you@example.com"
              className="w-full cursor-not-allowed rounded-lg border border-outline-variant bg-surface-container-low px-3 py-2 text-body-sm text-on-surface-variant"
            />
            <p className="text-label-sm text-on-surface-variant">
              Managed by your Supabase account.
            </p>
          </div>
          <div className="pt-2">
            <button
              type="button"
              className="rounded-lg border border-ink-900 px-4 py-2 font-display text-label-md text-ink-900 transition-colors hover:bg-surface-container-low"
            >
              Save changes
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}