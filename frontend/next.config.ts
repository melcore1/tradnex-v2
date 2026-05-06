import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  // Standalone output produces a self-contained server.js for the
  // production Docker stage. See Dockerfile.frontend.
  output: 'standalone',
  reactStrictMode: true,
  poweredByHeader: false,
  experimental: {
    // Suppress known Next 15 warning about turbo defaults
  },
}

export default nextConfig
