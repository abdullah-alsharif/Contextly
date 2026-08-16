// Backend origin comes from NEXT_PUBLIC_BACKEND_URL (docs/deployment.md §3);
// the dev-only websocket keeps next dev HMR working.
const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
const devConnect = process.env.NODE_ENV === "development" ? " ws://localhost:3000" : "";

const nextConfig = {
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          {
            // CSP incl. frame-ancestors (docs/security.md §5/§7); font/CDN
            // domains allow-listed, unsafe-inline/eval stay for hydration.
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
            // Defense in depth for clients that ignore CSP frame-ancestors.
            key: "X-Frame-Options",
            value: "DENY",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
