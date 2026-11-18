import { useCallback, useEffect, useState } from "react";
import Home from "./components/Home";
import SessionView from "./components/SessionView";

function sessionIdFromPath(): string | null {
  const match = window.location.pathname.match(/^\/s\/([0-9a-f-]{36})\/?$/i);
  return match ? match[1] : null;
}

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(() => sessionIdFromPath());

  const goHome = useCallback(() => {
    window.history.pushState(null, "", "/");
    setSessionId(null);
  }, []);

  const goSession = useCallback((id: string) => {
    window.history.pushState(null, "", `/s/${id}`);
    setSessionId(id);
  }, []);

  useEffect(() => {
    const onPop = () => setSessionId(sessionIdFromPath());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <button className="wordmark" onClick={goHome} aria-label="RAGDrop home">
          <span className="wordmark-mark" aria-hidden="true" />
          RAGDrop
        </button>
        <p className="topbar-tag mono">Your data · 7 days · then gone</p>
      </header>
      <main className="main">
        {sessionId ? (
          <SessionView sessionId={sessionId} onExit={goHome} />
        ) : (
          <Home onSession={goSession} />
        )}
      </main>
      <footer className="footer mono">
        <span>No account · no data kept past expiry</span>
        <span>Answers cite their sources</span>
      </footer>
    </div>
  );
}
