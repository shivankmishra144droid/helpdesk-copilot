import type { NextConfig } from "next";
import path from "path";

// Where /api/* is proxied when the frontend and backend share one container
// (see the root Dockerfile). Unused when NEXT_PUBLIC_API_BASE is an absolute URL.
const BACKEND_URL = process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  outputFileTracingRoot: path.join(process.cwd()),
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/:path*` }];
  },
};

export default nextConfig;
