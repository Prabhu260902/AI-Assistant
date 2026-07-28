import { NextRequest } from "next/server";
import { proxyToBackend } from "@/lib/backend";

export async function GET() {
  return proxyToBackend("/repos");
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  return proxyToBackend("/repos", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
