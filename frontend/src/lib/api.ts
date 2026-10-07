import type {
  AskHandlers,
  AskMode,
  ChatTurn,
  DocumentDetail,
  DocumentList,
  DocumentSummary,
  Folder,
  LoginResponse,
  SearchFilters,
  UploadResponse,
  User,
} from "./types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

const TOKEN_KEY = "govsearch-token";
const USER_KEY = "govsearch-user";

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function getToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getStoredUser(): User | null {
  try {
    const raw = window.localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

export function storeSession(session: LoginResponse) {
  try {
    window.localStorage.setItem(TOKEN_KEY, session.token);
    window.localStorage.setItem(USER_KEY, JSON.stringify(session.user));
  } catch {}
}

export function clearSession() {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(USER_KEY);
  } catch {}
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = "http_error";
  let message = `Request failed (${response.status})`;
  try {
    const body = await response.json();
    if (body?.error) {
      code = body.error.code || code;
      message = body.error.message || message;
    }
  } catch {}
  return new ApiError(response.status, code, message);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...authHeaders(), ...(init.headers as Record<string, string>) };
  if (init.body && !(init.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  devLogin: (username: string) =>
    request<LoginResponse>("/auth/dev-login", { method: "POST", body: JSON.stringify({ username }) }),
  me: () => request<User>("/me"),
  folders: () => request<Folder[]>("/folders"),
  createFolder: (name: string, parent_id: string | null) =>
    request<Folder>("/folders", { method: "POST", body: JSON.stringify({ name, parent_id }) }),
  updateFolder: (id: string, patch: { name?: string; parent_id?: string | null }) =>
    request<Folder>(`/folders/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteFolder: (id: string) => request<void>(`/folders/${encodeURIComponent(id)}`, { method: "DELETE" }),
  documents: (pageSize = 200) => request<DocumentList>(`/documents?page_size=${pageSize}&sort=-created_at`),
  document: (id: string) => request<DocumentDetail>(`/documents/${id}`),
  updateDocument: (id: string, patch: { title?: string; folder_id?: string; doctype?: string }) =>
    request<DocumentDetail>(`/documents/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteDocument: (id: string) => request<void>(`/documents/${id}`, { method: "DELETE" }),
  downloadFile: async (id: string): Promise<Blob> => {
    const response = await fetch(`${API_BASE}/documents/${id}/file`, { headers: authHeaders() });
    if (!response.ok) throw await toApiError(response);
    return response.blob();
  },
};

export function uploadFile(
  path: string,
  fields: Record<string, string | Blob>,
  onProgress: (fraction: number) => void,
): Promise<UploadResponse> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    Object.entries(fields).forEach(([key, value]) => form.append(key, value));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}${path}`);
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {}
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(1);
        resolve(body as UploadResponse);
      } else {
        const error = (body as { error?: { code?: string; message?: string } } | null)?.error;
        reject(new ApiError(xhr.status, error?.code || "upload_failed", error?.message || `Upload failed (${xhr.status})`));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "network", "Network error during upload"));
    xhr.send(form);
  });
}

export function uploadDocument(file: File, departmentId: string, folderId: string, onProgress: (f: number) => void) {
  return uploadFile("/documents", { file, department_id: departmentId, folder_id: folderId }, onProgress);
}

export function uploadVersion(documentId: string, file: File, onProgress: (f: number) => void) {
  return uploadFile(`/documents/${documentId}/versions`, { file }, onProgress) as unknown as Promise<{
    version_id: string;
    version_no: number;
    status: string;
  }>;
}

export async function askStream(
  question: string,
  options: { mode: AskMode; filters?: SearchFilters; history?: ChatTurn[]; signal?: AbortSignal },
  handlers: AskHandlers,
): Promise<void> {
  const response = await fetch(`${API_BASE}/ask`, {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ question, mode: options.mode, filters: options.filters, history: options.history ?? [] }),
    signal: options.signal,
  });
  if (!response.ok || !response.body) throw await toApiError(response);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const dispatch = (block: string) => {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    }
    if (!data.length) return;
    let payload: Record<string, unknown> = {};
    try {
      payload = JSON.parse(data.join("\n"));
    } catch {
      return;
    }
    if (event === "token") handlers.onToken(String(payload.text ?? ""));
    else if (event === "step") handlers.onStep({ tool: String(payload.tool ?? ""), input: (payload.input as Record<string, unknown>) ?? {} });
    else if (event === "citations") handlers.onCitations((payload.citations as never) ?? []);
    else if (event === "error") handlers.onError(String(payload.message ?? "Something went wrong"));
  };
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index: number;
    while ((index = buffer.search(/\r?\n\r?\n/)) !== -1) {
      const block = buffer.slice(0, index);
      buffer = buffer.slice(index).replace(/^\r?\n\r?\n/, "");
      dispatch(block);
    }
  }
  if (buffer.trim()) dispatch(buffer);
}

export type { DocumentSummary };
