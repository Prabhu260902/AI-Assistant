import { NextRequest } from "next/server";
import { proxyToBackend } from "@/lib/backend";

export async function POST(request: NextRequest) {
  const body = await request.json();
  return proxyToBackend("/copilot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
