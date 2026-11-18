import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  Check,
  Copy,
  FileText,
  Loader2,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { ApiError, ask, deleteSession, getSession, type AskResponse, type Session } from "../api";
import Countdown from "./Countdown";

interface Turn {
  role: "user" | "assistant";
  text: string;
  sources?: AskResponse["sources"];
}

const SUGGESTED = [
  "Summarize what this data covers",
  "What are the largest values in here?",
  "Anything unusual or worth noting?",
];

export default function SessionView({
  sessionId,
  onExit,
}: {
  sessionId: string;
  onExit: () => void;
}) {
  const [session, setSession] = useState<Session | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [gone, setGone] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    try {
      const s = await getSession(sessionId);
      setSession(s);
    } catch (e) {
      if (e instanceof ApiError && e.status === 410) setGone(true);
      else if (e instanceof ApiError && e.status === 404)
        setLoadError("No session at this address — the link may be wrong, or the session was deleted.");
      else setLoadError("Could not load this session — try refreshing the page.");
    }
  }, [sessionId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll while indexing (2s). Indexing runs in the background; the first
  // embedding call can take up to a minute on a cold start.
  useEffect(() => {
    if (!session || session.status !== "indexing") return;
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  }, [session?.status, refresh]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  async function send(question: string) {
    const q = question.trim();
    if (!q || asking) return;
    setInput("");
    setAskError(null);
    setTurns((t) => [...t, { role: "user", text: q }]);
    setAsking(true);
    try {
      const res = await ask(sessionId, q);
      setTurns((t) => [...t, { role: "assistant", text: res.answer, sources: res.sources }]);
    } catch (e) {
      setAskError(e instanceof ApiError ? e.message : "The answer failed — try again");
      setTurns((t) => t.slice(0, -1));
    } finally {
      setAsking(false);
    }
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard unavailable — the URL is in the address bar already
    }
  }

  async function handleDelete() {
    if (!window.confirm("Delete this session now? The vectors and record are removed immediately.")) return;
    setDeleting(true);
    try {
      await deleteSession(sessionId);
    } catch {
      // already gone is fine
    }
    onExit();
  }

  if (gone) {
    return (
      <div className="state-page">
        <p className="eyebrow mono">Session expired</p>
        <h1>This session is gone.</h1>
        <p className="lede">
          Its 7 days ran out, so the vectors and the record were deleted.
          Nothing of it remains — upload again to start a fresh session.
        </p>
        <button className="btn btn-primary" onClick={onExit}>
          <RotateCcw size={16} strokeWidth={1.5} />
          Start a new session
        </button>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="state-page">
        <p className="eyebrow mono">Session not found</p>
        <h1>Nothing here.</h1>
        <p className="lede">{loadError}</p>
        <button className="btn btn-primary" onClick={onExit}>
          <RotateCcw size={16} strokeWidth={1.5} />
          Start a new session
        </button>
      </div>
    );
  }

  if (!session) {
    return (
      <div className="state-page">
        <Loader2 size={20} className="spin muted" />
        <p className="lede">Loading session…</p>
      </div>
    );
  }

  const ready = session.status === "ready";
  const failed = session.status === "failed";

  return (
    <div className="session-view">
      <aside className="session-rail">
        <div className="rail-block">
          <p className="rail-label mono">File</p>
          <p className="rail-file">
            <FileText size={16} strokeWidth={1.5} />
            <span>{session.filename}</span>
          </p>
        </div>

        <div className="rail-block">
          <p className="rail-label mono">Status</p>
          <p className={`status-line ${session.status}`}>
            <span className="status-dot" />
            {session.status === "indexing" && `Indexing — ${session.chunks.toLocaleString()} chunks`}
            {session.status === "ready" && `Ready — ${session.chunks.toLocaleString()} chunks`}
            {session.status === "failed" && "Indexing failed"}
          </p>
          {session.status === "indexing" && (
            <p className="rail-note">
              {session.rows_read.toLocaleString()} rows read · first run can
              take a minute while the embedding service warms up
            </p>
          )}
          {failed && session.error && <p className="rail-note error">{session.error}</p>}
        </div>

        <div className="rail-block">
          <Countdown expiresAt={session.expires_at} createdAt={session.created_at} />
        </div>

        <div className="rail-block rail-actions">
          <button className="btn btn-ghost" onClick={copyLink}>
            {copied ? <Check size={16} strokeWidth={1.5} /> : <Copy size={16} strokeWidth={1.5} />}
            {copied ? "Link copied" : "Copy session link"}
          </button>
          <button className="btn btn-ghost danger" onClick={handleDelete} disabled={deleting}>
            <Trash2 size={16} strokeWidth={1.5} />
            Delete session now
          </button>
        </div>

        <p className="rail-id mono" title={session.id}>
          {session.id.slice(0, 8)}…{session.id.slice(-4)}
        </p>
      </aside>

      <section className="chat">
        <div className="chat-scroll">
          {turns.length === 0 && (
            <div className="chat-empty">
              {session.status === "indexing" && (
                <>
                  <Loader2 size={20} className="spin muted" />
                  <p>Indexing your data — questions open as soon as it&rsquo;s ready.</p>
                  <p className="chat-empty-meta mono">
                    {session.rows_read.toLocaleString()} rows read ·{" "}
                    {session.chunks.toLocaleString()} chunks embedded
                  </p>
                </>
              )}
              {failed && (
                <>
                  <p>Indexing failed, so there is nothing to ask yet.</p>
                  <p className="chat-empty-meta">{session.error}</p>
                  <button className="btn btn-secondary" onClick={onExit}>
                    Upload a different file
                  </button>
                </>
              )}
              {ready && (
                <>
                  <p>Your data is indexed. Ask anything about it — answers come with sources.</p>
                  <div className="suggestions">
                    {SUGGESTED.map((s) => (
                      <button key={s} className="suggestion" onClick={() => send(s)}>
                        {s}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {turns.map((turn, i) => (
            <div key={i} className={`turn ${turn.role}`}>
              <p className="turn-label mono">{turn.role === "user" ? "You" : "RAGDrop"}</p>
              <p className="turn-text">{turn.text}</p>
              {turn.sources && turn.sources.length > 0 && (
                <div className="sources">
                  <p className="sources-label mono">Sources</p>
                  {turn.sources.map((s, j) => (
                    <details key={j} className="source">
                      <summary>
                        <span className="source-index mono">[{j + 1}]</span>
                        <span className="source-ref">{s.source}</span>
                        <span className="source-score mono">{s.score.toFixed(2)}</span>
                      </summary>
                      <p className="source-text">{s.text}</p>
                    </details>
                  ))}
                </div>
              )}
            </div>
          ))}
          {asking && (
            <div className="turn assistant">
              <p className="turn-label mono">RAGDrop</p>
              <p className="turn-text muted">
                <Loader2 size={16} className="spin inline" /> Searching your data…
              </p>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        <form
          className="chat-input-row"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              ready ? "Ask about your data…" : "Indexing — questions open when ready"
            }
            disabled={!ready || asking}
            maxLength={2000}
            aria-label="Ask about your data"
          />
          <button
            type="submit"
            className="btn btn-primary btn-icon"
            disabled={!ready || asking || !input.trim()}
            aria-label="Send question"
          >
            <ArrowUp size={18} strokeWidth={1.5} />
          </button>
        </form>
        {askError && <p className="error-banner" role="alert">{askError}</p>}
      </section>
    </div>
  );
}
