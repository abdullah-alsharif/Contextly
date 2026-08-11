/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          {
            // Per docs/deployment.md §5: CSP + nosniff. Google Fonts (Geist,
            // Inter, Material Symbols — docs/frontend-design.md §2) are loaded
            // via stylesheet + font domains, so both are allow-listed.
            // Dev-friendly policy: unsafe-inline/eval are needed by next dev HMR.
            key: "Content-Security-Policy",
            value:
              "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; " +
              "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; " +
              "img-src 'self' data: blob:; " +
              "font-src 'self' data: https://fonts.gstatic.com; " +
              "connect-src 'self' http://localhost:8000 ws://localhost:3000",
          },
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
        ],
      },
    ];
  },
};

module.exports = nextConfig;