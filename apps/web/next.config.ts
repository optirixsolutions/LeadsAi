import type { NextConfig } from "next";

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
        ],
      },
    ];
  },
};

export default nextConfig;
