/**
 * REC-34. How a purchase on a card or a loan is spread: months, first payment,
 * any interest or fee - and what that plan will be, worked out by the server
 * (the one schedule, REC-22). Used by the add sheet and by an expense already
 * recorded; the parent saves.
 */
import { format, parseISO } from 'date-fns';
import { useEffect, useState } from 'react';
import { ApiError } from '../lib/api';
import { formatPHP, toDecimalString } from '../lib/money';
import { previewInstallments, type InstallmentPreview, type InstallmentTerms } from '../lib/recurring';
import { MoneyField } from './ui/MoneyField';

const MONTHS = [3, 6, 12, 24];

export interface InstallmentChoice {
  payments: number;
  start: string; // '' = the bill the purchase belongs to
  interest: string; // as typed
}

export const EMPTY_CHOICE: InstallmentChoice = { payments: 3, start: '', interest: '' };

/** What the server wants, from what was typed. */
export function termsOf(choice: InstallmentChoice): InstallmentTerms {
  return {
    payments: choice.payments,
    ...(choice.start ? { start: choice.start } : {}),
    ...(choice.interest.trim() ? { interest: toDecimalString(choice.interest) } : {}),
  };
}

export function InstallmentFields({ accountId, amount, txnDate, cardPostedOn, choice, onChange, onPreview }: {
  accountId: number;
  amount: string; // decimal string
  txnDate: string;
  cardPostedOn?: string | null;
  choice: InstallmentChoice;
  onChange: (next: InstallmentChoice) => void;
  onPreview?: (preview: InstallmentPreview | null) => void;
}) {
  const [preview, setPreview] = useState<InstallmentPreview | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [custom, setCustom] = useState(!MONTHS.includes(choice.payments));

  useEffect(() => {
    if (amount === '0.00' || choice.payments < 1) {
      setPreview(null);
      onPreview?.(null);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      previewInstallments({ account_id: accountId, amount, txn_date: txnDate, card_posted_on: cardPostedOn ?? null,
        ...termsOf(choice) }, controller.signal)
        .then((found) => {
          setPreview(found);
          setProblem(null);
          onPreview?.(found);
        })
        .catch((e: Error) => {
          if (e.name === 'AbortError') return;
          setPreview(null);
          setProblem(e instanceof ApiError ? e.message : 'Could not work out the plan.');
          onPreview?.(null);
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, amount, txnDate, cardPostedOn, choice.payments, choice.start, choice.interest]);

  const first = preview?.payments[0];
  const last = preview?.payments[preview.payments.length - 1];
  const even = preview && preview.payments.every((p) => p.amount === first?.amount);

  return (
    <div className="space-y-3 rounded-card border-2 border-stroke bg-surface-2 p-3" role="group" aria-label="Installments">
      <div>
        <p className="mb-1.5 text-footnote font-semibold text-ink-2">Monthly payments</p>
        <div className="flex flex-wrap gap-2">
          {MONTHS.map((n) => (
            <button key={n} type="button" aria-pressed={!custom && choice.payments === n}
              onClick={() => { setCustom(false); onChange({ ...choice, payments: n }); }}
              className={`min-h-tap rounded-xl px-3.5 text-footnote font-semibold transition ${!custom && choice.payments === n ? 'bg-accent text-on-accent' : 'bg-surface text-ink-2'}`}>
              {n}
            </button>
          ))}
          <button type="button" aria-pressed={custom} onClick={() => setCustom(true)}
            className={`min-h-tap rounded-xl px-3.5 text-footnote font-semibold transition ${custom ? 'bg-accent text-on-accent' : 'bg-surface text-ink-2'}`}>
            Other
          </button>
          {custom && (
            <input value={choice.payments || ''} inputMode="numeric" aria-label="Number of payments" placeholder="18"
              onChange={(e) => onChange({ ...choice, payments: Number(e.target.value.replace(/\D/g, '').slice(0, 3)) || 0 })}
              className="num min-h-tap w-20 rounded-xl bg-surface px-3 text-right text-body" />
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <label className="block text-footnote font-semibold text-ink-2">
          First payment
          <input type="date" value={choice.start || preview?.start || ''}
            onChange={(e) => onChange({ ...choice, start: e.target.value })}
            className="mt-1.5 block min-h-12 w-full rounded-xl border-2 border-stroke bg-surface px-3 text-body font-normal text-ink" />
        </label>
        <MoneyField label="Interest or fee" value={choice.interest} placeholder="0" onChange={(v) => onChange({ ...choice, interest: v })} />
      </div>

      {preview && first && last && (
        <p className="text-footnote text-ink-2">
          <span className="num font-semibold text-ink">
            {preview.payments.length} × {formatPHP(first.amount)}{even ? '' : ' (last one adjusted)'}
          </span>
          {' · '}
          {format(parseISO(first.on), 'd MMM yyyy')}
          {preview.payments.length > 1 && ` – ${format(parseISO(last.on), 'd MMM yyyy')}`}
        </p>
      )}
      {preview && preview.due_now > 0 && (
        <p className="text-footnote text-ink-2">
          {preview.due_now === 1 ? 'The first payment is' : `${preview.due_now} payments are`} already due and will be
          recorded now.
        </p>
      )}
      {preview?.on_closed_statement && (
        <p className="text-footnote text-warn">
          This purchase is on a statement that has closed. If you checked that statement, the check will show a difference.
        </p>
      )}
      <p className="text-caption text-ink-3">
        The purchase becomes the plan: you still owe the full amount from today, and your budget counts one payment a
        month.
      </p>
      {problem && <p className="text-footnote text-danger">{problem}</p>}
    </div>
  );
}
