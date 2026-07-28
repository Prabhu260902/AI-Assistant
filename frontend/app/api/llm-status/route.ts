import { proxyToBackend } from "@/lib/backend";

export async function GET() {
  return proxyToBackend("/llm/status");
}
