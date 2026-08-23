export interface Step {
  tool: string;
  args_summary: string;
  ok: boolean;
  ms: number;
  error: string | null;
}

export interface Source {
  chunk_id?: number;
  doc_id: string;
  tier: number;
  page?: number | null;
  section?: string | null;
  score?: number;
  // Actually named in the answer (prose mention or a verdict's governing
  // source), vs. merely retrieved by search_documents. A vague question can
  // retrieve up to RETRIEVAL_K chunks the answer never draws on.
  cited?: boolean;
}

export interface Verdict {
  rule: string;
  outcome: string;
  reason_code: string;
  amount_inr: number | null;
  override_applied: boolean;
  governing_source: string | null;
  caveats: string[];
  working: string[];
}

export interface PendingAction {
  status: string;
  token: string;
  action_type: string;
  preview: Record<string, unknown>;
  expires_in_minutes: number;
}

export interface ChatEnvelope {
  session_id: string;
  answer: string;
  confidence: "high" | "medium" | "low";
  sources: Source[];
  steps: Step[];
  conflicts: unknown[];
  excluded_sources: { doc_id: string; reason: string }[];
  verdicts: Verdict[];
  pending_action: PendingAction | null;
  escalation_offered: boolean;
  validator_flags: { check: string; detail: string; severity: string }[];
}

export interface DemoUser {
  user_id: string;
  display_name: string;
  role: "customer" | "support_agent" | "ops_lead";
  account_id: string | null;
}

export interface Signal {
  signal_id: string;
  signal_type: string;
  severity: string;
  title: string;
  detail: Record<string, unknown>;
  affected_accounts: string[];
  status: string;
}

// Empty string = same-origin relative paths, which is what the Vite dev
// proxy and a same-domain production deploy both want. The Docker compose
// `web` service serves a static build with no proxy, so it needs an
// absolute base pointing at the api container's published port.
const API_BASE = import.meta.env.VITE_API_BASE ?? "";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listUsers: (): Promise<{ users: DemoUser[] }> =>
    fetch(`${API_BASE}/users`).then((r) => json<{ users: DemoUser[] }>(r)),

  sendMessage: (userId: string, sessionId: string, message: string): Promise<ChatEnvelope> =>
    fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-User-Id": userId },
      body: JSON.stringify({ session_id: sessionId, message }),
    }).then((r) => json<ChatEnvelope>(r)),

  streamMessage: (
    userId: string,
    sessionId: string,
    message: string,
    onStep: (step: Step) => void,
    onAnswer: (envelope: ChatEnvelope) => void,
    onError: (err: Error) => void,
  ): void => {
    fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        "X-User-Id": userId,
      },
      body: JSON.stringify({ session_id: sessionId, message }),
    })
      .then(async (res) => {
        if (!res.ok || !res.body) {
          throw new Error(`${res.status}: ${await res.text()}`);
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const events = buffer.split("\n\n");
          buffer = events.pop() ?? "";
          for (const raw of events) {
            const lines = raw.split("\n");
            const eventLine = lines.find((l) => l.startsWith("event: "));
            const dataLine = lines.find((l) => l.startsWith("data: "));
            if (!eventLine || !dataLine) continue;
            const eventName = eventLine.slice("event: ".length);
            const data = JSON.parse(dataLine.slice("data: ".length));
            if (eventName === "step") onStep(data as Step);
            if (eventName === "answer") onAnswer(data as ChatEnvelope);
          }
        }
      })
      .catch(onError);
  },

  confirmAction: (userId: string, token: string): Promise<{ escalation_id: string; status: string }> =>
    fetch(`${API_BASE}/actions/${token}/confirm`, {
      method: "POST",
      headers: { "X-User-Id": userId },
    }).then((r) => json<{ escalation_id: string; status: string }>(r)),

  rejectAction: (userId: string, token: string, reason?: string): Promise<{ status: string }> =>
    fetch(`${API_BASE}/actions/${token}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-User-Id": userId },
      body: JSON.stringify({ reason }),
    }).then((r) => json<{ status: string }>(r)),

  getSignals: (userId: string): Promise<{ signals: Signal[] }> =>
    fetch(`${API_BASE}/signals`, { headers: { "X-User-Id": userId } }).then((r) => json<{ signals: Signal[] }>(r)),
};
