import { useEffect, useState } from "react";
import { api, type DemoUser } from "./api/client";
import { ChatWindow } from "./components/ChatWindow";
import { SignalsBoard } from "./components/SignalsBoard";
import { useSession } from "./state/session";

const RETRY_INTERVAL_MS = 3000;

// The notice must be readable on every load, not just a slow one. A warm
// backend can answer in under a second, and without a floor the notice
// flashes and vanishes before anyone can read it -- which is worse than not
// showing it at all, since it looks like a glitch. So it stays up for at
// least this long regardless of how fast the backend actually responds; the
// close button is the escape hatch for someone who doesn't want to wait it
// out.
const MIN_NOTICE_MS = 3000;

export default function App() {
  const [users, setUsers] = useState<DemoUser[]>([]);
  const [tab, setTab] = useState<"chat" | "signals">("chat");
  const [prefill, setPrefill] = useState<string | null>(null);
  const [backendReady, setBackendReady] = useState(false);
  const [minTimeElapsed, setMinTimeElapsed] = useState(false);
  const [noticeDismissed, setNoticeDismissed] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const { currentUser, switchUser, sessionId, turns, setTurns } = useSession();

  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout>;

    // Free-tier Render spins the backend down after inactivity and takes
    // 15-20s to cold-start it on the next request. A failed or hanging
    // FIRST request here is the expected shape of a cold start, not a real
    // error, so this retries quietly rather than giving up and leaving the
    // screen stuck on an unexplained "Loading users..." forever.
    const attempt = () => {
      api
        .listUsers()
        .then((r) => {
          if (cancelled) return;
          setUsers(r.users);
          setBackendReady(true);
          if (r.users.length > 0) switchUser(r.users[0]);
        })
        .catch(() => {
          if (cancelled) return;
          retryTimer = setTimeout(attempt, RETRY_INTERVAL_MS);
        });
    };
    attempt();

    const minTimer = setTimeout(() => setMinTimeElapsed(true), MIN_NOTICE_MS);
    const clock = setInterval(() => setElapsedSeconds((s) => s + 1), 1000);

    return () => {
      cancelled = true;
      clearTimeout(retryTimer);
      clearTimeout(minTimer);
      clearInterval(clock);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Shown until BOTH the backend has actually answered and the minimum
  // readable duration has passed -- whichever takes longer -- or until the
  // visitor closes it themselves.
  const showNotice = !noticeDismissed && (!backendReady || !minTimeElapsed);
  const isInternal = currentUser?.role === "support_agent" || currentUser?.role === "ops_lead";

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">ParcelPilot</span>
          <span className="brand-kicker">Support Dispatch</span>
        </div>

        {/* The role switcher: this is how access control gets demonstrated
            in one click, per the build spec's video requirement. */}
        <div className="user-switcher">
          <label>Viewing as</label>
          <select
            value={currentUser?.user_id ?? ""}
            disabled={!backendReady}
            onChange={(e) => {
              const u = users.find((x) => x.user_id === e.target.value);
              if (u) switchUser(u);
            }}
          >
            {!backendReady && <option value="">Waking up…</option>}
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
              Console
            </button>
            <button className={tab === "signals" ? "active" : ""} onClick={() => setTab("signals")}>
              Board
            </button>
          </nav>
        )}
      </header>

      <main className="app-main">
        {showNotice ? (
          <div className="waking-notice">
            <button
              className="waking-close"
              onClick={() => setNoticeDismissed(true)}
              aria-label="Dismiss"
              title="Dismiss"
            >
              ×
            </button>
            <div className="waking-stamp">Waking Dispatch</div>
            <p>
              <span className="waking-pulse" aria-hidden="true" />
              This demo runs on free-tier hosting that sleeps after a few
              minutes of inactivity. It's booting up now — usually back
              within 20&ndash;30 seconds.
            </p>
            {elapsedSeconds > 25 && (
              <p>Still on it — a cold start can occasionally run a bit longer.</p>
            )}
            <p className="waking-elapsed">{elapsedSeconds}s elapsed</p>
          </div>
        ) : !currentUser ? (
          // Reachable only if the notice was closed before the backend
          // actually answered -- keep some acknowledgement on screen rather
          // than going back to the silent blank state this was built to fix.
          <div className="loading">Connecting…</div>
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
