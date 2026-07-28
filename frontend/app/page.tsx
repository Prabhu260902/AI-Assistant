"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ChatInput from "@/components/ChatInput";
import ChatMessage from "@/components/ChatMessage";
import IngestSummary from "@/components/IngestSummary";
import styles from "@/components/Chat.module.css";
import type { ChatTurn, CopilotResponse, IngestResult } from "@/lib/types";

const REPO_STORAGE_KEY = "allease.repoId";

function makeId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export default function Home() {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [pending, setPending] = useState(false);
  const [repoOptions, setRepoOptions] = useState<string[]>([]);
  const [repoId, setRepoId] = useState(() =>
    typeof window === "undefined" ? "" : window.localStorage.getItem(REPO_STORAGE_KEY) ?? "",
  );
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    window.localStorage.setItem(REPO_STORAGE_KEY, repoId);
  }, [repoId]);

  const refreshRepoOptions = useCallback(async () => {
    try {
      const res = await fetch("/api/repos");
      if (!res.ok) return;
      const data = await res.json();
      if (Array.isArray(data.repos)) setRepoOptions(data.repos);
    } catch {
      // repo list is a convenience (autocomplete only) — a failure here
      // shouldn't interrupt anything else on the page.
    }
  }, []);

  useEffect(() => {
    refreshRepoOptions();
  }, [refreshRepoOptions]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  async function handleSend(repoId: string, message: string) {
    const userTurn: ChatTurn = { id: makeId(), role: "user", text: message };
    const pendingId = makeId();
    setTurns((prev) => [...prev, userTurn, { id: pendingId, role: "assistant", pending: true }]);
    setPending(true);

    try {
      const res = await fetch("/api/copilot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_id: repoId, message }),
      });
      const data = await res.json();

      if (!res.ok || data.error) {
        setTurns((prev) =>
          prev.map((t) =>
            t.id === pendingId
              ? { ...t, role: "error", pending: false, text: data.error ?? data.detail ?? "Request failed." }
              : t,
          ),
        );
        return;
      }

      setTurns((prev) =>
        prev.map((t) => (t.id === pendingId ? { ...t, pending: false, response: data as CopilotResponse } : t)),
      );
    } catch (err) {
      setTurns((prev) =>
        prev.map((t) =>
          t.id === pendingId
            ? { ...t, role: "error", pending: false, text: err instanceof Error ? err.message : "Something went wrong." }
            : t,
        ),
      );
    } finally {
      setPending(false);
    }
  }

  async function handleIngest(source: string, repoId?: string) {
    const userTurn: ChatTurn = { id: makeId(), role: "user", text: `/ingest ${source}${repoId ? ` ${repoId}` : ""}` };
    const pendingId = makeId();
    setTurns((prev) => [...prev, userTurn, { id: pendingId, role: "system", pending: true }]);
    setPending(true);

    try {
      const res = await fetch("/api/repos", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source, repo_id: repoId }),
      });
      const data = await res.json();

      if (!res.ok || data.error) {
        setTurns((prev) =>
          prev.map((t) =>
            t.id === pendingId
              ? { ...t, role: "error", pending: false, text: data.error ?? data.detail ?? "Ingestion failed." }
              : t,
          ),
        );
        return;
      }

      const result = data as IngestResult;
      setTurns((prev) => prev.map((t) => (t.id === pendingId ? { ...t, pending: false, ingest: result } : t)));
      setRepoId(result.repo_id);
      refreshRepoOptions();
    } catch (err) {
      setTurns((prev) =>
        prev.map((t) =>
          t.id === pendingId
            ? { ...t, role: "error", pending: false, text: err instanceof Error ? err.message : "Something went wrong." }
            : t,
        ),
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <span className={styles.headerTitle}>AllEase Engineering Copilot</span>
        <span className={styles.headerSub}>search · plan · tickets · implement · review · architecture</span>
      </header>

      <div className={styles.messageList} ref={listRef}>
        {turns.length === 0 && (
          <p className={styles.emptyState}>
            Set a repo id below, then ask anything — &ldquo;What does search_hcps do?&rdquo;,
            &ldquo;Plan adding X&rdquo;, &ldquo;Review main vs feature/x&rdquo;, &ldquo;How does creating an
            HCP work?&rdquo; No repo ingested yet? Type{" "}
            <code>/ingest /path/to/repo repo-id</code> to add one.
          </p>
        )}

        {turns.map((turn) => {
          if (turn.role === "user") {
            return (
              <div className={`${styles.row} ${styles.rowUser}`} key={turn.id}>
                <div className={`${styles.bubble} ${styles.bubbleUser}`}>{turn.text}</div>
              </div>
            );
          }
          if (turn.role === "error") {
            return (
              <div className={`${styles.row} ${styles.rowError}`} key={turn.id}>
                <div className={`${styles.bubble} ${styles.bubbleError}`}>{turn.text}</div>
              </div>
            );
          }
          if (turn.role === "system") {
            return (
              <div className={`${styles.row} ${styles.rowSystem}`} key={turn.id}>
                {turn.pending ? (
                  <span className={styles.loading}>
                    <span className={styles.loadingDot} />
                    <span className={styles.loadingDot} />
                    <span className={styles.loadingDot} />
                  </span>
                ) : turn.ingest ? (
                  <IngestSummary result={turn.ingest} />
                ) : null}
              </div>
            );
          }
          return (
            <div className={`${styles.row} ${styles.rowAssistant}`} key={turn.id}>
              <div className={`${styles.bubble} ${styles.bubbleAssistant}`}>
                {turn.pending ? (
                  <span className={styles.loading}>
                    <span className={styles.loadingDot} />
                    <span className={styles.loadingDot} />
                    <span className={styles.loadingDot} />
                  </span>
                ) : turn.response ? (
                  <ChatMessage response={turn.response} />
                ) : null}
              </div>
            </div>
          );
        })}
      </div>

      <ChatInput
        disabled={pending}
        repoId={repoId}
        onRepoIdChange={setRepoId}
        repoOptions={repoOptions}
        onSend={handleSend}
        onIngest={handleIngest}
      />
    </div>
  );
}
