"use client";

// Profile card: editable display name (PATCH /auth/me); email is read-only.
import { useEffect, useState } from "react";
import PageTitleBar from "@/components/page-title-bar";
import { getProfile, updateProfile } from "@/lib/api-client";
import { notifyCrossTab } from "@/lib/cross-tab";

export default function SettingsPage() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<"idle" | "saved" | "error">("idle");

  useEffect(() => {
    getProfile()
      .then((profile) => {
        setFullName(profile.full_name ?? "");
        setEmail(profile.email);
      })
      .catch(() => {
        setStatus("error");
      })
      .finally(() => setLoaded(true));
  }, []);

  const save = async () => {
    setSaving(true);
    setStatus("idle");
    try {
      const profile = await updateProfile(fullName.trim() || null);
      setFullName(profile.full_name ?? "");
      setStatus("saved");
      window.dispatchEvent(new CustomEvent("profile:updated"));
      notifyCrossTab("profile:updated");
    } catch {
      setStatus("error");
    } finally {
      setSaving(false);
    }
  };

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
                value={fullName}
                maxLength={120}
                onChange={(e) => {
                  setFullName(e.target.value);
                  setStatus("idle");
                }}
                placeholder="Your name"
                className="w-full rounded-lg border border-outline-variant bg-surface px-3 py-2 text-body-sm text-on-surface focus:border-secondary focus-ring"
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
                value={email}
                placeholder="you@example.com"
                className="w-full cursor-not-allowed rounded-lg border border-outline-variant bg-surface-container-low px-3 py-2 text-body-sm text-on-surface-variant"
              />
              <p className="text-label-sm text-on-surface-variant">
                Managed by your account. Contact support to change it.
              </p>
            </div>
            <div className="flex items-center gap-3 pt-2">
              <button
                type="button"
                onClick={() => void save()}
                disabled={saving || !loaded}
                className="rounded-lg bg-secondary px-4 py-2 font-display text-label-md text-on-secondary transition-colors enabled:hover:bg-secondary/90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {saving ? "Saving…" : "Save changes"}
              </button>
              {status === "saved" && (
                <p className="text-label-sm text-secondary" role="status">
                  Saved.
                </p>
              )}
              {status === "error" && (
                <p className="text-label-sm text-error" role="alert">
                  Could not save. Try again.
                </p>
              )}
            </div>
          </div>
        </section>
      </div>
    </>
  );
}
