import { useEffect, useState } from "react";
import { api, type DemoUser } from "./api/client";
import { ChatWindow } from "./components/ChatWindow";
import { SignalsBoard } from "./components/SignalsBoard";
import { useSession } from "./state/session";

export default function App() {
  const [users, setUsers] = useState<DemoUser[]>([]);
  const [tab, setTab] = useState<"chat" | "signals">("chat");
  const [prefill, setPrefill] = useState<string | null>(null);
  const { currentUser, switchUser, sessionId, turns, setTurns } = useSession();

  useEffect(() => {
    api.listUsers().then((r) => {
      setUsers(r.users);
      if (r.users.length > 0) switchUser(r.users[0]);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const isInternal = currentUser?.role === "support_agent" || currentUser?.role === "ops_lead";

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">ParcelPilot Support</div>

        {/* The role switcher: this is how access control gets demonstrated
            in one click, per the build spec's video requirement. */}
        <div className="user-switcher">
          <label>Viewing as</label>
          <select
            value={currentUser?.user_id ?? ""}
            onChange={(e) => {
              const u = users.find((x) => x.user_id === e.target.value);
              if (u) switchUser(u);
            }}
          >
            {users.map((u) => (
              <option key={u.user_id} value={u.user_id}>
                {u.display_name} — {u.role}
                {u.account_id ? ` (${u.account_id})` : ""}
              </option>
            ))}
          </select>
        </div>

        {isInternal && (
          <nav className="tabs">
            <button className={tab === "chat" ? "active" : ""} onClick={() => setTab("chat")}>
              Chat
            </button>
            <button className={tab === "signals" ? "active" : ""} onClick={() => setTab("signals")}>
              Signals
            </button>
          </nav>
        )}
      </header>

      <main className="app-main">
        {!currentUser ? (
          <div className="loading">Loading users…</div>
        ) : tab === "signals" && isInternal ? (
          <SignalsBoard
            userId={currentUser.user_id}
            onInvestigate={(question) => {
              // Prefilling connects the signals board back to the agent
              // rather than leaving it a dead dashboard.
              setPrefill(question);
              setTab("chat");
            }}
          />
        ) : (
          <ChatWindow
            currentUser={currentUser}
            sessionId={sessionId}
            turns={turns}
            setTurns={setTurns}
            prefill={prefill}
            onPrefillConsumed={() => setPrefill(null)}
          />
        )}
      </main>
    </div>
  );
}
