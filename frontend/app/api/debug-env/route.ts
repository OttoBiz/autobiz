import { NextResponse } from "next/server"

/**
 * Debug endpoint — shows which backend URL the Next.js proxy is targeting.
 * Hit /api/debug-env in the browser to confirm the env vars are correct.
 * Remove this route before going to production.
 */
export async function GET() {
  const backendUrl =
    process.env.BACKEND_URL ||
    process.env.NEXT_PUBLIC_BACKEND_URL ||
    "(not set — will default to http://localhost:8000 in next.config.mjs)"

  // Also probe the backend to confirm it's reachable from the Next.js server
  let probeStatus: string
  const probeTarget =
    process.env.BACKEND_URL ||
    process.env.NEXT_PUBLIC_BACKEND_URL ||
    "http://localhost:8000"

  try {
    const res = await fetch(`${probeTarget.replace(/\/$/, "")}/`, {
      signal: AbortSignal.timeout(5000),
    })
    probeStatus = `${res.status} ${res.statusText}`
  } catch (err: unknown) {
    probeStatus = `FAILED — ${err instanceof Error ? err.message : String(err)}`
  }

  return NextResponse.json({
    BACKEND_URL: process.env.BACKEND_URL ?? null,
    NEXT_PUBLIC_BACKEND_URL: process.env.NEXT_PUBLIC_BACKEND_URL ?? null,
    resolved_proxy_target: backendUrl,
    backend_probe: probeStatus,
  })
}
