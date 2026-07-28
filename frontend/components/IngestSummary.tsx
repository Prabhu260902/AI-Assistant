import type { IngestProgressEvent, IngestResult } from "@/lib/types";
import styles from "./Chat.module.css";

const PHASE_LABELS: Record<string, string> = {
  indexing: "Indexing files",
  embedding: "Embedding chunks",
  knowledge_graph: "Building knowledge graph",
};

export function IngestProgressBar({ progress }: { progress: IngestProgressEvent }) {
  return (
    <div className={styles.systemCard}>
      <p className={styles.systemTitle}>
        {PHASE_LABELS[progress.phase] ?? progress.phase} — {progress.current}/{progress.total}
      </p>
      <progress className={styles.progressBar} value={progress.current} max={progress.total || 1} />
    </div>
  );
}

export default function IngestSummary({ result }: { result: IngestResult }) {
  const stats: [string, number][] = [
    ["Files indexed", result.files_indexed],
    ["Chunks", result.chunks_indexed],
    ["Symbols", result.symbols],
    ["Imports", result.imports],
    ["Calls", result.calls],
    ["Endpoints", result.endpoints],
  ];

  return (
    <div className={styles.systemCard}>
      <p className={styles.systemTitle}>
        Ingested <code>{result.repo_id}</code>
      </p>
      <div className={styles.statGrid}>
        {stats.map(([label, value]) => (
          <div className={styles.stat} key={label}>
            <span className={styles.statValue}>{value}</span>
            <span className={styles.statLabel}>{label}</span>
          </div>
        ))}
      </div>
      <p className={styles.systemFootnote}>
        {result.files_scanned} files scanned, {result.files_skipped} skipped. You can query{" "}
        <code>{result.repo_id}</code> now.
      </p>
    </div>
  );
}
