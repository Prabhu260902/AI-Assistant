// Mirrors backend/main.py's response models — see docs/phase10.md for the
// /copilot contract. `result`'s exact shape depends on `intent`; these
// interfaces are narrowed by intent in ChatMessage, not runtime-validated
// (single-user local tool, not a public API boundary).

export type Intent = "search" | "architecture" | "plan" | "tickets" | "implement" | "review" | string;

export interface CopilotResponse {
  intent: Intent;
  result: Record<string, unknown>;
}

export interface Citation {
  file_path: string;
  start_line: number;
  end_line: number;
  snippet: string;
}

export interface SearchResult {
  answer: string;
  citations: Citation[];
}

export interface FlowNode {
  key: string;
  name: string;
  file_path: string;
  kind: "endpoint" | "function" | "external" | string;
  detail: string | null;
}

export interface FlowEdge {
  from_key: string;
  to_key: string;
}

export interface ArchitectureResult {
  explanation: string;
  mermaid_diagram: string;
  flow_graph: { nodes: FlowNode[]; edges: FlowEdge[] } | null;
}

export interface AffectedModule {
  file_path: string;
  reason: string;
  fan_in: number;
  has_api_endpoint: boolean;
}

export interface PlanResult {
  plan: string;
  affected_modules: AffectedModule[];
  risks: string[];
}

export interface Task {
  title: string;
  description: string;
}

export interface Story {
  title: string;
  description: string;
  acceptance_criteria: string[];
  test_cases: string[];
  tasks: Task[];
}

export interface Epic {
  title: string;
  description: string;
  stories: Story[];
}

export interface TicketsResult extends PlanResult {
  epics: Epic[];
}

export interface ProposedChange {
  file_path: string;
  diff: string;
  new_content: string;
}

export interface ImplementResult {
  plan: string;
  risks: string[];
  proposed_changes: ProposedChange[];
}

export type Severity = "low" | "medium" | "high";

export interface Finding {
  category: "correctness" | "security" | "performance" | "test_coverage" | string;
  severity: Severity;
  file_path: string;
  line: number | null;
  description: string;
}

export interface ReviewResult {
  summary: string;
  findings: Finding[];
}

export interface IngestResult {
  repo_id: string;
  files_scanned: number;
  files_indexed: number;
  files_skipped: number;
  chunks_indexed: number;
  files: number;
  symbols: number;
  imports: number;
  calls: number;
  endpoints: number;
}

export interface RepoListResult {
  repos: string[];
}

export interface ChatTurn {
  id: string;
  role: "user" | "assistant" | "error" | "system";
  text?: string;
  response?: CopilotResponse;
  ingest?: IngestResult;
  pending?: boolean;
}
