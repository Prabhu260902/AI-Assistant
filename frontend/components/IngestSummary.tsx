import type { IngestResult } from "@/lib/types";
import styles from "./Chat.module.css";

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
