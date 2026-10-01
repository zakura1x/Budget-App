/**
 * The AI companion's API (misc/AI ARCHITECTURE §10).
 *
 * A question goes in a POST body - never a URL, which IIS would log. Nothing
 * here is kept in the browser's storage (invariant 10): the conversation
 * lives in `assistantStore`, in memory, and is dropped on lock like every
 * other answer the API gives. A conversation the user chose to KEEP (A6,
 * AI-60) is kept by the server, sealed under their key, and read back here.
 */
import { api } from './api';
import { localToday } from './transactions';

export type Tone = 'ok' | 'warn' | 'danger';

export interface AssistantStatus {
  enabled: boolean;
  opted_in: boolean;
  questions_left_today: number | null;
  reply_language: 'en' | 'match';
  suggestions: string[];
  /** AI-60 - how many days conversations are kept; 0 = gone on lock. */
  history_days: number;
}

export interface AssistantLink {
  label: string;
  route: string;
}

/** AI-40. Where an Explain link was tapped - it names a place; the server reads the figures itself. */
export interface AskContext {
  screen?: string;
  alert?: string;
  account_id?: number;
}

/** A draft's fields, for an ORDINARY sheet to open pre-filled. Nothing is saved until the user saves (AI-42..44). */
export interface DraftTransaction {
  type: 'expense' | 'income';
  amount: string;
  txn_date: string;
  category_id: number | null;
  account_id: number | null;
  merchant: string | null;
  notes: string | null;
}
export interface DraftGoal {
  name: string;
  target: string;
  target_date: string | null;
}
export interface DraftInstallment {
  name: string;
  price: string;
  payments: number;
}

export type AssistantAction =
  | { kind: 'open_screen'; label: string; route: string; payload: null }
  | { kind: 'draft_transaction'; label: string; route: string; payload: DraftTransaction }
  | { kind: 'draft_goal'; label: string; route: string; payload: DraftGoal }
  | { kind: 'try_installment'; label: string; route: string; payload: DraftInstallment };

export interface AssistantReply {
  conversation_id: string;
  question: string;
  text: string;
  /** False: the reply is the app's own sentence - the model was off, failed, or its figures did not check out (AI-08). */
  ai_phrased: boolean;
  skill: string;
  title: string;
  facts: string[];
  sources: AssistantLink[];
  actions: AssistantAction[];
  tone: Tone | null;
  /** The chip's words when the tone's own do not fit - an affordability verdict: Yes, Wait, No (AI-30). */
  label: string | null;
  verdict: 'yes' | 'yes_over_budget' | 'tight' | 'wait' | 'no' | null;
  follow_ups: string[];
}

export const getAssistantStatus = (signal?: AbortSignal) => api<AssistantStatus>('/assistant/status', { signal });

export const askAssistant = (question: string, conversationId: string | null, context?: AskContext) =>
  api<AssistantReply>('/assistant/ask', {
    method: 'POST',
    body: { question, today: localToday(), conversation_id: conversationId, context: context ?? null },
  });

/** A6 - one kept conversation in the list. */
export interface SavedConversation {
  conversation_id: string;
  title: string;
  started_at: string;
  updated_at: string;
  turns: number;
}

export const listConversations = (signal?: AbortSignal) =>
  api<{ history_days: number; conversations: SavedConversation[] }>('/assistant/conversations', { signal });

export const getConversation = (conversationId: string) =>
  api<{ conversation_id: string; turns: AssistantReply[] }>(
    `/assistant/conversations/${encodeURIComponent(conversationId)}`);

/** Forgets it in memory and, when it was kept, deletes the saved copy for good. */
export const forgetConversation = (conversationId: string) =>
  api<void>(`/assistant/conversations/${encodeURIComponent(conversationId)}`, { method: 'DELETE' });

/** One day's counts, every account summed - the Admin screen's line (A5). Never whose, never what. */
export interface AssistantUsageDay {
  day: string;
  users: number;
  questions: number;
  model_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  /** Replies the app wrote itself because the model failed or its reply was not believed (AI-08). */
  fallbacks: number;
}

export interface AssistantUsage {
  enabled: boolean;
  model: string;
  /** How many accounts the pilot list names; null = every account that turned it on. */
  pilot_users: number | null;
  days: AssistantUsageDay[];
}

export interface AssistantHealth {
  status: 'disabled' | 'ok' | 'failing';
  checks: Record<string, { ok: boolean; detail: string; ms: number | null }>;
}

/** Admin only. Reads the counts and nothing else. */
export const getAssistantUsage = (signal?: AbortSignal) => api<AssistantUsage>('/assistant/usage', { signal });

/** Admin only. Loads the key and asks the model for one word, so it is asked for, never run on open. */
export const checkAssistantHealth = () => api<AssistantHealth>('/assistant/health');
