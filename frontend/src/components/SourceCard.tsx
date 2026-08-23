import type { Source } from "../api/client";

const TIER_LABELS: Record<number, string> = {
  1: "Contract",
  2: "Current Policy",
  3: "SOP / Guide",
  4: "Ticket (context only)",
  5: "Deprecated",
};

export function SourceCard({ source }: { source: Source }) {
  return (
    <div className={`source-card tier-${source.tier}`}>
      <span className="source-tier-badge">{TIER_LABELS[source.tier] ?? `Tier ${source.tier}`}</span>
      <span className="source-doc-id">{source.doc_id}</span>
      {source.page != null && <span className="source-page">p.{source.page}</span>}
      {source.section && <span className="source-section">{source.section}</span>}
    </div>
  );
}

export function ExcludedSourceLine({ doc_id, reason }: { doc_id: string; reason: string }) {
  return (
    <div className="excluded-source">
      <em>{doc_id}</em> was excluded — {reason}
    </div>
  );
}
