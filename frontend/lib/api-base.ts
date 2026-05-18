const publicUrl = process.env.NEXT_PUBLIC_BACKEND_URL?.trim()

/** Browser API root — direct URL when set, otherwise same-origin `/backend` proxy. */
export const API_BASE = publicUrl || "/backend"
