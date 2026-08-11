// connect-src is deployment-aware: the real backend origin comes from
// NEXT_PUBLIC_BACKEND_URL (docs/deployment.md §3); the dev-only websocket keeps
// next dev HMR working. `ws://localhost:3000` is omitted in production builds.
const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
const devConnect = process.env.NODE_ENV === "development" ? " ws://localhost:3000" : "";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          {
            // Per docs/deployment.md §5 + docs/security.md §5: CSP (includes
            // frame-ancestors so the SPA refuses to be framed — Phase 9),
            // nosniff, and X-Frame-Options for legacy browsers. Google Fonts
            // (Geist, Inter, Material Symbols — docs/frontend-design.md §2) are
            // loaded via stylesheet + font domains, so both are allow-listed.
            // NOTE (accepted, docs/security.md §7): unsafe-inline/eval remain
            // in script-src because Next's hydration injects inline scripts;
            // a nonce/hash-based policy is a Phase 11 deployment-hardening item.
            key: "Content-Security-Policy",
            value:
              `default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; ` +
              `style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; ` +
              `img-src 'self' data: blob:; ` +
              `font-src 'self' data: https://fonts.gstatic.com; ` +
              `connect-src 'self' ${backendUrl}${devConnect}; ` +
              `frame-ancestors 'none'`,
          },
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
          {
            // Defense in depth: X-Frame-Options for clients that ignore the
            // CSP frame-ancestors directive (docs/security.md §5).
            key: "X-Frame-Options",
            value: "DENY",
          },
        ],
      },
    ];
  },
};

module.exports = nextConfig;