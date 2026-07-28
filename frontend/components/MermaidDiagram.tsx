"use client";

import { useEffect, useId, useRef, useState } from "react";
import styles from "./Chat.module.css";

let configured = false;

export default function MermaidDiagram({ source }: { source: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const reactId = useId().replace(/[^a-zA-Z0-9]/g, "");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function render() {
      const mermaid = (await import("mermaid")).default;
      if (!configured) {
        mermaid.initialize({ startOnLoad: false, theme: "neutral", securityLevel: "strict" });
        configured = true;
      }
      try {
        const { svg } = await mermaid.render(`mermaid-${reactId}`, source);
        if (!cancelled && containerRef.current) {
          containerRef.current.innerHTML = svg;
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
    }

    render();
    return () => {
      cancelled = true;
    };
  }, [source, reactId]);

  if (error) {
    return (
      <details className={styles.diagramFallback}>
        <summary>Couldn&apos;t render diagram ({error}) — show raw Mermaid source</summary>
        <pre>{source}</pre>
      </details>
    );
  }

  return <div className={styles.diagram} ref={containerRef} />;
}
