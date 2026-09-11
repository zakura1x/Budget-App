/**
 * The single fetch wrapper. Every call to the API goes through here.
 *
 *  - credentials: 'include'  the session is an HttpOnly cookie scoped to
 *                            /ZBDGT (SEC-28). JavaScript never sees a token.
 *  - X-Requested-With        sent on every request; the server refuses a
 *                            state-changing request without it (CSRF guard).
 *  - errors are RFC 7807     problem+json becomes an ApiError carrying the
 *                            server's `code`; screens branch on codes.
 *  - silent refresh          a 401 TOKEN_EXPIRED / AUTH_REQUIRED triggers ONE
 *                            refresh (shared by every call waiting on it -
 *                            two refreshes with the same token would look
 *                            like a replay and end the session), then a
 *                            single retry.
 *  - SESSION_LOCKED          -> the 'locked' event; the app shows the PIN pad.
 *  - SESSION_REVOKED / a failed refresh -> the 'signed-out' event.
 *
 * Nothing returned from here is ever written to localStorage, IndexedDB or
 * the Cache API (SEC-29). Every app on this host can read those.
 */

import { API_PREFIX } from './config';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail?: string;
  readonly body: Record<string, unknown>;

  constructor(status: number, code: string, message: string, body: Record<string, unknown> = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = typeof body.detail === 'string' ? body.detail : undefined;
    this.body = body;
  }
}

export const LOCKED_EVENT = 'zbdgt:session-locked';
export const SIGNED_OUT_EVENT = 'zbdgt:signed-out';

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

interface RequestOptions {
  method?: Method;
  body?: unknown;
  signal?: AbortSignal;
  /** Resolve with the parsed body even on non-2xx (used by /health). */
  acceptErrorBody?: boolean;
}

// Calls that must never trigger a refresh-and-retry of their own.
const NO_REFRESH = ['/auth/login', '/auth/register', '/auth/recover', '/auth/refresh', '/auth/logout', '/auth/config'];

let refreshing: Promise<boolean> | null = null;

/** One refresh at a time, shared by every caller that needs it. */
export function refreshSession(): Promise<boolean> {
  if (!refreshing) {
    refreshing = rawFetch('/auth/refresh', { method: 'POST' })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

function rawFetch(path: string, { method = 'GET', body, signal }: RequestOptions): Promise<Response> {
  return fetch(`${API_PREFIX}${path}`, {
    method,
    signal,
    credentials: 'include',
    cache: 'no-store',
    headers: {
      Accept: 'application/json, application/problem+json',
      'X-Requested-With': 'fetch',
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

async function parse(response: Response): Promise<Record<string, unknown> | null> {
  if (response.status === 204) return null;
  const isJson = (response.headers.get('content-type') ?? '').includes('json');
  return isJson ? ((await response.json().catch(() => null)) as Record<string, unknown> | null) : null;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const attempt = async (): Promise<Response> => {
    try {
      return await rawFetch(path, options);
    } catch (error) {
      if ((error as Error).name === 'AbortError') throw error;
      throw new ApiError(0, 'OFFLINE', 'You appear to be offline.');
    }
  };

  let response = await attempt();
  let payload = await parse(response);

  const code = (payload?.code as string | undefined) ?? '';
  if (
    response.status === 401 &&
    (code === 'TOKEN_EXPIRED' || code === 'AUTH_REQUIRED') &&
    !NO_REFRESH.some((p) => path.startsWith(p))
  ) {
    if (await refreshSession()) {
      response = await attempt();
      payload = await parse(response);
    }
  }

  if (response.ok || options.acceptErrorBody) return payload as T;

  const problem = payload ?? {};
  const finalCode = (problem.code as string | undefined) ?? `HTTP_${response.status}`;
  if (finalCode === 'SESSION_LOCKED') window.dispatchEvent(new Event(LOCKED_EVENT));
  if (
    response.status === 401 &&
    !NO_REFRESH.some((p) => path.startsWith(p)) &&
    finalCode !== 'SESSION_LOCKED' &&
    finalCode !== 'INVALID_CREDENTIALS'
  ) {
    window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
  }
  const message =
    (typeof problem.detail === 'string' && problem.detail) ||
    (typeof problem.title === 'string' && problem.title) ||
    'Something went wrong.';
  throw new ApiError(response.status, finalCode, message, problem);
}

export interface HealthStatus {
  status: 'ok' | 'degraded';
  app: string;
  version: string;
  checks: {
    database: { reachable: boolean; schema_present: boolean };
    encryption: { master_key_loaded: boolean };
  };
}

export const getHealth = (signal?: AbortSignal) =>
  api<HealthStatus>('/health', { signal, acceptErrorBody: true });
