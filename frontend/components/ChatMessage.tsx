import type {
  AffectedModule,
  ArchitectureResult,
  Citation,
  CopilotResponse,
  Epic,
  Finding,
  ImplementResult,
  PlanResult,
  ReviewResult,
  SearchResult,
  Severity,
  TicketsResult,
} from "@/lib/types";
import MermaidDiagram from "./MermaidDiagram";
import styles from "./Chat.module.css";

function FormattedText({ text }: { text: string }) {
  const trimmed = text.trim();
  if (!trimmed) return null;

  const blocks = trimmed.split(/\n\s*\n/);
  return (
    <div className={styles.text}>
      {blocks.map((block, i) => {
        const lines = block
          .split("\n")
          .map((l) => l.trim())
          .filter(Boolean);
        const isBullet = lines.length > 0 && lines.every((l) => /^[-*]\s+/.test(l));
        const isNumbered = lines.length > 0 && lines.every((l) => /^\d+[.)]\s+/.test(l));

        if (isBullet) {
          return (
            <ul key={i}>
              {lines.map((l, j) => (
                <li key={j}>{l.replace(/^[-*]\s+/, "")}</li>
              ))}
            </ul>
          );
        }
        if (isNumbered) {
          return (
            <ol key={i}>
              {lines.map((l, j) => (
                <li key={j}>{l.replace(/^\d+[.)]\s+/, "")}</li>
              ))}
            </ol>
          );
        }
        return <p key={i}>{block.trim()}</p>;
      })}
    </div>
  );
}

function SeverityPill({ severity }: { severity: Severity | string }) {
  const cls =
    severity === "high" ? styles.pillHigh : severity === "medium" ? styles.pillMedium : styles.pillLow;
  return <span className={`${styles.pill} ${cls}`}>{severity}</span>;
}

function CitationChips({ citations }: { citations: Citation[] }) {
  if (!citations?.length) return null;
  return (
    <div className={styles.section}>
      <p className={styles.sectionLabel}>Sources</p>
      <div className={styles.citations}>
        {citations.map((c, i) => (
          <span className={styles.citationChip} key={i}>
            {c.file_path}:{c.start_line}-{c.end_line}
          </span>
        ))}
      </div>
    </div>
  );
}

