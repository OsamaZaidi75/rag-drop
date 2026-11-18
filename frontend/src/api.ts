export interface Session {
  id: string;
  filename: string;
  status: "indexing" | "ready" | "failed" | "expired";
  chunks: number;
  rows_read: number;
  error: string | null;
  created_at: string;
  expires_at: string;
  seconds_remaining: number;
}

export interface Source {
  source: string;
  text: string;
  score: number;
}

export interface AskResponse {
  answer: string;
  sources: Source[];
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") message = body.detail;
    } catch {
      // keep statusText
    }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

export async function uploadFile(file: File): Promise<Session> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/sessions", { method: "POST", body: form });
  return handle<Session>(res);
}

export async function loadSample(): Promise<Session> {
  const res = await fetch("/sessions/sample", { method: "POST" });
  return handle<Session>(res);
}

export async function getSession(id: string): Promise<Session> {
  const res = await fetch(`/sessions/${id}`);
  return handle<Session>(res);
}

export async function deleteSession(id: string): Promise<void> {
  const res = await fetch(`/sessions/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    throw new ApiError(res.status, "Delete failed");
  }
}

export async function ask(id: string, question: string): Promise<AskResponse> {
  const res = await fetch(`/sessions/${id}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  return handle<AskResponse>(res);
}
