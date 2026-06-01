import type { NextConfig } from "next";

// In dev, proxy /api/* to the local Python server (serve_local_api.py on :8000).
// In production, Vercel serves /api/*.py as Python serverless functions directly.
const dev = process.env.NODE_ENV !== "production";

const nextConfig: NextConfig = {
  async rewrites() {
    return dev
      ? [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" }]
      : [];
  },
};

export default nextConfig;
