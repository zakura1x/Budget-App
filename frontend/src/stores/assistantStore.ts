/**
 * The AI companion's conversation, in memory only (misc/AI ARCHITECTURE §7, §11).
 *
 * Not a query: it is a thread the user builds one question at a time, and the
 * server keeps its own copy only until the key goes - unless the user keeps
 * conversations (A6), when the server also seals it. Never persisted here
 * (invariant 10); App.tsx calls `reset()` in the lock effect beside
 * `queryClient.clear()`, so a lock wipes the page's copy in the same moment as
 * the server's memory.
 */
import { create } from 'zustand';
import { ApiError } from '../lib/api';
import {
  askAssistant, forgetConversation, getConversation, type AskContext, type AssistantReply,
} from '../lib/assistant';
import { buzz } from '../lib/haptics';
import { invalidateGroups } from '../lib/queryKeys';

interface AssistantState {
  conversationId: string | null;
  turns: AssistantReply[];
  /** The question waiting for its answer - drawn as the last bubble with a typing indicator. */
  pending: string | null;
  error: string | null;
  ask: (question: string, context?: AskContext) => Promise<void>;
  /**
   * Start over. A conversation that is not kept is dropped on the server too;
   * a kept one (`kept`, A6) stays in the saved list.
   */
  clear: (kept?: boolean) => void;
  /** A6 - carry on a kept conversation: its turns come back from the server. */
  open: (conversationId: string) => Promise<void>;
  /** A6 - delete a kept conversation for good; if it is the open one, start over. */
  remove: (conversationId: string) => Promise<void>;
  reset: () => void;
}

const MESSAGES: Record<string, string> = {
  ASSISTANT_BUSY: 'Still answering your last question - one at a time.',
  ASSISTANT_DAILY_LIMIT: "That's today's questions. The assistant is back tomorrow.",
  ASSISTANT_QUESTION_TOO_LONG: 'Keep a question under 500 characters.',
  ASSISTANT_DISABLED: 'The assistant is switched off on this server.',
  ASSISTANT_NOT_OPTED_IN: 'Turn the assistant on first.',
};

export const useAssistantStore = create<AssistantState>((set, get) => ({
  conversationId: null,
  turns: [],
  pending: null,
  error: null,

  ask: async (question, context) => {
    const text = question.trim();
    if (!text || get().pending) return;
    set({ pending: text, error: null });
    try {
      const reply = await askAssistant(text, get().conversationId, context);
      set((s) => ({ turns: [...s.turns, reply], conversationId: reply.conversation_id, pending: null }));
      buzz('success');
    } catch (e) {
      const code = e instanceof ApiError ? e.code : '';
      set({ pending: null, error: MESSAGES[code] ?? "Couldn't reach the assistant. Try again." });
    } finally {
      // The questions-left count moved; nothing that shows money did. A store,
      // like ledgerStore, invalidates its own keys - components use afterWrite.
      invalidateGroups(['assistant']);
    }
  },

  clear: (kept = false) => {
    const id = get().conversationId;
    set({ conversationId: null, turns: [], pending: null, error: null });
    if (id && !kept) void forgetConversation(id).catch(() => undefined);
  },

  open: async (conversationId) => {
    if (get().pending) return;
    set({ error: null });
    try {
      const found = await getConversation(conversationId);
      set({ conversationId: found.conversation_id, turns: found.turns });
    } catch {
      set({ error: "That conversation isn't there any more." });
      invalidateGroups(['assistant']);
    }
  },

  remove: async (conversationId) => {
    try {
      await forgetConversation(conversationId);
      if (get().conversationId === conversationId) set({ conversationId: null, turns: [], error: null });
    } catch {
      set({ error: "Couldn't delete that conversation. Try again." });
    } finally {
      invalidateGroups(['assistant']);
    }
  },

  reset: () => set({ conversationId: null, turns: [], pending: null, error: null }),
}));
