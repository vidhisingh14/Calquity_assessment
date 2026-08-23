import { useState } from "react";
import type { ChatEnvelope, DemoUser } from "../api/client";

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
  envelope?: ChatEnvelope;
}

export function useSession() {
  const [currentUser, setCurrentUser] = useState<DemoUser | null>(null);
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID());
  const [turns, setTurns] = useState<ChatTurn[]>([]);

  const switchUser = (user: DemoUser) => {
    // A fresh session per role switch keeps the access-control demo unambiguous:
    // no risk of stale history from one account leaking into the next.
    setCurrentUser(user);
    setSessionId(crypto.randomUUID());
    setTurns([]);
  };

  return { currentUser, switchUser, sessionId, turns, setTurns };
}
