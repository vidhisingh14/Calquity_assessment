import { useEffect, useState } from "react";
import type { DemoUser, Step } from "../api/client";
import { useChat } from "../hooks/useChat";
import type { ChatTurn } from "../state/session";
import { ConfirmationCard } from "./ConfirmationCard";
import { ExcludedSourceLine, SourceCard } from "./SourceCard";
import { ToolTimeline } from "./ToolTimeline";

// The signature element: a customs-clearance stamp standing in for the
// validator's derived confidence. CLEARED / REVIEW / HOLD reads as freight
// paperwork and names the real mechanism -- whether a human should look at
// this -- more plainly than a generic "confidence" pill would.
const CONFIDENCE_LABEL: Record<string, string> = {
  high: "Cleared",
  medium: "Review",
  low: "Hold",
};

function AssistantTurn({
  turn,
  userId,
  isLast,
  onActionResolved,
  onActionShown,
}: {
  turn: ChatTurn;
  userId: string;
  isLast: boolean;
  onActionResolved: () => void;
  onActionShown: () => void;
}) {
  const [resolved, setResolved] = useState<{ text: string; status: "confirmed" | "declined" } | null>(
    null,
  );
  const envelope = turn.envelope;

  useEffect(() => {
    if (isLast && envelope?.pending_action && !resolved) onActionShown();
  }, [isLast, envelope?.pending_action, resolved]);

  if (!envelope) return <div className="bubble assistant">{turn.content}</div>;

  return (
    <div className="bubble assistant">
      <div className="answer-text">{turn.content}</div>

      <div className={`confidence-badge ${envelope.confidence}`}>
        {CONFIDENCE_LABEL[envelope.confidence]}
      </div>

      {envelope.escalation_offered && !envelope.pending_action && (
        <div className="escalation-hint">Flagged for a specialist to pick up.</div>
      )}

      <ToolTimeline steps={envelope.steps} />

      {(() => {
        // search_documents can retrieve up to RETRIEVAL_K chunks on one vague
        // question ("can I cancel order", no order ID) that the model never
        // ends up drawing on -- a clarifying-question turn shouldn't stamp
        // eight source cards as if they all backed the answer. Only sources
        // actually named in the prose or a verdict's governing_source get the
        // full stamp treatment; the rest fold into one quiet line, same
        // pattern as excluded_sources below.
        const cited = envelope.sources.filter((s) => s.cited);
        const consulted = envelope.sources.filter((s) => !s.cited);
        if (cited.length === 0 && consulted.length === 0 && envelope.excluded_sources.length === 0) {
          return null;
        }
        return (
          <div className="source-cards">
            {cited.map((s, i) => (
              <SourceCard key={i} source={s} />
            ))}
            {consulted.length > 0 && (
              <div className="consulted-note">
                Also consulted, not cited: {consulted.map((s) => s.doc_id).join(", ")}
              </div>
            )}
            {envelope.excluded_sources.map((e, i) => (
              <ExcludedSourceLine key={i} {...e} />
            ))}
          </div>
        );
      })()}

      {envelope.pending_action && !resolved && (
        <ConfirmationCard
          userId={userId}
          action={envelope.pending_action}
          onResolved={(r) => {
            setResolved(
              r.status === "confirmed"
                ? { text: `Authorized — escalation ${r.escalation_id} created.`, status: "confirmed" }
                : { text: "Declined — no escalation created.", status: "declined" },
            );
            onActionResolved();
          }}
        />
      )}
      {resolved && (
        <div className={`resolution-note ${resolved.status}`}>{resolved.text}</div>
      )}
    </div>
  );
}

export function ChatWindow({
  currentUser,
  sessionId,
  turns,
  setTurns,
  prefill,
  onPrefillConsumed,
}: {
  currentUser: DemoUser;
  sessionId: string;
  turns: ChatTurn[];
  setTurns: (updater: (prev: ChatTurn[]) => ChatTurn[]) => void;
  prefill?: string | null;
  onPrefillConsumed?: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [pendingUnresolved, setPendingUnresolved] = useState(false);
  const { send, liveSteps, sending } = useChat(currentUser.user_id, sessionId, turns, setTurns);

  useEffect(() => {
    if (prefill) {
      setDraft(prefill);
      onPrefillConsumed?.();
    }
  }, [prefill]);

  // The confirmation gate is visible, not implied: the composer locks while a
  // pending action sits unresolved. AssistantTurn owns resolution state and
  // reports back up through onActionResolved / onActionShown.
  const composerLocked = pendingUnresolved;

  const submit = () => {
    if (!draft.trim() || sending) return;
    send(draft.trim());
    setDraft("");
  };

  return (
    <div className="chat-window">
      <div className="messages-scroll">
        <div className="messages">
          {turns.map((turn, i) =>
            turn.role === "user" ? (
              <div key={i} className="bubble user">
                {turn.content}
              </div>
            ) : (
              <AssistantTurn
                key={i}
                turn={turn}
                userId={currentUser.user_id}
                isLast={i === turns.length - 1}
                onActionResolved={() => setPendingUnresolved(false)}
                onActionShown={() => setPendingUnresolved(true)}
              />
            ),
          )}
          {sending && (
            <div className="bubble assistant pending">
              <ToolTimeline steps={liveSteps} />
              {liveSteps.length === 0 && <span className="thinking">Thinking…</span>}
            </div>
          )}
        </div>
      </div>
      <div className="composer">
        <div className="composer-inner">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder={
              composerLocked
                ? "Resolve the pending escalation to continue…"
                : `Ask as ${currentUser.display_name}…`
            }
            disabled={sending || composerLocked}
          />
          <button onClick={submit} disabled={sending || composerLocked || !draft.trim()}>
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
