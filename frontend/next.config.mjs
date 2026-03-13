/** @type {import('next').NextConfig} */
const nextConfig = {
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    domains: ["localhost"],
    unoptimized: true,
  },
  // Environment variables are loaded from .env.local
  // NEXT_PUBLIC_BACKEND_URL defaults to http://localhost:8000 for local development
}

export default nextConfig
