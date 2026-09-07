// ARCHITECTURE.md §1: "Web and API are served from one origin ... /api/*
// rewrite [to FastAPI]." This is what the browser's relative /api/* calls
// (lib/api/client.ts) are proxied through — same server-only INTERNAL_API_URL
// a server component uses directly (docker-compose.yml sets it to the `api`
// container's hostname; defaults to localhost:8000 for host-side `pnpm dev`).
const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL ?? "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${INTERNAL_API_URL}/api/:path*` },
    ];
  },
};

export default nextConfig;
