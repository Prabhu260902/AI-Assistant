"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./Chat.module.css";

const REPO_DATALIST_ID = "known-repo-ids";

function parseIngestCommand(message: string): { source: string; repoId?: string } | null {
  if (!/^\/ingest\s+/i.test(message)) return null;
  const args = message.replace(/^\/ingest\s+/i, "").trim().split(/\s+/);
  if (args.length === 0 || !args[0]) return null;
  return { source: args[0], repoId: args[1] };
}

export default function ChatInput({
  disabled,
  repoId,
  onRepoIdChange,
  repoOptions,
  onSend,
  onIngest,
}: {
  disabled: boolean;
  repoId: string;
  onRepoIdChange: (repoId: string) => void;
  repoOptions: string[];
  onSend: (repoId: string, message: string) => void;
  onIngest: (source: string, repoId?: string) => void;
}) {
  const [message, setMessage] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [message]);

  const trimmedMessage = message.trim();
  const ingestCommand = parseIngestCommand(trimmedMessage);
  const canSubmit = disabled
    ? false
    : ingestCommand
      ? Boolean(ingestCommand.source)
      : Boolean(repoId.trim() && trimmedMessage);

  function submit() {
    if (!canSubmit) return;
    if (ingestCommand) {
      onIngest(ingestCommand.source, ingestCommand.repoId);
    } else {
      onSend(repoId.trim(), trimmedMessage);
    }
    setMessage("");
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <div className={styles.inputBar}>
      <div className={styles.repoRow}>
        <label className={styles.repoLabel} htmlFor="repo-id">
          Repo
        </label>
        <input
          id="repo-id"
          className={styles.repoInput}
          placeholder="e.g. hcp-crm"
          value={repoId}
          onChange={(e) => onRepoIdChange(e.target.value)}
          list={REPO_DATALIST_ID}
          spellCheck={false}
        />
        <datalist id={REPO_DATALIST_ID}>
          {repoOptions.map((id) => (
            <option value={id} key={id} />
          ))}
        </datalist>
        <span className={styles.repoHint}>or type /ingest &lt;path-or-url&gt; [repo_id] below to add one</span>
      </div>
      <div className={styles.composerRow}>
        <textarea
          ref={textareaRef}
          className={styles.textarea}
          placeholder="Ask about the repo, plan a feature, request a review, trace a flow… or /ingest <path-or-url> [repo_id]"
          rows={1}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
        />
        <button className={styles.sendButton} onClick={submit} disabled={!canSubmit}>
          {ingestCommand ? "Ingest" : "Send"}
        </button>
      </div>
    </div>
  );
}
