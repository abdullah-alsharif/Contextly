/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          {
            // Per docs/deployment.md §5: CSP + nosniff.
            // Dev-friendly policy: unsafe-inline/eval are needed by next dev HMR.
            key: "Content-Security-Policy",
            value:
              "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; " +
              "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; " +
              "font-src 'self' data:; " +
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