/**
 * /security, /goals and /admin - types and calls (SEC-21..24, GOA-01..07, UX-20).
 *
 * Every security call carries the password again in its body.
 */
import { api } from './api';
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
  /** GOA-08. The account it is set aside in: its balance, what is still available there, any shortfall. */
  account_balance: string;
  account_available: string;
  short_by: string;
  /** GOA-05. To set aside each month to reach it on time; null with no date, a past one, or nothing left. */
  per_month?: string | null;
  /** This month and the target's own included. */
  months_left?: number | null;
  overdue?: boolean;
  /** Phase 13. saving · sinking (GOA-09, repeats or follows a yearly bill) · emergency (GOA-10, at most one). */
  kind?: GoalKind;
  repeats_yearly?: boolean;
  rule_id?: number | null;
  /** GOA-09. This month's part: what it asks for to stay on time, and what is set aside in it already. */
  month_need?: string | null;
  month_added?: string;
  month_done?: boolean;
}

export type GoalKind = 'saving' | 'sinking' | 'emergency';

export interface GoalDraft {
  name: string;
  target: string;
  target_date?: string | null;
  account_id: number;
  kind?: GoalKind;
  repeats_yearly?: boolean;
  /** A yearly bill to follow; 0 stops following one. */
  rule_id?: number | null;
}

/** GOA-09. A bill that comes once a year with no sinking fund following it yet. */
export interface YearlyBill {
  rule_id: number;
  name: string;
  amount: string;
  on: string;
}

/** GOA-10/11. How long the emergency money lasts, what it should be, and every reason. */
export interface EmergencyAdvice {
  essentials: { monthly: string; months: number; guessing: boolean };
  money: string;
  source: 'goal' | 'cash';
  goal_id: number | null;
  cover_months: string;
  measurable: boolean;
  target_months: number;
  target: string;
  fired: { code: string; text: string; months: number }[];
  short_history: boolean;
  per_month: string;
  answered: boolean;
  work: 'employee' | 'contract' | 'self';
  dependents: '0' | '1-2' | '3+';
  earners: '1' | '2+';
}

/** GOA-12. "Your ₱25,000 arrived - set some aside?" */
export interface Payday {
  transaction_id: number;
  amount: string;
  on: string;
  name: string;
  suggestions: { goal_id: number; name: string; kind: string; amount: string }[];
  total: string;
}

const today = () => `today=${localToday()}`;

export const listGoals = (signal?: AbortSignal) => api<Goal[]>(`/goals?${today()}`, { signal });
export const createGoal = (body: GoalDraft) => api<Goal>(`/goals?${today()}`, { method: 'POST', body });
export const updateGoal = (id: number, body: Partial<GoalDraft>) =>
  api<Goal>(`/goals/${id}?${today()}`, { method: 'PATCH', body });
export const deleteGoal = (id: number) => api<null>(`/goals/${id}`, { method: 'DELETE' });
export const getYearlyBills = (signal?: AbortSignal) => api<YearlyBill[]>(`/goals/yearly-bills?${today()}`, { signal });
export const getEmergency = (signal?: AbortSignal) => api<EmergencyAdvice>(`/goals/emergency?${today()}`, { signal });
export const getPayday = (signal?: AbortSignal) => api<Payday | null>(`/goals/payday?${today()}`, { signal });
/** GOA-12. Set each amount aside for its goal; the income is answered. One commit on the server. */
export const setAsidePayday = (transactionId: number, amounts: Record<number, string>) =>
  api<null>(`/goals/payday/${transactionId}?${today()}`, { method: 'POST', body: { amounts } });
/** GOA-12. "Not now" - this income is never asked about again. */
export const dismissPayday = (transactionId: number) =>
  api<null>(`/goals/payday/${transactionId}/dismiss`, { method: 'POST' });
/** GOA-08. Money set aside for a goal, or released from it. Nothing moves; the balance is unchanged. */
export interface GoalMoney {
  amount: string;
  on?: string;
  note?: string | null;
}

export const addToGoal = (id: number, body: GoalMoney) =>
  api<Goal>(`/goals/${id}/add?${today()}`, { method: 'POST', body });
export const releaseFromGoal = (id: number, body: GoalMoney) =>
  api<Goal>(`/goals/${id}/use?${today()}`, { method: 'POST', body });

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
  /** SEC-31 - short hashes of the loaded keys, to compare with the offline .env copy. */
  key_fingerprints: Record<string, string>;
}

export const adminUsers = (signal?: AbortSignal) => api<AdminUser[]>('/admin/users', { signal });
export const adminStatus = (signal?: AbortSignal) => api<AdminStatus>('/admin/status', { signal });
export const setUserActive = (id: number, active: boolean) =>
  api<AdminUser>(`/admin/users/${id}/active`, { method: 'POST', body: { active } });
export const deleteUser = (id: number, confirm_user_id: number, password: string) =>
  api<null>(`/admin/users/${id}/delete`, { method: 'POST', body: { confirm_user_id, password } });
