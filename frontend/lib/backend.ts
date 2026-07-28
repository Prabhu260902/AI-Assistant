import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

/**
 * Forwards a request to the FastAPI backend and relays its response,
 * guaranteeing the browser always gets back valid JSON — even when the
 * backend is unreachable, or (should the global exception handler in
 * backend/main.py ever be bypassed) returns a non-JSON body.
 */
export async function proxyToBackend(path: string, init?: RequestInit): Promise<NextResponse> {
  let backendResponse: Response;
  try {
    backendResponse = await fetch(`${BACKEND_URL}${path}`, init);
  } catch {
    return NextResponse.json(
      { error: `Could not reach the backend at ${BACKEND_URL}. Is it running?` },
      { status: 502 },
    );
  }

  const rawBody = await backendResponse.text();
  let data: unknown;
  try {
    data = rawBody ? JSON.parse(rawBody) : {};
  } catch {
    return NextResponse.json(
      {
        error: `Backend returned a non-JSON response (status ${backendResponse.status}): ${rawBody.slice(0, 300)}`,
      },
      { status: 502 },
    );
  }

  return NextResponse.json(data, { status: backendResponse.status });
}
