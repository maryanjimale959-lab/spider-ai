import type {
  AiStatus, DocumentSummary, Investigation, InvestigationResults, QuestionAnswer, TokenResponse, User,
  VersionContent,
} from "./types";

const TOKEN_KEY = "spider.token";

let token: string | null = null;
const listeners = new Set<() => void>();

export function setToken(value: string | null) {
  token = value;
  try {
    if (value) localStorage.setItem(TOKEN_KEY, value);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage disabled - the session simply will not persist */
  }
  listeners.forEach((fn) => fn());
}

export function restoreToken() {
  try {
    token = localStorage.getItem(TOKEN_KEY);
  } catch {
    token = null;
  }
  return token;
}

export function currentToken() {
  return token;
}

export function onSessionChange(fn: () => void) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(path, { ...init, headers });
  } catch {
    throw new ApiError(0, "The SPIDER AI server is not reachable. Start the backend and try again.");
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { detail: text.slice(0, 300) };
    }
  }
  if (!response.ok) {
    const detail =
      (payload as { detail?: string | { msg?: string }[] })?.detail ?? `Request failed (${response.status})`;
    const message = Array.isArray(detail) ? detail.map((d) => d.msg ?? String(d)).join(", ") : String(detail);
    if (response.status === 401 && token) setToken(null);
    throw new ApiError(response.status, message);
  }
  return payload as T;
}

const json = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const api = {
  /* session */
  login: (email: string, password: string) =>
    request<TokenResponse>("/api/auth/login", json({ email, password })),
  register: (payload: { email: string; full_name: string; password: string; role?: string; institution?: string }) =>
    request<TokenResponse>("/api/auth/register", json(payload)),
  me: () => request<User>("/api/auth/me"),
  health: () =>
    request<{ app: string; status: string; engine: string; ai: AiStatus; formats: string[] }>("/api/health"),

  /* documents */
  listDocuments: (scope?: "assigned") =>
    request<DocumentSummary[]>(`/api/documents${scope ? `?scope=${scope}` : ""}`),
  upload: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<DocumentSummary>("/api/documents", { method: "POST", body });
  },
  deleteDocument: (id: string) => request<void>(`/api/documents/${id}`, { method: "DELETE" }),
  content: (versionId: string) => request<VersionContent>(`/api/versions/${versionId}/content`),

  /* investigation */
  start: (versionId: string, goals: string[]) =>
    request<Investigation>(`/api/versions/${versionId}/investigations`, json({ goals })),
  status: (id: string) => request<Investigation>(`/api/investigations/${id}`),
  results: (id: string) => request<InvestigationResults>(`/api/investigations/${id}/results`),
  latest: (versionId: string) =>
    request<Investigation | null>(`/api/versions/${versionId}/investigations/latest`),
  cancel: (id: string) => request<Investigation>(`/api/investigations/${id}/cancel`, { method: "POST" }),
  decide: (id: string, status: "accepted" | "dismissed" | "edited", user_text?: string) =>
    request<{ id: string; status: string }>(`/api/recommendations/${id}/decision`, json({ status, user_text })),
  ask: (investigationId: string, question: string) =>
    request<QuestionAnswer>(`/api/investigations/${investigationId}/questions`, json({ question })),
  keywordOccurrences: (keywordId: string) =>
    request<{ term: string; occurrences: number; hits: { passage_id: string; page_number?: number | null; start: number; end: number; excerpt: string }[] }>(
      `/api/keywords/${keywordId}/occurrences`,
    ),

};
