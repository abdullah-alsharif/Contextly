// Minimal settings page (docs/frontend-design.md §4: reuses sidebar list rows
// + form inputs).
import PageTitleBar from "@/components/page-title-bar";

export default function SettingsPage() {
  return (
    <>
      <PageTitleBar
        title="Settings"
        subtitle="Account preferences for your workspace."
      />
      <div className="mx-auto w-full max-w-container-max px-8 py-8">
        <section className="rounded-xl border border-outline-variant bg-surface-container-lowest">
        <div className="border-b border-surface-variant px-6 py-4">
          <h2 className="font-display text-title-lg text-on-surface">Profile</h2>
        </div>
        <div className="space-y-4 px-6 py-5">
          <div className="space-y-1.5">
            <label htmlFor="full-name" className="block font-display text-label-sm text-on-surface">
              Full name
            </label>
            <input
              id="full-name"
              type="text"
              placeholder="Your name"
              className="w-full rounded-lg border border-outline-variant bg-surface-container-lowest px-3 py-2 text-body-sm text-on-surface-variant focus:border-secondary focus-ring"
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="email" className="block font-display text-label-sm text-on-surface">
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
              className="rounded-lg border border-outline px-4 py-2 font-display text-label-md text-on-surface transition-colors hover:bg-surface-container-low"
            >
              Save changes
            </button>
          </div>
        </div>
      </section>
    </div>
    </>
  );
}
