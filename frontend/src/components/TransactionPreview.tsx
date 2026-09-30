/**
 * One transaction, read-only (TXN-23, 2026-09-20, user: "I want a preview of the data first and a
 * button if I want to edit"). Tapping a row on the Account page, Home or the Calendar opens this;
 * Edit opens the sheet that used to open on the tap itself.
 *
 * It shows what the row could not: every split with its category, the tags, the note, the receipt,
 * the plan behind a posted payment, the money back on a purchase, and when the entry was recorded.
 * The receipt is the one thing it changes: attaching proof alters nothing about the entry.
 *
 * A balance adjustment (ACC-29) has no Edit - it is written when a balance is set, and editing its
 * amount would contradict the record - only Delete, as the sheet has always offered.
 *
 * Delete asks twice here: a row is tapped by accident far more easily than the editor is opened. It is a
 * BUTTON, not red words, and the second tap is a solid red one - as plain text beside a filled Edit it read as a
 * label, so a payment made by mistake looked impossible to take back (user, 2026-09-21).
 */
import { format, parseISO } from 'date-fns';
import { useEffect, useState } from 'react';
import { useLookups } from '../hooks/useLookups';
import { ApiError } from '../lib/api';
import { formatPHP } from '../lib/money';
import { ensureRules } from '../lib/prefetch';
import { deleteTransaction, getTransaction } from '../lib/transactions';
import { moneyIn } from './TransactionRow';
import { isPending, useLedgerStore } from '../stores/ledgerStore';
import { useUiStore } from '../stores/uiStore';
import { ReceiptControl } from './ReceiptControl';
import { offerUndo } from './UndoToast';
import { Button } from './ui/Button';
import { Sheet } from './ui/Sheet';

const day = (iso: string) => format(parseISO(iso), 'EEE, d MMM yyyy');

function Line({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5 text-footnote">
      <span className="shrink-0 text-ink-2">{label}</span>
      <span className="min-w-0 text-right">{children}</span>
    </div>
  );
}