function AffectedModulesTable({ modules }: { modules: AffectedModule[] }) {
  if (!modules?.length) return null;
  return (
    <div className={styles.section}>
      <p className={styles.sectionLabel}>Affected modules</p>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>File</th>
              <th>Reason</th>
              <th>Fan-in</th>
              <th>API</th>
            </tr>
          </thead>
          <tbody>
            {modules.map((m) => (
              <tr key={m.file_path}>
                <td>
                  <code>{m.file_path}</code>
                </td>
                <td>{m.reason}</td>
                <td>{m.fan_in}</td>
                <td>{m.has_api_endpoint ? "yes" : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RiskList({ risks }: { risks: string[] }) {
  if (!risks?.length) return null;
  return (
    <div className={styles.section}>
      <p className={styles.sectionLabel}>Risks</p>
      <ul className={styles.riskList}>
        {risks.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>
    </div>
  );
}

function TicketTree({ epics }: { epics: Epic[] }) {
  if (!epics?.length) return null;
  return (
    <div className={styles.section}>
      <p className={styles.sectionLabel}>Epics</p>
      {epics.map((epic, i) => (
        <details className={styles.epic} key={i} open>
          <summary>{epic.title}</summary>
          <p style={{ marginTop: ".4rem" }}>{epic.description}</p>
          {epic.stories.map((story, j) => (
            <div className={styles.story} key={j}>
              <h4>{story.title}</h4>
              <div className={styles.storyMeta}>
                <p>{story.description}</p>
                {story.acceptance_criteria.length > 0 && (
                  <>
                    <strong>Acceptance criteria</strong>
                    <ul>
                      {story.acceptance_criteria.map((c, k) => (
                        <li key={k}>{c}</li>
                      ))}
                    </ul>
                  </>
                )}
                {story.test_cases.length > 0 && (
                  <>
                    <strong>Test cases</strong>
                    <ul>
                      {story.test_cases.map((c, k) => (
                        <li key={k}>{c}</li>
                      ))}
                    </ul>
                  </>
                )}
                {story.tasks.length > 0 && (
                  <>
                    <strong>Tasks</strong>
                    <ul>
                      {story.tasks.map((t, k) => (
                        <li key={k}>{t.title}</li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            </div>
          ))}
        </details>
      ))}
    </div>
  );
}

function DiffBlock({ diff }: { diff: string }) {
  return (
    <pre className={styles.diff}>
      {diff.split("\n").map((line, i) => {
        const isAdd = line.startsWith("+") && !line.startsWith("+++");
        const isDel = line.startsWith("-") && !line.startsWith("---");
        const cls = isAdd ? styles.diffAdd : isDel ? styles.diffDel : undefined;
        return (
          <div key={i} className={cls}>
            {line.length ? line : " "}
          </div>
        );
      })}
    </pre>
  );
}

function FindingsList({ findings }: { findings: Finding[] }) {
  if (!findings?.length) return null;
  return (
    <div className={styles.section}>
      <p className={styles.sectionLabel}>Findings ({findings.length})</p>
      <div className={styles.findings}>
        {findings.map((f, i) => (
          <div className={styles.finding} key={i}>
            <div className={styles.findingHead}>
              <SeverityPill severity={f.severity} />
              <span className={styles.categoryTag}>{f.category}</span>
              <span className={styles.findingLocation}>
                {f.file_path}
                {f.line != null ? `:${f.line}` : ""}
              </span>
            </div>
            <p>{f.description}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ChatMessage({ response }: { response: CopilotResponse }) {
  const { intent, result } = response;

  switch (intent) {
    case "search": {
      const r = result as unknown as SearchResult;
      return (
        <div>
          <span className={styles.intentTag}>search</span>
          <FormattedText text={r.answer ?? ""} />
          <CitationChips citations={r.citations ?? []} />
        </div>
      );
    }
    case "architecture": {
      const r = result as unknown as ArchitectureResult;
      return (
        <div>
          <span className={styles.intentTag}>architecture</span>
          <FormattedText text={r.explanation ?? ""} />
          {r.mermaid_diagram ? (
            <div className={styles.section}>
              <p className={styles.sectionLabel}>Flow diagram</p>
              <MermaidDiagram source={r.mermaid_diagram} />
            </div>
          ) : null}
        </div>
      );
    }
    case "plan": {
      const r = result as unknown as PlanResult;
      return (
        <div>
          <span className={styles.intentTag}>plan</span>
          <FormattedText text={r.plan ?? ""} />
          <AffectedModulesTable modules={r.affected_modules ?? []} />
          <RiskList risks={r.risks ?? []} />
        </div>
      );
    }
    case "tickets": {
      const r = result as unknown as TicketsResult;
      return (
        <div>
          <span className={styles.intentTag}>tickets</span>
          <FormattedText text={r.plan ?? ""} />
          <TicketTree epics={r.epics ?? []} />
          <AffectedModulesTable modules={r.affected_modules ?? []} />
          <RiskList risks={r.risks ?? []} />
        </div>
      );
    }
    case "implement": {
      const r = result as unknown as ImplementResult;
      return (
        <div>
          <span className={styles.intentTag}>implement</span>
          <FormattedText text={r.plan ?? ""} />
          <RiskList risks={r.risks ?? []} />
          {r.proposed_changes?.length ? (
            <div className={styles.section}>
              <p className={styles.sectionLabel}>Proposed changes ({r.proposed_changes.length})</p>
              {r.proposed_changes.map((c, i) => (
                <div className={styles.changeBlock} key={i}>
                  <p className={styles.changePath}>{c.file_path}</p>
                  <DiffBlock diff={c.diff} />
                </div>
              ))}
            </div>
          ) : null}
        </div>
      );
    }
    case "review": {
      const r = result as unknown as ReviewResult;
      return (
        <div>
          <span className={styles.intentTag}>review</span>
          <FormattedText text={r.summary ?? ""} />
          <FindingsList findings={r.findings ?? []} />
        </div>
      );
    }
    default:
      return (
        <div>
          <span className={styles.intentTag}>{intent}</span>
          <pre className={styles.rawFallback}>{JSON.stringify(result, null, 2)}</pre>
        </div>
      );
  }
}
