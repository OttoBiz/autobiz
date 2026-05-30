/**
 * Resolves the backend API root at runtime, in priority order:
 *
 * 1. window.__BACKEND_URL__  — injected by app/layout.tsx from process.env.BACKEND_URL
 *    (server-side, always available regardless of Docker build args)
 * 2. process.env.NEXT_PUBLIC_BACKEND_URL — baked at build time if set as a build arg
 * 3. "/backend" — same-origin Next.js rewrite proxy (local dev fallback only)
 */
function resolveApiBase(): string {
  if (typeof window !== "undefined") {
    const runtime = (window as Window & { __BACKEND_URL__?: string })
      .__BACKEND_URL__
      ?.trim()
    if (runtime) return runtime
  }
  const buildTime = process.env.NEXT_PUBLIC_BACKEND_URL?.trim()
  if (buildTime) return buildTime
  return "/backend"
}

export const API_BASE = resolveApiBase()
