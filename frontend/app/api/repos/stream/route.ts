import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

// Can't go through lib/backend.ts's proxyToBackend here — that reads the
// whole response body before returning, which would defeat the entire
// point of streaming. This forwards the backend's body straight through
// instead, chunk by chunk.
export async function POST(request: NextRequest) {
  const body = await request.text();

  let backendResponse: Response;
  try {
    backendResponse = await fetch(`${BACKEND_URL}/repos/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
  } catch {
    return Response.json(
      { error: `Could not reach the backend at ${BACKEND_URL}. Is it running?` },
      { status: 502 },
    );
  }

  // A validation error (e.g. bad repo_id) is rejected before the backend
  // ever opens the stream, so it comes back as a plain JSON error body —
  // relay it as-is rather than treating it as an ndjson stream.
  if (!backendResponse.ok || !backendResponse.body) {
    const text = await backendResponse.text();
    return new Response(text, {
      status: backendResponse.status,
      headers: { "Content-Type": backendResponse.headers.get("content-type") ?? "application/json" },
    });
  }

  return new Response(backendResponse.body, {
    status: backendResponse.status,
    headers: { "Content-Type": "application/x-ndjson" },
  });
}
