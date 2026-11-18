import { useRef, useState } from "react";
import { Database, FileUp, FlaskConical, Loader2, ShieldCheck, Timer } from "lucide-react";
import { ApiError, loadSample, uploadFile } from "../api";

const ACCEPT = ".csv,.txt,.md,.pdf,.zip";

export default function Home({ onSession }: { onSession: (id: string) => void }) {
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleFile(file: File | undefined) {
    if (!file || busy) return;
    setBusy(true);
    setError(null);
    try {
      const session = await uploadFile(file);
      onSession(session.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Upload failed — try again");
      setBusy(false);
    }
  }

  async function handleSample() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const session = await loadSample();
      onSession(session.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load the sample");
      setBusy(false);
    }
  }

  return (
    <div className="home">
      <section className="hero">
        <p className="eyebrow mono">Ephemeral retrieval playground</p>
        <h1>
          Drop in your data.
          <br />
          Ask it questions.
          <br />
          <span className="accent">It disappears in 7 days.</span>
        </h1>
        <p className="lede">
          No account, no signup. Your file is chunked and embedded, you get a
          private link, and when the session expires the vectors and the
          record are deleted — nothing is kept.
        </p>
      </section>

      <section className="upload-shell">
        <div
          className={`dropzone ${dragging ? "dragging" : ""} ${busy ? "busy" : ""}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            handleFile(e.dataTransfer.files[0]);
          }}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter") inputRef.current?.click();
          }}
          aria-label="Upload a file"
        >
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            hidden
            onChange={(e) => handleFile(e.target.files?.[0])}
          />
          <div className="dropzone-icon">
            {busy ? (
              <Loader2 size={20} className="spin" />
            ) : (
              <FileUp size={20} strokeWidth={1.5} />
            )}
          </div>
          <p className="dropzone-title">
            {busy ? "Uploading…" : "Drop a file here, or click to choose one"}
          </p>
          <p className="dropzone-meta mono">
            CSV · TXT · Markdown · PDF · ZIP of those — up to 25 MB
          </p>
        </div>

        <div className="upload-actions">
          <button
            className="btn btn-secondary"
            onClick={handleSample}
            disabled={busy}
          >
            <FlaskConical size={16} strokeWidth={1.5} />
            Load sample dataset
          </button>
          <span className="upload-note">
            36 fictional coffee orders — try “Which region ordered the most
            espresso?”
          </span>
        </div>

        {error && <p className="error-banner" role="alert">{error}</p>}
      </section>

      <section className="facts">
        <div className="fact">
          <Timer size={18} strokeWidth={1.5} />
          <div>
            <h2>7-day lifetime</h2>
            <p>
              Every session expires 7 days after creation. The countdown is
              always visible; expiry deletes the vectors and the record.
            </p>
          </div>
        </div>
        <div className="fact">
          <ShieldCheck size={18} strokeWidth={1.5} />
          <div>
            <h2>Private by link</h2>
            <p>
              No accounts. The session link is an unguessable address, and one
              session can never see another session&rsquo;s data.
            </p>
          </div>
        </div>
        <div className="fact">
          <Database size={18} strokeWidth={1.5} />
          <div>
            <h2>Your file is not kept</h2>
            <p>
              The raw upload is deleted as soon as indexing finishes. Only
              embedded chunks remain, and only until expiry.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
