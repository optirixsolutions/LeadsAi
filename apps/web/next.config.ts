import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output is for the Docker image; `next start` (dev, e2e) needs the default.
  output: process.env.SALESIQ_STANDALONE === "1" ? "standalone" : undefined,
  poweredByHeader: false,
  transpilePackages: ["@salesiq/contracts"],
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
