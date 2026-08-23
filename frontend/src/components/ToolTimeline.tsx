import type { Step } from "../api/client";

// Short, terse, uppercase by CSS -- these read as scan-event codes
// ("ARRIVED AT FACILITY") rather than sentence fragments.
const TOOL_LABELS: Record<string, string> = {
  lookup_records: "Record lookup",
  search_documents: "Document search",
  evaluate_policy: "Policy check",
  create_escalation: "Escalation draft",
};

export function ToolTimeline({ steps }: { steps: Step[] }) {
  if (steps.length === 0) return null;
  return (
    <div className="tool-timeline">
      {steps.map((step, i) => (
        <div key={i} className={`tool-step ${step.ok ? "ok" : "error"}`}>
          <span className="tool-step-icon">{step.ok ? "✓" : "✕"}</span>
          <span className="tool-step-name">
            {TOOL_LABELS[step.tool] ?? step.tool}
          </span>
          <span className="tool-step-args">{step.args_summary}</span>
          <span className="tool-step-ms">{step.ms}ms</span>
        </div>
      ))}
    </div>
  );
}
