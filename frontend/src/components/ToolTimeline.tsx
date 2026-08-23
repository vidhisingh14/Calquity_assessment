import type { Step } from "../api/client";

const TOOL_LABELS: Record<string, string> = {
  lookup_records: "Looking up records",
  search_documents: "Searching documents",
  evaluate_policy: "Evaluating policy",
  create_escalation: "Preparing escalation",
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
