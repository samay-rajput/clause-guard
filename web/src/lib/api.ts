/** API client: bearer token in memory, transparent refresh on 401 (httpOnly
 * cookie carries the refresh token), SSE consumption for job progress. */
import { fetchEventSource } from "@microsoft/fetch-event-source";

let accessToken: string | null = null;
let onSession: ((user: User | null) => void) | null = null;

export interface User {
  username: string;
  role: "drafter" | "reviewer";
}

export function setSessionListener(fn: (user: User | null) => void) {
  onSession = fn;
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

async function refresh(): Promise<boolean> {
  const r = await fetch("/api/auth/refresh", { method: "POST" });
  if (!r.ok) {
    accessToken = null;
    onSession?.(null);
    return false;
  }
  const data = await r.json();
  accessToken = data.access_token;
  onSession?.(data.user);
  return true;
}

async function raw(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const r = await fetch(path, { ...init, headers });
  if (r.status === 401 && retry && !path.startsWith("/api/auth/")) {
    if (await refresh()) return raw(path, init, false);
  }
  return r;
}

async function toBlobUrl(r: Response): Promise<{ url: string; filename: string }> {
  if (!r.ok) {
    const body = r.headers.get("content-type")?.includes("json")
      ? await r.json()
      : await r.text();
    throw new ApiError(r.status, (body as any)?.detail ?? body);
  }
  const dispo = r.headers.get("content-disposition") ?? "";
  const filename = /filename="?([^";]+)"?/.exec(dispo)?.[1] ?? "download";
  return { url: URL.createObjectURL(await r.blob()), filename };
}

async function toJson(r: Response) {
  const body = r.headers.get("content-type")?.includes("json")
    ? await r.json()
    : await r.text();
  if (!r.ok) throw new ApiError(r.status, (body as any)?.detail ?? body);
  return body;
}

export const api = {
  get: (path: string) => raw(path).then(toJson),
  post: (path: string, body?: unknown) =>
    raw(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then(toJson),

  async login(username: string, password: string) {
    const form = new URLSearchParams({ username, password });
    const r = await fetch("/api/auth/login", { method: "POST", body: form });
    const data = await toJson(r);
    accessToken = data.access_token;
    onSession?.(data.user);
    return data.user as User;
  },

  async tryResume(): Promise<boolean> {
    return refresh();
  },

  async logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    accessToken = null;
    onSession?.(null);
  },

  async upload(path: string, file: File) {
    const fd = new FormData();
    fd.append("file", file);
    return raw(path, { method: "POST", body: fd }).then(toJson);
  },

  /** POST-created blob (exports) → object URL + suggested filename. */
  async blob(path: string, body: unknown): Promise<{ url: string; filename: string }> {
    const r = await raw(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return toBlobUrl(r);
  },

  /** GET-served blob (audit trail downloads) → object URL + filename. */
  async blobGet(path: string): Promise<{ url: string; filename: string }> {
    return toBlobUrl(await raw(path));
  },

  /** Stream a job's SSE events; resolves with the result payload. */
  job<T = any>(jobId: string, onProgress: (msg: string, step: number) => void): Promise<T> {
    return new Promise((resolve, reject) => {
      const ctrl = new AbortController();
      fetchEventSource(`/api/jobs/${jobId}/events`, {
        signal: ctrl.signal,
        headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
        openWhenHidden: true,
        onmessage(ev) {
          if (ev.event === "progress") {
            const d = JSON.parse(ev.data);
            onProgress(d.message, d.step);
          } else if (ev.event === "result") {
            ctrl.abort();
            resolve(JSON.parse(ev.data));
          } else if (ev.event === "error") {
            ctrl.abort();
            reject(new ApiError(500, JSON.parse(ev.data).error));
          }
        },
        onerror(err) {
          ctrl.abort();
          reject(err);
        },
      });
    });
  },
};
