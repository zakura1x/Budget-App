/**
 * "Explain" - opens the Assistant with a question about the thing beside it
 * (misc/AI, AI-40). It sends WHERE it was tapped (a screen, an alert, an
 * account id), never a figure: the server reads the object itself.
 *
 * Draws nothing unless the assistant is on for this user and they have opted
 * in, so it can sit on any screen without a check of its own.
 */
import { ChatIcon } from './Icons';
import { useAskAssistant, useAssistantOn } from '../hooks/useAssistant';
import type { AskContext } from '../lib/assistant';

export function ExplainLink({ ask, context, label = 'Explain', className = '' }: {
  ask: string; context: AskContext; label?: string; className?: string;
}) {
  const on = useAssistantOn();
  const open = useAskAssistant();
  if (!on) return null;
  return (
    <button type="button" onClick={() => open(ask, context)}
      className={`inline-flex min-h-tap items-center gap-1.5 px-1 text-footnote font-semibold text-accent-ink ${className}`}>
      <ChatIcon size={16} />
      {label}
    </button>
  );
}
