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
  /** SEC-30 - false when the server has no SMTP settings. */
  password_reset_enabled: boolean;
  reset_link_minutes: number;
  password_policy: PasswordPolicy;
}

export const authApi = {
  config: () => api<AuthConfig>('/auth/config'),
  me: () => api<Session>('/auth/me'),
  login: (email: string, password: string) => api<Session>('/auth/login', { method: 'POST', body: { email, password } }),
  register: (body: { email: string; password: string; registration_code: string; display_name?: string }) =>
    api<Session>('/auth/register', { method: 'POST', body }),
  logout: () => api<null>('/auth/logout', { method: 'POST' }),
  lock: () => api<null>('/auth/lock', { method: 'POST' }),
  verifyPin: (pin: string) => api<Session>('/auth/pin/verify', { method: 'POST', body: { pin } }),
  unlock: (password: string) => api<Session>('/auth/unlock', { method: 'POST', body: { password } }),
  setPin: (pin: string, current_password?: string) =>
    api<Session>('/auth/pin', { method: 'POST', body: { pin, current_password } }),
  forgotPassword: (email: string) =>
    api<{ link_minutes: number }>('/auth/forgot-password', { method: 'POST', body: { email } }),
  /** The token from the emailed link travels in the body - never in a URL the server could log. */
  resetPassword: (token: string, password: string) =>
    api<Session>('/auth/reset-password', { method: 'POST', body: { token, password } }),
};

/** Which parts of the policy a password meets - drives the strength meter. */
export function policyChecks(password: string, policy: PasswordPolicy) {
  const checks = [{ label: `${policy.min_length}+ characters`, ok: password.length >= policy.min_length }];
  if (policy.require_upper) checks.push({ label: 'An upper-case letter', ok: /[A-Z]/.test(password) });
  if (policy.require_digit) checks.push({ label: 'A digit', ok: /\d/.test(password) });
  if (policy.require_symbol) checks.push({ label: 'A symbol', ok: /[^A-Za-z0-9]/.test(password) });
  return checks;
}