export function TransactionPreview() {
  const row = useUiStore((s) => s.preview);
  const close = useUiStore((s) => s.closePreview);
  const openAddSheet = useUiStore((s) => s.openAddSheet);
  const openRuleSheet = useUiStore((s) => s.openRuleSheet);
  const lookups = useLookups();
  const ledger = useLedgerStore();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setConfirming(false);
    setBusy(false);
    setError(null);
  }, [row?.id]);

  const remove = async () => {
    if (!row) return;
    if (!confirming) {
      setConfirming(true);
      return;
    }
    setBusy(true);
    try {
      const outcome = await deleteTransaction(row.id);
      ledger.removeIds(outcome.transactions.map((t) => t.id), outcome);
      close();
      offerUndo(row); // TXN-25 - and it waits under More → Recently deleted for 30 days
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not delete. Try again.');
      setBusy(false);
    }
  };

  const openPlan = async (ruleId: number) => {
    setError(null);
    try {
      // The whole rule list, to open one plan - from the cache the Recurring
      // screen and the account pages already fill.
      const rule = (await ensureRules()).find((r) => r.id === ruleId);
      if (!rule) throw new Error('gone');
      openRuleSheet({ kind: rule.kind, rule, prefill: null });
    } catch {
      setError('That plan could not be opened.');
    }
  };

  const openLinked = async (id: number) => {
    setError(null);
    try {
      useUiStore.getState().openPreview(await getTransaction(id));
    } catch {
      setError('That entry could not be opened.');
    }
  };

  if (!row) return <Sheet open={false} onClose={close}>{null}</Sheet>;

  const account = lookups.accountById.get(row.account_id);
  const counter = row.counter_account_id != null ? lookups.accountById.get(row.counter_account_id) : undefined;
  const adjustment = row.type === 'adjustment';
  const inward = moneyIn(row);
  const only = row.splits.length === 1 ? row.splits[0] : null;  // one category, the usual case
  const tags = (row.tag_ids ?? []).map((id) => lookups.tagById.get(id)?.name).filter(Boolean);
  const [from, to] = row.direction === 'in' ? [counter, account] : [account, counter];
  const title = adjustment
    ? row.direction === 'out' ? 'Unrecorded loss' : 'Unrecorded gain'
    : row.type === 'transfer' ? 'Transfer' : row.type === 'income' ? 'Income' : 'Expense';

  return (
    <Sheet open onClose={close} title={title}>
      <div className="space-y-3 pb-2">
        <output className={`num block pt-1 text-center text-display ${inward ? 'text-ok' : 'text-ink'}`}>
          {inward ? '+' : ''}
          {formatPHP(inward ? row.amount : `-${row.amount}`)}
        </output>
        {row.merchant && <p className="text-center text-body font-semibold">{row.merchant}</p>}

        <div className="divide-y divide-stroke/60 rounded-card border-2 border-stroke bg-surface-2 px-4 py-1">
          <Line label="Date">{day(row.txn_date)}</Line>
          {row.type === 'transfer' ? (
            <Line label="Moved">{`${from?.name ?? 'Account'} → ${to?.name ?? 'Account'}`}</Line>
          ) : (
            <Line label="Account">{account?.name ?? 'Account'}</Line>
          )}
          {only && row.type !== 'transfer' && !adjustment && (
            <Line label="Category">
              {only.category_id != null ? lookups.categoryById.get(only.category_id)?.name ?? 'Uncategorised' : 'Uncategorised'}
            </Line>
          )}
          {row.splits.length > 1 &&
            row.splits.map((split, i) => (
              <Line key={i} label={i === 0 ? `Split · ${row.splits.length} categories` : ''}>
                <span className="num">
                  {split.category_id != null ? lookups.categoryById.get(split.category_id)?.name ?? 'Uncategorised' : 'Uncategorised'}
                  {' · '}
                  {formatPHP(split.amount)}
                </span>
                {split.note && <span className="block text-caption text-ink-3">{split.note}</span>}
              </Line>
            ))}
          {tags.length > 0 && <Line label="Tags">{tags.join(', ')}</Line>}
          {row.notes && <Line label="Note">{row.notes}</Line>}
          {row.card_posted_on && <Line label="Posted by the bank">{day(row.card_posted_on)}</Line>}
          {row.interest_on && <Line label="Savings interest for">{day(row.interest_on)}</Line>}
          {row.created_at && <Line label="Recorded">{format(parseISO(row.created_at), 'd MMM yyyy, HH:mm')}</Line>}
        </div>

        {row.recurring_id != null && (
          <Button variant="secondary" block onClick={() => void openPlan(row.recurring_id as number)}>
            Open the plan behind this
          </Button>
        )}
        {row.cashback && (
          <p className="num rounded-card border-2 border-stroke bg-surface-2 px-4 py-3 text-footnote text-ink-2">
            {formatPHP(row.cashback.amount)} came back on this purchase
            {row.cashback_id != null && (
              <button type="button" className="ml-1 font-semibold text-accent-ink" onClick={() => void openLinked(row.cashback_id as number)}>
                see it
              </button>
            )}
          </p>
        )}
        {row.cashback_of != null && (
          <p className="rounded-card border-2 border-stroke bg-surface-2 px-4 py-3 text-footnote text-ink-2">
            Money back on a purchase.{' '}
            <button type="button" className="font-semibold text-accent-ink" onClick={() => void openLinked(row.cashback_of as number)}>
              See the purchase
            </button>
          </p>
        )}
        {/* TXN-15. A receipt or a payment's screenshot is attached right here, not only
            behind Edit (2026-09-30, user) - it adds proof and changes nothing about the entry.
            A transfer's two legs share it, so either account's page shows it. */}
        {!adjustment && !isPending(row) ? (
          <ReceiptControl transactionId={row.id} attachmentId={row.attachment_id ?? null} />
        ) : row.attachment_id != null && (
          <ReceiptControl transactionId={row.id} attachmentId={row.attachment_id} readOnly />
        )}
        {adjustment && (
          <p className="rounded-card border-2 border-stroke bg-surface-2 px-4 py-3 text-footnote text-ink-2">
            Recorded when you set this account’s balance. It moves the balance only — your budget stays the same —
            and it can’t be edited; delete it and set the balance again.
          </p>
        )}

        {error && <p className="text-footnote text-danger">{error}</p>}
        {!isPending(row) && (
          <div className={adjustment ? '' : 'grid grid-cols-2 gap-2'}>
            {!adjustment && <Button onClick={() => openAddSheet(row)}>Edit</Button>}
            <Button
              variant={confirming ? 'danger' : 'secondary'}
              block={adjustment}
              className={confirming ? '' : 'text-danger'}
              onClick={() => void remove()}
              disabled={busy}
            >
              {confirming ? 'Tap again to delete' : 'Delete'}
            </Button>
          </div>
        )}
      </div>
    </Sheet>
  );
}
