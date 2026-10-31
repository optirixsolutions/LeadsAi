import type { NextConfig } from "next";

// No third-party origin is ever needed, so nothing else may load, connect, or receive a form. Next's
// bootstrap needs inline scripts without per-request nonces, so this limits where scripts come from
// and what a page can reach, and does not stop an inline injection by itself. React's escaping does
// that. Development also needs eval and a socket for hot reload.
const isDev = process.env.NODE_ENV === "development";
const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  `connect-src 'self'${isDev ? " ws:" : ""}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const nextConfig: NextConfig = {
  // Standalone output is for the Docker image; `next start` (dev, e2e) needs the default.
  output: process.env.SALESIQ_STANDALONE === "1" ? "standalone" : undefined,
  poweredByHeader: false,
  transpilePackages: ["@salesiq/contracts"],
  // The browser calls the API through this origin, so session cookies are first-party and
  // HttpOnly, and no CORS is involved. Note: the destination is resolved at build time.
  async rewrites() {
    const api = process.env.SALESIQ_API_URL ?? "http://127.0.0.1:8000";
    return [{ source: "/api/v1/:path*", destination: `${api}/api/v1/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Content-Security-Policy", value: CONTENT_SECURITY_POLICY },
        ],
      },
    ];
  },
};

export default nextConfig;
