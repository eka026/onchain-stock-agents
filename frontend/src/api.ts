import type { Session, SessionListItem } from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function listSessions(): Promise<SessionListItem[]> {
  return request<SessionListItem[]>("/api/sessions");
}

export function getSession(id: string): Promise<Session> {
  return request<Session>(`/api/sessions/${encodeURIComponent(id)}`);
}

export function importDemoSession(): Promise<Session> {
  return request<Session>("/api/sessions/import-demo", { method: "POST" });
}

export function importLiveSession(): Promise<Session> {
  return request<Session>("/api/sessions/import-live", { method: "POST" });
}
