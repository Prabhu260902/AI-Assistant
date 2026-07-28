import type { LlmStatus } from "@/lib/types";
import styles from "./Chat.module.css";

export default function GroqStatus({ status }: { status: LlmStatus | null }) {
  if (!status?.available || status.remaining_tokens == null || status.limit_tokens == null) {
    return null;
  }

  const ratio = status.limit_tokens > 0 ? status.remaining_tokens / status.limit_tokens : 1;
  const level = ratio < 0.15 ? styles.quotaLow : ratio < 0.4 ? styles.quotaMedium : styles.quotaOk;

  return (
    <span className={`${styles.quotaBadge} ${level}`} title={`${status.model ?? "groq"} — resets per minute`}>
      {status.remaining_tokens.toLocaleString()} / {status.limit_tokens.toLocaleString()} tok/min
    </span>
  );
}
