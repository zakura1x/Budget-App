/**
 * The assistant's conversation store (misc/AI ARCHITECTURE §11).
 *
 * What fails silently here is a thread that outlives the lock, or a second
 * question sent while one is waiting. Both are guarded below, with the API
 * mocked - no DOM, like the rest of src/tests.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../lib/api';
import type { AssistantReply } from '../lib/assistant';

const ask = vi.fn<(question: string, conversationId: string | null, context?: unknown) => Promise<AssistantReply>>();
const forget = vi.fn<(id: string) => Promise<void>>();

vi.mock('../lib/assistant', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/assistant')>()),
  askAssistant: (question: string, id: string | null, context?: unknown) => ask(question, id, context),
  forgetConversation: (id: string) => forget(id),
}));

const { useAssistantStore } = await import('../stores/assistantStore');

const reply = (question: string, id = 'c1'): AssistantReply => ({
  conversation_id: id, question, text: 'You have ₱4,210.00 left.', ai_phrased: true, skill: 'budget_status',
  title: 'Budget', facts: ['Left to spend: ₱4,210.00.'], sources: [], actions: [], tone: 'ok', label: null, verdict: null, follow_ups: [],
});

beforeEach(() => {
  ask.mockReset();
  forget.mockReset();
  forget.mockResolvedValue(undefined);
  useAssistantStore.getState().reset();
});

describe('asking', () => {
  it('keeps the thread and carries its id into the next question', async () => {
    ask.mockResolvedValueOnce(reply('How much is left?'));
    await useAssistantStore.getState().ask('How much is left?');
    ask.mockResolvedValueOnce(reply('And cash?'));
    await useAssistantStore.getState().ask('And cash?');
    expect(ask.mock.calls.map((c) => c[1])).toEqual([null, 'c1']);
    expect(useAssistantStore.getState().turns).toHaveLength(2);
    expect(useAssistantStore.getState().pending).toBeNull();
  });

  it('sends one question at a time', async () => {
    let answer!: (r: AssistantReply) => void;
    ask.mockReturnValueOnce(new Promise((resolve) => { answer = resolve; }));
    const first = useAssistantStore.getState().ask('One');
    await useAssistantStore.getState().ask('Two');
    expect(ask).toHaveBeenCalledTimes(1);
    answer(reply('One'));
    await first;
  });

  it('turns a refusal into a plain sentence', async () => {
    ask.mockRejectedValueOnce(new ApiError(429, 'ASSISTANT_DAILY_LIMIT', 'limit'));
    await useAssistantStore.getState().ask('How much is left?');
    expect(useAssistantStore.getState().error).toMatch(/back tomorrow/);
    expect(useAssistantStore.getState().turns).toHaveLength(0);
  });
});

describe('an Explain link', () => {
  it('sends where it was tapped, never a figure', async () => {
    ask.mockResolvedValueOnce(reply('Explain my budget'));
    await useAssistantStore.getState().ask('Explain my budget', { screen: 'budget' });
    expect(ask.mock.calls[0]![2]).toEqual({ screen: 'budget' });
  });
});

describe('forgetting', () => {
  it('reset (the lock effect) drops the whole thread', async () => {
    ask.mockResolvedValueOnce(reply('How much is left?'));
    await useAssistantStore.getState().ask('How much is left?');
    useAssistantStore.getState().reset();
    const state = useAssistantStore.getState();
    expect([state.turns, state.conversationId, state.pending]).toEqual([[], null, null]);
  });

  it('a new chat also forgets it on the server', async () => {
    ask.mockResolvedValueOnce(reply('How much is left?'));
    await useAssistantStore.getState().ask('How much is left?');
    useAssistantStore.getState().clear();
    expect(forget).toHaveBeenCalledWith('c1');
    expect(useAssistantStore.getState().turns).toHaveLength(0);
  });
});
