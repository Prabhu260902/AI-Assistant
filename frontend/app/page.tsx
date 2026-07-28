"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ChatInput from "@/components/ChatInput";
import ChatMessage from "@/components/ChatMessage";
import GroqStatus from "@/components/GroqStatus";
import IngestSummary, { IngestProgressBar } from "@/components/IngestSummary";
import styles from "@/components/Chat.module.css";
import type { ChatTurn, CopilotResponse, IngestStreamEvent, LlmStatus } from "@/lib/types";

const REPO_STORAGE_KEY = "allease.repoId";

function makeId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function updateTurn(id: string, patch: Partial<ChatTurn>) {
  return (prev: ChatTurn[]) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t));
}

export default function Home() {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [pending, setPending] = useState(false);
  const [repoOptions, setRepoOptions] = useState<string[]>([]);
  const [llmStatus, setLlmStatus] = useState<LlmStatus | null>(null);
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

  const refreshLlmStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/llm-status");
      if (!res.ok) return;
      setLlmStatus((await res.json()) as LlmStatus);
    } catch {
      // same as above — a badge failing to update shouldn't interrupt anything.
    }
  }, []);

  // Inlined rather than delegated to refreshRepoOptions/refreshLlmStatus
  // (used elsewhere, after handleSend/handleIngest) — an effect that calls
  // a named useCallback-wrapped setter trips this project's react-hooks
  // lint config even when the setState is behind an await; an inline async
  // IIFE with its own cancellation guard is the pattern it accepts.
  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const res = await fetch("/api/repos");
        if (!res.ok || cancelled) return;
        const data = await res.json();
        if (!cancelled && Array.isArray(data.repos)) setRepoOptions(data.repos);
      } catch {
        // repo list is a convenience (autocomplete only) — ignore failures.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const res = await fetch("/api/llm-status");
        if (!res.ok || cancelled) return;
        const data = (await res.json()) as LlmStatus;
        if (!cancelled) setLlmStatus(data);
      } catch {
        // status badge is best-effort — ignore failures.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

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
        setTurns(
          updateTurn(pendingId, {
            role: "error",
            pending: false,
            text: data.error ?? data.detail ?? "Request failed.",
          }),
        );
        return;
      }

      setTurns(updateTurn(pendingId, { pending: false, response: data as CopilotResponse }));
      refreshLlmStatus();
    } catch (err) {
      setTurns(
        updateTurn(pendingId, {
          role: "error",
          pending: false,
          text: err instanceof Error ? err.message : "Something went wrong.",
        }),
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
      const res = await fetch("/api/repos/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source, repo_id: repoId }),
      });

      if (!res.ok || !res.body) {
        const data = await res.json().catch(() => ({}));
        setTurns(
          updateTurn(pendingId, {
            role: "error",
            pending: false,
            text: data.error ?? data.detail ?? "Ingestion failed.",
          }),
        );
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      readLoop: while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let newlineIndex: number;
        while ((newlineIndex = buffer.indexOf("\n")) !== -1) {
          const line = buffer.slice(0, newlineIndex).trim();
          buffer = buffer.slice(newlineIndex + 1);
          if (!line) continue;

          const event = JSON.parse(line) as IngestStreamEvent;

          if (event.phase === "done") {
            setTurns(updateTurn(pendingId, { pending: false, progress: undefined, ingest: event.summary }));
            setRepoId(event.summary.repo_id);
            refreshRepoOptions();
            break readLoop;
          }
          if (event.phase === "error") {
            setTurns(updateTurn(pendingId, { role: "error", pending: false, text: event.message }));
            break readLoop;
          }
          setTurns(updateTurn(pendingId, { pending: false, progress: event }));
        }
      }
    } catch (err) {
      setTurns(
        updateTurn(pendingId, {
          role: "error",
          pending: false,
          text: err instanceof Error ? err.message : "Something went wrong.",
        }),
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <span className={styles.headerTitle}>AllEase Engineering Copilot</span>
        <div className={styles.headerRight}>
          <GroqStatus status={llmStatus} />
          <span className={styles.headerSub}>search · plan · tickets · implement · review · architecture</span>
        </div>
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
                {turn.ingest ? (
                  <IngestSummary result={turn.ingest} />
                ) : turn.progress ? (
                  <IngestProgressBar progress={turn.progress} />
                ) : (
                  <span className={styles.loading}>
                    <span className={styles.loadingDot} />
                    <span className={styles.loadingDot} />
                    <span className={styles.loadingDot} />
                  </span>
                )}
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
