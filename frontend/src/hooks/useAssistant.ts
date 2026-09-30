/**
 * Is the AI companion on for this user? (misc/AI, AI-40/45)
 *
 * True only when the server has it switched on, the user is on the pilot list
 * if there is one, AND the user has opted in - so an Explain link or the Home
 * tile never appears for someone who has not read what is sent (AI-50). Reads
 * the one status query every assistant entry point shares.
 */
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { getAssistantStatus, type AskContext } from '../lib/assistant';
import { keys, STALE } from '../lib/queryKeys';

export function useAssistantOn(): boolean {
  const { data } = useQuery({
    queryKey: keys.assistantStatus(),
    queryFn: ({ signal }) => getAssistantStatus(signal),
    staleTime: STALE.assistant,
  });
  return Boolean(data?.enabled && data.opted_in);
}

/** Open the Assistant with a question already asked - and, for an Explain link, where it was tapped. */
export function useAskAssistant(): (question: string, context?: AskContext) => void {
  const navigate = useNavigate();
  return (question, context) => navigate('/assistant', { state: { ask: question, context } });
}
