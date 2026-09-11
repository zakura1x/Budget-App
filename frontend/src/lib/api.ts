/**
 * The single fetch wrapper. Every call to the API goes through here.
 *
 *  - credentials: 'include'  the session is an HttpOnly cookie scoped to
 *                            /ZBDGT (SEC-28). JavaScript never sees a token.
 *  - errors are RFC 7807     problem+json bodies become an ApiError with the
 *                            server's `code`, so screens branch on codes,
 *                            never on message text.
 *  - SESSION_LOCKED          (auto-lock, or the server restarted - SEC-27) is
 *                            announced as an event; Phase 2's lock screen
 *                            listens for it. 401 -> refresh -> retry joins in
 *                            Phase 2 as well.
 *
 * Nothing returned from here is ever written to localStorage, IndexedDB or
 * the Cache API (SEC-29). Every app on this host can read those.
 */

import { API_PREFIX } from './config';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail?: string;
  readonly ref?: string;
  readonly body?: unknown;

  constructor(status: number, code: string, message: string, detail?: string, ref?: string, body?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.ref = ref;
    this.body = body;
  }
}

export const LOCKED_EVENT = 'zbdgt:session-locked';

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

interface RequestOptions {
  method?: Method;
  body?: unknown;
  signal?: AbortSignal;
  /** Resolve with the parsed body even on non-2xx (used by /health). */
  acceptErrorBody?: boolean;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, signal, acceptErrorBody = false } = options;

  let response: Response;
  try {
    response = await fetch(`${API_PREFIX}${path}`, {
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
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error;
    throw new ApiError(0, 'OFFLINE', 'You appear to be offline.');
  }

  const isJson = (response.headers.get('content-type') ?? '').includes('json');
  const payload: unknown = isJson ? await response.json().catch(() => null) : null;

  if (response.ok || acceptErrorBody) return payload as T;

  const problem = (payload ?? {}) as { title?: string; code?: string; detail?: string; ref?: string };
  const code = problem.code ?? `HTTP_${response.status}`;
  if (code === 'SESSION_LOCKED') window.dispatchEvent(new Event(LOCKED_EVENT));
  throw new ApiError(
    response.status,
    code,
    problem.detail ?? problem.title ?? 'Something went wrong.',
    problem.detail,
    problem.ref,
    payload,
  );
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
