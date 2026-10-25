import type { NextConfig } from "next";

// In production Caddy sends /api/* to FastAPI and everything else here, so the browser sees one
// origin. `next dev` has no Caddy in front: forward /api/* to the stack instead (Caddy on :8080 by
// default, or uvicorn directly with IDS_API_ORIGIN=http://localhost:8000).
const apiOrigin = process.env.IDS_API_ORIGIN ?? "http://localhost:8080";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    if (process.env.NODE_ENV !== "development") return [];
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

export default nextConfig;
