/**
 * The AI companion's API (misc/AI ARCHITECTURE §10).
 *
 * A question goes in a POST body - never a URL, which IIS would log. Nothing
 * here is kept in the browser's storage (invariant 10): the conversation
 * lives in `assistantStore`, in memory, and is dropped on lock like every
 * other answer the API gives.
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

export const forgetConversation = (conversationId: string) =>
  api<void>(`/assistant/conversations/${encodeURIComponent(conversationId)}`, { method: 'DELETE' });
