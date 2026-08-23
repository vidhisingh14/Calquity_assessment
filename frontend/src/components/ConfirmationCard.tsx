import { useState } from "react";
import { api, type PendingAction } from "../api/client";

interface Props {
  userId: string;
  action: PendingAction;
  onResolved: (result: { status: string; escalation_id?: string }) => void;
}

export function ConfirmationCard({ userId, action, onResolved }: Props) {
  const [busy, setBusy] = useState(false);
  const preview = action.preview as Record<string, unknown>;

  const confirm = async () => {
    setBusy(true);
    try {
      const result = await api.confirmAction(userId, action.token);
      onResolved({ status: "confirmed", escalation_id: result.escalation_id });
    } finally {
      setBusy(false);
    }
  };

  const reject = async () => {
    setBusy(true);
    try {
      await api.rejectAction(userId, action.token);
      onResolved({ status: "rejected" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="confirmation-card">
      <div className="confirmation-header">Escalation — awaiting authorization</div>
      <dl className="confirmation-fields">
        <dt>Summary</dt>
        <dd>{String(preview.summary ?? "")}</dd>
        <dt>Severity</dt>
        <dd>{String(preview.severity ?? "")}</dd>
        <dt>Reason</dt>
        <dd>{String(preview.reason ?? "")}</dd>
        {preview.ticket_id != null && (
          <>
            <dt>Ticket</dt>
            <dd>{String(preview.ticket_id)}</dd>
          </>
        )}
        {preview.order_id != null && (
          <>
            <dt>Order</dt>
            <dd>{String(preview.order_id)}</dd>
          </>
        )}
      </dl>
      <div className="confirmation-note">
        Nothing is created until you confirm. This draft expires in {action.expires_in_minutes} minutes.
      </div>
      <div className="confirmation-buttons">
        <button className="confirm-btn" disabled={busy} onClick={confirm}>
          Confirm
        </button>
        <button className="reject-btn" disabled={busy} onClick={reject}>
          Reject
        </button>
      </div>
    </div>
  );
}
