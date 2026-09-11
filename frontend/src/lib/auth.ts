/** The /auth endpoints, typed. The session itself lives in HttpOnly cookies. */
import { api } from './api';

export interface SessionUser {
  id: number;
  is_admin: boolean;
  /** Only present while unlocked - the email lives under the DEK. */
  email: string | null;
  display_name: string | null;
}

export interface Session {
  user: SessionUser;
  locked: boolean;
  pin_set: boolean;
  auto_lock_minutes: number;
}

export interface RegisterResult extends Session {
  recovery_phrase: string[];
}

export interface PasswordPolicy {
  min_length: number;
  require_upper: boolean;
  require_digit: boolean;
  require_symbol: boolean;
}

export interface AuthConfig {
  registration_open: boolean;
  pin_enabled: boolean;
  pin_length: number;
  recovery_words: number;
  password_policy: PasswordPolicy;
}

export const authApi = {
  config: () => api<AuthConfig>('/auth/config'),
  me: () => api<Session>('/auth/me'),
  login: (email: string, password: string) => api<Session>('/auth/login', { method: 'POST', body: { email, password } }),
  register: (body: { email: string; password: string; registration_code: string; display_name?: string }) =>
    api<RegisterResult>('/auth/register', { method: 'POST', body }),
  logout: () => api<null>('/auth/logout', { method: 'POST' }),
  lock: () => api<null>('/auth/lock', { method: 'POST' }),
  verifyPin: (pin: string) => api<Session>('/auth/pin/verify', { method: 'POST', body: { pin } }),
  unlock: (password: string) => api<Session>('/auth/unlock', { method: 'POST', body: { password } }),
  setPin: (pin: string, current_password?: string) =>
    api<Session>('/auth/pin', { method: 'POST', body: { pin, current_password } }),
  recover: (phrase: string, new_password: string) =>
    api<Session>('/auth/recover', { method: 'POST', body: { phrase, new_password } }),
};

/** Which parts of the policy a password meets - drives the strength meter. */
export function policyChecks(password: string, policy: PasswordPolicy) {
  const checks = [{ label: `${policy.min_length}+ characters`, ok: password.length >= policy.min_length }];
  if (policy.require_upper) checks.push({ label: 'An upper-case letter', ok: /[A-Z]/.test(password) });
  if (policy.require_digit) checks.push({ label: 'A digit', ok: /\d/.test(password) });
  if (policy.require_symbol) checks.push({ label: 'A symbol', ok: /[^A-Za-z0-9]/.test(password) });
  return checks;
}
