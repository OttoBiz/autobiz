/** @type {import('next').NextConfig} */
const nextConfig = {
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
    NEXT_PUBLIC_BACKEND_URL: "https://a-health.onrender.com",
  },
}

export default nextConfig
