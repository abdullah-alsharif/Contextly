// Security-header guard rail for the frontend (docs/deployment.md §5,
// docs/security.md §5, spec SC-005). Asserts that the Next.js headers()
// config carries CSP (with frame-ancestors), X-Content-Type-Options, and
// X-Frame-Options on the catch-all route. Runs in CI (`npm run security:check`).
//
// This is a static config guard — it catches a config regressions, not a
// config-to-served regression; the actual served headers are verified end to
// end during the manual/converge pass (next start + curl).

import assert from "node:assert/strict";
import nextConfig from "../next.config.mjs";

// Next.js context: `headers` is an async function returning the route table.
assert.equal(typeof nextConfig.headers, "function", "next.config.mjs must define headers()");
const headers = await nextConfig.headers();
assert.ok(Array.isArray(headers), "headers() must return an array");

const root = headers.find((entry) => entry.source === "/(.*)");
assert.ok(root, "a header entry for the catch-all source '/(.*)' is required");

const byKey = new Map(root.headers.map((h) => [h.key, h.value]));

const csp = byKey.get("Content-Security-Policy");
assert.ok(csp, "Content-Security-Policy header is missing");
for (const directive of ["default-src 'self'", "frame-ancestors 'none'"]) {
  assert.ok(csp.includes(directive), `CSP must contain ${directive}`);
}

assert.equal(
  byKey.get("X-Content-Type-Options"),
  "nosniff",
  "X-Content-Type-Options must be nosniff",
);
assert.equal(
  byKey.get("X-Frame-Options"),
  "DENY",
  "X-Frame-Options must be DENY (defense in depth for frame-ancestors)",
);

console.log("security headers OK: CSP(+frame-ancestors), nosniff, X-Frame-Options");