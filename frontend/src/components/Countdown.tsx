import { useEffect, useState } from "react";

/** Expiry countdown: a thin amber "fuse" that drains as the 7-day
 * lifetime runs out, plus a mono readout. The fuse is RAGDrop's
 * signature detail — the session is visibly temporary. */

function formatRemaining(totalSeconds: number): string {
  if (totalSeconds <= 0) return "expired";
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h left`;
  if (hours > 0) return `${hours}h ${minutes}m left`;
  return `${minutes}m left`;
}

export default function Countdown({
  expiresAt,
  createdAt,
}: {
  expiresAt: string;
  createdAt: string;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const expires = new Date(expiresAt).getTime();
  const created = new Date(createdAt).getTime();
  const total = Math.max(expires - created, 1);
  const remainingMs = Math.max(expires - now, 0);
  const fraction = Math.min(remainingMs / total, 1);
  const seconds = Math.floor(remainingMs / 1000);
  const urgent = seconds < 86400;

  return (
    <div className="countdown" title={`Expires ${new Date(expiresAt).toLocaleString()}`}>
      <div className="countdown-row">
        <span className="countdown-label">Session expires in</span>
        <span className={`countdown-value mono ${urgent ? "urgent" : ""}`}>
          {formatRemaining(seconds)}
        </span>
      </div>
      <div className="fuse" role="progressbar" aria-valuenow={Math.round(fraction * 100)}>
        <div className="fuse-fill" style={{ width: `${fraction * 100}%` }} />
      </div>
    </div>
  );
}
