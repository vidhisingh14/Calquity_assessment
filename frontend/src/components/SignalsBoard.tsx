import { useEffect, useState } from "react";
import { api, type Signal } from "../api/client";

const SEVERITY_ORDER = ["urgent", "high", "medium", "low"];

export function SignalsBoard({
  userId,
  onInvestigate,
}: {
  userId: string;
  onInvestigate: (question: string) => void;
}) {
  const [signals, setSignals] = useState<Signal[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getSignals(userId)
      .then((r) => setSignals(r.signals))
      .catch((e) => setError(String(e)));
  }, [userId]);

  if (error) return <div className="signals-error">{error}</div>;
  if (!signals) return <div className="signals-loading">Loading signals…</div>;

  const grouped = SEVERITY_ORDER.map((sev) => ({
    severity: sev,
    items: signals.filter((s) => s.severity === sev),
  })).filter((g) => g.items.length > 0);

  if (grouped.length === 0) {
    return <div className="signals-empty">No open signals right now.</div>;
  }

  return (
    <div className="signals-board">
      {grouped.map((g) => (
        <div key={g.severity} className={`signal-group sev-${g.severity}`}>
          <div className="signal-group-header">{g.severity.toUpperCase()}</div>
          {g.items.map((s) => (
            <button
              key={s.signal_id}
              className="signal-item"
              onClick={() =>
                onInvestigate(
                  `Investigate this signal: ${s.title} (${s.signal_type}). ` +
                    `Detail: ${JSON.stringify(s.detail)}`,
                )
              }
            >
              <span className="signal-title">{s.title}</span>
              <span className="signal-accounts">
                {s.affected_accounts.length > 0
                  ? s.affected_accounts.join(", ")
                  : "no account link"}
              </span>
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}
