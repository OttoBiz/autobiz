/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    appDir: true,
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    domains: ["localhost", "a-health.onrender.com"],
    unoptimized: true,
  },
  env: {
    BACKEND_URL: process.env.BACKEND_URL || "https://a-health.onrender.com",
  },
}

module.exports = nextConfig
