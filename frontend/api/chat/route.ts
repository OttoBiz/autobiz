import { type NextRequest, NextResponse } from "next/server"

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData()

    // Get the backend URL from environment variables
    const backendUrl = process.env.BACKEND_URL || "http://localhost:8000"

    // Forward the request to your Python backend
    const response = await fetch(`${backendUrl}/chat`, {
      method: "POST",
      body: formData,
    })

    if (!response.ok) {
      throw new Error(`Backend responded with status: ${response.status}`)
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error("Error forwarding request to backend:", error)
    return NextResponse.json({ error: "Failed to process request" }, { status: 500 })
  }
}
