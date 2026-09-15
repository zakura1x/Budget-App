/**
 * /security, /goals and /admin - types and calls (SEC-21..24, GOA-01..07, UX-20).
 *
 * Every security call carries the password again in its body.
 */
import { api } from './api';
import type { Outcome } from './transactions';
import { localToday } from './transactions';

export interface RotatedKey {
  sessions_ended: number;
  backups_replaced: boolean;
}

export const changePassword = (current_password: string, new_password: string) =>
  api<{ sessions_ended: number }>('/security/password', { method: 'POST', body: { current_password, new_password } });

export const rotateKey = (password: string) => api<RotatedKey>('/security/rotate-key', { method: 'POST', body: { password } });

export const deleteAccount = (password: string, confirm_email: string) =>
  api<null>('/security/delete-account', { method: 'POST', body: { password, confirm_email } });

export interface Goal {
  id: number;
  name: string;
  target: string;
  target_date: string | null;
  account_id: number;
  colour: string;
  icon: string;
  saved: string;
  remaining: string;
  ratio: string;
  reached: boolean;
}

export interface GoalDraft {
  name: string;
  target: string;
  target_date?: string | null;
  account_id: number;
}

const today = () => `today=${localToday()}`;

export const listGoals = (signal?: AbortSignal) => api<Goal[]>(`/goals?${today()}`, { signal });
export const createGoal = (body: GoalDraft) => api<Goal>(`/goals?${today()}`, { method: 'POST', body });
export const updateGoal = (id: number, body: Partial<GoalDraft>) =>
  api<Goal>(`/goals/${id}?${today()}`, { method: 'PATCH', body });
export const deleteGoal = (id: number) => api<null>(`/goals/${id}`, { method: 'DELETE' });
export const contributeToGoal = (id: number, body: { amount: string; from_account_id: number; txn_date?: string }) =>
  api<Outcome>(`/goals/${id}/contribute?${today()}`, { method: 'POST', body });

export interface AdminUser {
  id: number;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  key_version: number;
}

export interface AdminStatus {
  users: number;
  active_users: number;
  max_users: number;
  master_key_version: number;
  master_key_versions_loaded: number;
  unlocked_sessions: number;
  cached_users: number;
  rows: Record<string, number>;
}

export const adminUsers = (signal?: AbortSignal) => api<AdminUser[]>('/admin/users', { signal });
export const adminStatus = (signal?: AbortSignal) => api<AdminStatus>('/admin/status', { signal });
export const setUserActive = (id: number, active: boolean) =>
  api<AdminUser>(`/admin/users/${id}/active`, { method: 'POST', body: { active } });
export const deleteUser = (id: number, confirm_user_id: number, password: string) =>
  api<null>(`/admin/users/${id}/delete`, { method: 'POST', body: { confirm_user_id, password } });
