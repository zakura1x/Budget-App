/**
 * One card bill, opened (ACC-35, 2026-09-19 - user: "if I click the October bill I want to see the
 * installments and expenses I will pay for that month").
 *
 * The lines come from the server, built by the same pass that adds up the bill, so they always sum
 * to it: the typed figure from the card's app, the purchases and plan payments added on top, what the
 * typed figure already holds (greyed - shown, never added), and the payments that settled it, oldest
 * bill first. A line with a transaction or plan behind it opens that.
 */
import { format, parseISO } from 'date-fns';
import { useState } from 'react';
import { useLookups } from '../hooks/useLookups';
import type { Bill, BillLine } from '../lib/accounts';
import { formatPHP } from '../lib/money';
import { ensureRules } from '../lib/prefetch';
import { getTransaction } from '../lib/transactions';
import { useUiStore } from '../stores/uiStore';
import { Sheet } from './ui/Sheet';

const short = (iso: string) => format(parseISO(iso), 'd MMM');

function LineRow({ line, label, muted, onOpen }: { line: BillLine; label: string; muted?: boolean; onOpen?: () => void }) {
  const body = (
    <>
      <span className="min-w-0 truncate">
        {line.on && <span className="text-ink-2">{short(line.on)} · </span>}
        {label}
      </span>
      <span className={`shrink-0 font-semibold ${muted ? 'text-ink-3' : ''}`}>{formatPHP(line.amount)}</span>
    </>
  );
  const row = `num flex min-h-11 w-full items-center justify-between gap-2 text-left text-footnote ${muted ? 'text-ink-3' : ''}`;
  return (
    <li>
      {onOpen ? <button type="button" onClick={onOpen} className={`${row} active:bg-surface`}>{body}</button> : <div className={row}>{body}</div>}
    </li>
  );
}

function Group({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1.5 text-footnote font-semibold text-ink-2">{title}</p>
      <ul className="divide-y divide-stroke/80 rounded-card border-2 border-stroke bg-surface-2 px-3">{children}</ul>
      {note && <p className="px-1 pt-1.5 text-caption text-ink-3">{note}</p>}
    </div>
  );
}

export function BillSheet({ bill, onClose }: { bill: Bill | null; onClose: () => void }) {
  const lookups = useLookups();
  const openAddSheet = useUiStore((s) => s.openAddSheet);
  const openRuleSheet = useUiStore((s) => s.openRuleSheet);
  const [error, setError] = useState<string | null>(null);

  const label = (line: BillLine): string => {
    if (line.kind === 'typed') return 'From the card’s app';
    if (line.kind === 'payment') return line.name ?? 'Payment';
    const category = line.category_id !== null ? lookups.categoryById.get(line.category_id)?.name : undefined;
    const fallback = line.rule_id !== null ? 'Plan payment' : 'Purchase';
    return line.name || category || fallback;
  };

  /** The tap handler for a line with a transaction or plan behind it; none for the typed figure. */
  const open = (line: BillLine) => {
    if (line.transaction_id !== null) {
      const id = line.transaction_id;
      return () =>
        void getTransaction(id)
          .then((tx) => { onClose(); openAddSheet(tx); })
          .catch(() => setError('That entry could not be opened.'));
    }
    if (line.rule_id !== null) {
      const id = line.rule_id;
      return () =>
        // The whole rule list, to open one plan - from the shared cache.
        void ensureRules()
          .then((rules) => {
            const rule = rules.find((r) => r.id === id);
            if (!rule) throw new Error('gone');
            onClose();
            openRuleSheet({ kind: rule.kind, rule, prefill: null });
          })
          .catch(() => setError('That plan could not be opened.'));
    }
    return undefined;
  };

  const lines = bill?.lines ?? [];
  const adds = lines.filter((l) => l.kind === 'typed' || l.kind === 'purchase' || l.kind === 'plan');
  const inside = lines.filter((l) => l.kind === 'inside_typed');
  const payments = lines.filter((l) => l.kind === 'payment');

  return (
    <Sheet open={bill !== null} onClose={onClose} title={bill ? `Bill due ${format(parseISO(bill.due), 'd MMM yyyy')}` : undefined}>
      {bill && (
        <div className="space-y-4 pb-2">
          <div className="num space-y-1 rounded-card border-2 border-stroke bg-surface-2 px-4 py-3 text-footnote">
            <p className="flex justify-between"><span className="text-ink-2">The bill</span>{formatPHP(bill.amount)}</p>
            {bill.paid !== '0.00' && (
              <p className="flex justify-between"><span className="text-ink-2">Paid</span>−{formatPHP(bill.paid)}</p>
            )}
            <p className={`flex justify-between border-t border-stroke/40 pt-1 font-semibold ${bill.overdue ? 'text-danger' : ''}`}>
              <span>{bill.overdue ? 'Overdue' : 'Left to pay'}</span>{formatPHP(bill.left)}
            </p>
          </div>
          {adds.length > 0 && (
            <Group title="What makes up this bill">
              {adds.map((line, i) => <LineRow key={`a${i}`} line={line} label={label(line)} onOpen={open(line)} />)}
            </Group>
          )}
          {inside.length > 0 && (
            <Group title="Already in the card app’s figure" note="Counted inside the amount you typed, so not added again.">
              {inside.map((line, i) => <LineRow key={`i${i}`} line={line} label={label(line)} muted onOpen={open(line)} />)}
            </Group>
          )}
          {payments.length > 0 && (
            <Group title="Paid by" note="Payments into the card settle the oldest bill first.">
              {payments.map((line, i) => <LineRow key={`p${i}`} line={line} label={label(line)} onOpen={open(line)} />)}
            </Group>
          )}
          {error && <p className="text-footnote text-danger">{error}</p>}
        </div>
      )}
    </Sheet>
  );
}
