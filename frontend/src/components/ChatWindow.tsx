import { useEffect, useState } from "react";
import type { DemoUser, Step } from "../api/client";
import { useChat } from "../hooks/useChat";
import type { ChatTurn } from "../state/session";
import { ConfirmationCard } from "./ConfirmationCard";
import { ExcludedSourceLine, SourceCard } from "./SourceCard";
import { ToolTimeline } from "./ToolTimeline";

const CONFIDENCE_LABEL: Record<string, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
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
  const [resolved, setResolved] = useState<string | null>(null);
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
        <div className="escalation-hint">This can be escalated to a human specialist.</div>
      )}

      <ToolTimeline steps={envelope.steps} />

      {envelope.sources.length > 0 && (
        <div className="source-cards">
          {envelope.sources.map((s, i) => (
            <SourceCard key={i} source={s} />
          ))}
          {envelope.excluded_sources.map((e, i) => (
            <ExcludedSourceLine key={i} {...e} />
          ))}
        </div>
      )}

      {envelope.pending_action && !resolved && (
        <ConfirmationCard
          userId={userId}
          action={envelope.pending_action}
          onResolved={(r) => {
            setResolved(
              r.status === "confirmed"
                ? `Escalation ${r.escalation_id} confirmed.`
                : "Escalation rejected.",
            );
            onActionResolved();
          }}
        />
      )}
      {resolved && <div className="resolution-note">{resolved}</div>}
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
      <div className="composer">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder={
            composerLocked
              ? "Resolve the pending escalation to continue…"
              : `Ask as ${currentUser.display_name}…`
          }
          disabled={sending}
        />
        <button onClick={submit} disabled={sending || !draft.trim()}>
          Send
        </button>
      </div>
    </div>
  );
}
