import { useCallback, useState } from "react";
import { api, type ChatEnvelope, type Step } from "../api/client";
import type { ChatTurn } from "../state/session";

export function useChat(
  userId: string | undefined,
  sessionId: string,
  turns: ChatTurn[],
  setTurns: (updater: (prev: ChatTurn[]) => ChatTurn[]) => void,
) {
  const [liveSteps, setLiveSteps] = useState<Step[]>([]);
  const [sending, setSending] = useState(false);

  const send = useCallback(
    (message: string) => {
      if (!userId || sending) return;
      setSending(true);
      setLiveSteps([]);
      setTurns((prev) => [...prev, { role: "user", content: message }]);

      const finish = (envelope: ChatEnvelope) => {
        setTurns((prev) => [
          ...prev,
          { role: "assistant", content: envelope.answer, envelope },
        ]);
        setLiveSteps([]);
        setSending(false);
      };

      // Streaming is the default: the tool timeline updates live, which is
      // the single most convincing thing in a demo. Fall back to a plain
      // POST if the stream errors, so the chat never just goes silent.
      api.streamMessage(
        userId,
        sessionId,
        message,
        (step) => setLiveSteps((prev) => [...prev, step]),
        finish,
        () => {
          api.sendMessage(userId, sessionId, message).then(finish).catch(() => {
            setSending(false);
          });
        },
      );
    },
    [userId, sessionId, sending, setTurns],
  );

  return { send, liveSteps, sending };
}
