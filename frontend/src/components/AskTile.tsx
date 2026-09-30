/**
 * Home's "Ask" tile (misc/AI, AI-45): two questions picked from what Home
 * already knows - an alert showing, a budget running hot - and a way into the
 * Assistant. Shown only once the user has opted in.
 *
 * The suggestions are chosen here from the budget status Home has loaded; no
 * extra request, and nothing is asked until a chip is tapped.
 */
import { ChatIcon } from './Icons';
import { Card } from './ui/Card';
import { useAskAssistant, useAssistantOn } from '../hooks/useAssistant';
import type { AskContext } from '../lib/assistant';
import type { Alert, BudgetStatus } from '../lib/budgets';

interface Suggestion {
  question: string;
  context?: AskContext;
}

const CARD_ALERTS = ['card_due', 'card_limit_over', 'card_limit_approaching', 'card_limit_pace'];

function suggestions(status: BudgetStatus | null, alerts: Alert[]): Suggestion[] {
  const picked: Suggestion[] = [];
  const card = alerts.find((a) => CARD_ALERTS.includes(a.kind));
  if (card) {
    picked.push({ question: 'What do I owe on my card?', context: { alert: card.kind, account_id: card.account_id ?? undefined } });
  }
  if (status) {
    const hot = alerts.some((a) => ['over', 'approaching', 'pace', 'category_over'].includes(a.kind));
    picked.push(hot
      ? { question: 'Am I on track with my budget?', context: { screen: 'budget' } }
      : { question: 'How much is left in my budget?', context: { screen: 'budget' } });
  }
  picked.push({ question: 'What bills are due before payday?' });
  picked.push({ question: 'Where did my money go this month?' });
  return picked.slice(0, 2);
}

export function AskTile({ status, alerts }: { status: BudgetStatus | null; alerts: Alert[] }) {
  const on = useAssistantOn();
  const ask = useAskAssistant();
  if (!on) return null;
  return (
    <Card className="mt-3 space-y-3">
      <button type="button" onClick={() => ask('')}
        className="flex w-full items-center gap-2 text-left text-headline">
        <ChatIcon size={20} />
        <span className="flex-1">Ask about your money</span>
        <span className="text-ink-3" aria-hidden="true">›</span>
      </button>
      <div className="flex flex-wrap gap-2">
        {suggestions(status, alerts).map((s) => (
          <button key={s.question} type="button" onClick={() => ask(s.question, s.context)}
            className="press rounded-full bg-surface px-3 py-2 text-left text-footnote font-semibold text-ink">
            {s.question}
          </button>
        ))}
      </div>
    </Card>
  );
}
