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
  actions: (AssistantLink & { kind: 'open_screen' })[];
  tone: Tone | null;
  follow_ups: string[];
}

export const getAssistantStatus = (signal?: AbortSignal) => api<AssistantStatus>('/assistant/status', { signal });

export const askAssistant = (question: string, conversationId: string | null) =>
  api<AssistantReply>('/assistant/ask', {
    method: 'POST',
    body: { question, today: localToday(), conversation_id: conversationId },
  });

export const forgetConversation = (conversationId: string) =>
  api<void>(`/assistant/conversations/${encodeURIComponent(conversationId)}`, { method: 'DELETE' });

/** Replies with no figures of their own - they never get the "answered from your figures" note. */
export const PLAIN_SKILLS = new Set(['off_topic', 'clarify']);
